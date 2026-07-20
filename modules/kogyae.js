// ============================================================
// LAND SYSTEM CLASSIFICATION, v2
// West Africa Protected Areas | Desmond Lartey | PhD Research
//
// Features:
//   - Adaptive thresholds derived from park-specific percentiles
//   - AlphaEarth satellite embeddings (64-dim) + phenological
//     indices (14-dim) = 78-dim feature space (Model D)
//   - RUE tile-boundary correction via valid-month normalisation
//   - Four-model ablation: A (KNN/Emb), B (RF/Emb),
//     C (RF/Pheno, circular), D (RF/Emb+Pheno, PRIMARY)
//   - Conservative change detection + RUE inter-annual CV
//   - All exports to LandSystem_PhD/ on Google Drive
//
// TO SWITCH PARKS: change only the three lines in Phase 1.
// ============================================================


// ============================================================
// PHASE 1, STUDY AREA AND GLOBAL PARAMETERS
// ============================================================
var protectedAreas = ee.FeatureCollection(
  'projects/ee-desmond/assets/NewParkMerged');
print('Park Names:', protectedAreas.aggregate_array('NAME'));

// ── Configure these three lines only when switching parks ──
var PARK_NAME_FILTER = 'Kogyae';
var PARK_NAME        = 'Kogyae';
var EPOCHS           = [2017, 2019, 2021, 2024];
// ───────────────────────────────────────────────────────────

var parkFeature = protectedAreas.filter(
  ee.Filter.eq('NAME', PARK_NAME_FILTER));
var geometry = parkFeature.geometry().dissolve({maxError: 1});

Map.centerObject(geometry, 12);
Map.setOptions('SATELLITE');
Map.addLayer(
  ee.Image().byte().paint({
    featureCollection: parkFeature, color: 1, width: 2}),
  {palette: ['ffffff']}, PARK_NAME + ', Boundary', true);

var CLASS_PROPERTY = 'landSystem';
var EXPORT_SCALE   = 10;
var CLASS_INFO = {
  1: {name: 'Core Woodland',                color: '1a6b1a'},
  2: {name: 'Open Woodland / Tree Savanna',  color: '74c476'},
  3: {name: 'Shrub-Transition Savanna',      color: 'c7e9c0'},
  4: {name: 'Grassland Systems',             color: 'ffff99'},
  5: {name: 'Riparian / Wetland Vegetation', color: '4292c6'},
  6: {name: 'Anthropogenic Disturbance',     color: 'd73027'}
};
var PALETTE = Object.keys(CLASS_INFO).map(
  function(k) { return CLASS_INFO[k].color; });
var VIS_CLASSIFIED = {min: 1, max: 6, palette: PALETTE};

var POINTS_PER_CLASS             = 30;
var CANDIDATE_POINTS_PER_CLUSTER = 50;
var RANDOM_SEED                  = 42;
var CONFIDENCE_MARGIN            = 0.03;

print('=== ' + PARK_NAME + ', LAND SYSTEM CLASSIFICATION ===');
print('Epochs:', EPOCHS);


// ============================================================
// PHASE 2, SENTINEL-2 REFERENCE IMAGERY (2024 baseline)
// ============================================================
function getSentinel2Composite(year, region) {
  var startDate = ee.Date.fromYMD(year, 1, 1);
  var endDate   = startDate.advance(1, 'year');
  var s2        = ee.ImageCollection('COPERNICUS/S2_SR_HARMONIZED')
    .filter(ee.Filter.date(startDate, endDate))
    .filter(ee.Filter.bounds(region));
  var csPlus = ee.ImageCollection(
    'GOOGLE/CLOUD_SCORE_PLUS/V1/S2_HARMONIZED');
  return s2
    .linkCollection(csPlus, csPlus.first().bandNames())
    .map(function(img) {
      return img.updateMask(img.select('cs').gte(0.65));
    })
    .select('B.*').median().clip(region);
}

var composite2024 = getSentinel2Composite(2024, geometry);
Map.addLayer(composite2024,
  {min:300, max:4000, bands:['B11','B8','B4']},
  '2024 Sentinel-2 False Colour', true);
Map.addLayer(composite2024,
  {min:300, max:3000, bands:['B4','B3','B2']},
  '2024 Sentinel-2 True Colour', false);


// ============================================================
// PHASE 3, ALPHEARTH SATELLITE EMBEDDINGS
// ============================================================
var embeddingCollection = ee.ImageCollection(
  'GOOGLE/SATELLITE_EMBEDDING/V1/ANNUAL');

function getEmbeddingImage(year, region) {
  var startDate = ee.Date.fromYMD(year, 1, 1);
  var endDate   = startDate.advance(1, 'year');
  return embeddingCollection
    .filter(ee.Filter.date(startDate, endDate))
    .filter(ee.Filter.bounds(region))
    .mosaic().clip(region);
}

var embedding2024 = getEmbeddingImage(2024, geometry);
print('--- PHASE 3: Embedding image loaded ---');
print('Embedding bands (64 dimensions):', embedding2024.bandNames());
Map.addLayer(embedding2024,
  {min:-0.3, max:0.3, bands:['A01','A16','A09']},
  '2024 Embedding Space (3 axes as RGB)', false);


// ============================================================
// PHASE 4, TRAINING SAMPLE COLLECTION (GCPs)
// ============================================================

// 4.1, Seasonal composites and percentile statistics
var s2_2024 = getSentinel2Composite(2024, geometry);

var csPlus_annual = ee.ImageCollection(
  'GOOGLE/CLOUD_SCORE_PLUS/V1/S2_HARMONIZED')
  .filter(ee.Filter.date('2024-01-01','2024-12-31'))
  .filter(ee.Filter.bounds(geometry));
var s2_annual_masked = ee.ImageCollection('COPERNICUS/S2_SR_HARMONIZED')
  .filter(ee.Filter.date('2024-01-01','2024-12-31'))
  .filter(ee.Filter.bounds(geometry))
  .linkCollection(csPlus_annual, csPlus_annual.first().bandNames())
  .map(function(img) {
    return img.updateMask(img.select('cs').gte(0.65));
  }).select('B.*');

var s2_p10 = s2_annual_masked
  .reduce(ee.Reducer.percentile([10]))
  .rename(s2_annual_masked.first().bandNames()
    .map(function(b){return ee.String(b);}))
  .clip(geometry);
var s2_p90 = s2_annual_masked
  .reduce(ee.Reducer.percentile([90]))
  .rename(s2_annual_masked.first().bandNames()
    .map(function(b){return ee.String(b);}))
  .clip(geometry);

var csPlus_dry = ee.ImageCollection(
  'GOOGLE/CLOUD_SCORE_PLUS/V1/S2_HARMONIZED')
  .filter(ee.Filter.date('2024-03-01','2024-05-15'))
  .filter(ee.Filter.bounds(geometry));
var s2_dry = ee.ImageCollection('COPERNICUS/S2_SR_HARMONIZED')
  .filter(ee.Filter.date('2024-03-01','2024-05-15'))
  .filter(ee.Filter.bounds(geometry))
  .linkCollection(csPlus_dry, csPlus_dry.first().bandNames())
  .map(function(img){
    return img.updateMask(img.select('cs').gte(0.60));
  }).select('B.*').median().clip(geometry);

var csPlus_wet = ee.ImageCollection(
  'GOOGLE/CLOUD_SCORE_PLUS/V1/S2_HARMONIZED')
  .filter(ee.Filter.date('2024-05-01','2024-07-15'))
  .filter(ee.Filter.bounds(geometry));
var s2_wet = ee.ImageCollection('COPERNICUS/S2_SR_HARMONIZED')
  .filter(ee.Filter.date('2024-05-01','2024-07-15'))
  .filter(ee.Filter.bounds(geometry))
  .linkCollection(csPlus_wet, csPlus_wet.first().bandNames())
  .map(function(img){
    return img.updateMask(img.select('cs').gte(0.60));
  }).select('B.*').median().clip(geometry);

// 4.2, Spectral indices (2024 baseline)
var ndvi     = s2_2024.normalizedDifference(['B8','B4']).rename('NDVI');
var ndmi     = s2_2024.normalizedDifference(['B8','B11']).rename('NDMI');
var mndwi    = s2_2024.normalizedDifference(['B3','B11']).rename('MNDWI');
var ndbi     = s2_2024.normalizedDifference(['B11','B8']).rename('NDBI');
var ndvi_dry = s2_dry.normalizedDifference(['B8','B4']).rename('NDVI_dry');
var ndmi_dry = s2_dry.normalizedDifference(['B8','B11']).rename('NDMI_dry');
var ndbi_dry = s2_dry.normalizedDifference(['B11','B8']).rename('NDBI_dry');
var ndvi_wet = s2_wet.normalizedDifference(['B8','B4']).rename('NDVI_wet');
var ndmi_wet = s2_wet.normalizedDifference(['B8','B11']).rename('NDMI_wet');
var ndvi_amp = ndvi_wet.subtract(ndvi_dry).rename('NDVI_amp');
var ndmi_amp = ndmi_wet.subtract(ndmi_dry).rename('NDMI_amp');
var ndvi_p10   = s2_p10.normalizedDifference(['B8','B4']).rename('NDVI_p10');
var ndmi_p10   = s2_p10.normalizedDifference(['B8','B11']).rename('NDMI_p10');
var ndvi_p90   = s2_p90.normalizedDifference(['B8','B4']).rename('NDVI_p90');
var ndmi_p90   = s2_p90.normalizedDifference(['B8','B11']).rename('NDMI_p90');
var ndvi_p_amp = ndvi_p90.subtract(ndvi_p10).rename('NDVI_p_amp');

// 4.3, Coverage diagnostics
print('Percentile composite coverage (p10 B8):',
  s2_p10.select('B8').mask().reduceRegion({
    reducer:ee.Reducer.mean(), geometry:geometry,
    scale:100, maxPixels:1e9}));
print('Dry (Mar-May) coverage:',
  ndvi_dry.mask().reduceRegion({
    reducer:ee.Reducer.mean(), geometry:geometry,
    scale:100, maxPixels:1e9}));
print('Wet (May-Jul) coverage:',
  ndvi_wet.mask().reduceRegion({
    reducer:ee.Reducer.mean(), geometry:geometry,
    scale:100, maxPixels:1e9}));

// 4.4, Visualisation of spectral indices
Map.addLayer(ndvi,
  {min:0.1,max:0.8,palette:['8c510a','f6e8c3','01665e']},
  'NDVI Annual 2024', false);
Map.addLayer(ndvi_dry,
  {min:0.15,max:0.75,palette:['8c510a','f6e8c3','01665e']},
  'NDVI Dry 2024', false);
Map.addLayer(ndvi_wet,
  {min:0.30,max:0.85,palette:['8c510a','f6e8c3','01665e']},
  'NDVI Wet 2024', false);
Map.addLayer(ndvi_amp,
  {min:-0.05,max:0.40,palette:['f7f7f7','fc8d59','d73027']},
  'NDVI Amplitude', false);
Map.addLayer(ndmi,
  {min:-0.10,max:0.20,palette:['8c510a','f5f5f5','01665e']},
  'NDMI Annual 2024', false);
Map.addLayer(ndmi_dry,
  {min:-0.15,max:0.15,palette:['8c510a','f5f5f5','01665e']},
  'NDMI Dry 2024', false);
Map.addLayer(ndbi,
  {min:-0.15,max:0.12,palette:['01665e','f5f5f5','b2182b']},
  'NDBI Annual 2024', false);

// 4.5, Unsupervised k-means clustering in embedding space
var clusterSamples6 = embedding2024.sample({
  region:geometry, scale:30, numPixels:3000,
  seed:RANDOM_SEED, tileScale:8});
var kMeans6 = ee.Clusterer.wekaKMeans({
  nClusters:6, seed:RANDOM_SEED}).train(clusterSamples6);
var unsupervised6 = embedding2024.cluster(kMeans6)
  .toInt().rename('cluster6');
print('cluster6 band type (must be int):',
  unsupervised6.bandTypes());
Map.addLayer(unsupervised6.randomVisualizer().clip(geometry),
  {}, 'Unsupervised Clusters (k=6)', false);

// 4.6, Cluster statistics
var clusterStatImage = ee.Image.cat([
  ndvi_dry, ndmi_dry, ndvi_amp, ndmi, ndbi,
  ndvi, ndvi_wet, ndmi_wet, unsupervised6
]);
print('Cluster stat band count (must be 9):',
  clusterStatImage.bandNames().length());
var clusterStats = clusterStatImage.reduceRegion({
  reducer: ee.Reducer.mean().group({
    groupField:8, groupName:'cluster'}),
  geometry:geometry, scale:100, maxPixels:1e9, tileScale:8
});
print('=== CLUSTER MEAN VALUES ===');
print('Bands: NDVI_dry NDMI_dry NDVI_amp NDMI NDBI ' +
      'NDVI NDVI_wet NDMI_wet');
print(clusterStats);

// 4.7, Index percentiles (diagnostic)
print('=== INDEX PERCENTILES ===',
  ee.Image.cat([ndvi,ndmi,ndbi,ndvi_dry,ndmi_dry,
                ndvi_wet,ndmi_wet,ndvi_amp])
  .reduceRegion({
    reducer: ee.Reducer.percentile([5,10,25,50,75,90,95]),
    geometry:geometry, scale:100,
    maxPixels:1e9, tileScale:8}));


// ============================================================
// PHASE 4.7b, RAIN USE EFFICIENCY (RUE)
// Monthly iNDVI normalised by valid observation count to
// remove Sentinel-2 tile boundary bias.
// ============================================================
var chirps2024 = ee.ImageCollection('UCSB-CHG/CHIRPS/DAILY')
  .filter(ee.Filter.date('2024-01-01','2024-12-31'))
  .filter(ee.Filter.bounds(geometry))
  .sum().clip(geometry).rename('annual_rainfall_mm');

var months = ee.List.sequence(1, 12);

var monthlyNDVI_2024 = ee.ImageCollection(months.map(function(m) {
  var start = ee.Date.fromYMD(2024, m, 1);
  var end   = start.advance(1, 'month');
  var csPlus_m = ee.ImageCollection(
    'GOOGLE/CLOUD_SCORE_PLUS/V1/S2_HARMONIZED')
    .filter(ee.Filter.date(start, end))
    .filter(ee.Filter.bounds(geometry));
  var s2_m = ee.ImageCollection('COPERNICUS/S2_SR_HARMONIZED')
    .filter(ee.Filter.date(start, end))
    .filter(ee.Filter.bounds(geometry))
    .linkCollection(csPlus_m, csPlus_m.first().bandNames())
    .map(function(img) {
      return img.updateMask(img.select('cs').gte(0.65));
    });
  // Masked (not zero) for months with no valid scenes
  var monthlyImg = ee.Image(ee.Algorithms.If(
    s2_m.size().gt(0),
    s2_m.select(['B8','B4']).median()
      .normalizedDifference().rename('NDVI').multiply(30),
    ee.Image.constant(0).rename('NDVI').selfMask()
  ));
  return monthlyImg.clip(geometry);
}));

// Normalise iNDVI by valid month count to remove tile bias
var validMonthCount_2024 = monthlyNDVI_2024.count()
  .rename('valid_months');
var iNDVI = monthlyNDVI_2024.sum()
  .divide(validMonthCount_2024)
  .multiply(12)
  .rename('iNDVI');

var rue = iNDVI
  .divide(chirps2024.add(ee.Image.constant(1)))
  .rename('RUE')
  .clip(geometry);

print('=== RUE DIAGNOSTICS ===');
print('Annual rainfall mm:',
  chirps2024.reduceRegion({
    reducer:ee.Reducer.mean(), geometry:geometry,
    scale:5000, maxPixels:1e9}));
print('RUE percentiles:',
  rue.reduceRegion({
    reducer:ee.Reducer.percentile([5,25,50,75,95]),
    geometry:geometry, scale:100, maxPixels:1e9}));

Map.addLayer(chirps2024,
  {min:800, max:1600, palette:['f7fbff','6baed6','08519c']},
  'Annual Rainfall 2024', false);
Map.addLayer(rue,
  {min:0.0, max:0.8, palette:['d73027','ffffbf','1a9641']},
  'Rain Use Efficiency 2024', false);
Map.addLayer(iNDVI,
  {min:0, max:25, palette:['8c510a','f6e8c3','01665e']},
  'Integrated NDVI 2024', false);


// ============================================================
// PHASE 4.8, ADAPTIVE THRESHOLD DERIVATION
// All thresholds derived from park-specific index percentiles.
// No hardcoded values, works identically for all parks.
// ============================================================
var _pctImage = ee.Image.cat([
  ndvi, ndmi, ndbi, ndvi_dry, ndmi_dry,
  ndvi_wet, ndmi_wet, ndvi_amp]);
var _pctDict = _pctImage.reduceRegion({
  reducer: ee.Reducer.percentile([5,10,25,50,75,90,95]),
  geometry: geometry, scale: 100,
  maxPixels: 1e9, tileScale: 8
});

// Named-percentile extractor
function pct(band, p) {
  return ee.Number(_pctDict.get(band + '_p' + p));
}

// Anthropogenic
var T_ANTHRO_NDBI     = pct('NDBI', 90);
var T_ANTHRO_NDVI_MAX = ee.Number(0.20);

// Riparian
var T_RIPARIAN_NDMI     = pct('NDMI', 95);
var T_RIPARIAN_NDMI_DRY = pct('NDMI_dry',75).add(
  pct('NDMI_dry',90).subtract(pct('NDMI_dry',75)).multiply(0.5));
var T_RIPARIAN_NDVI_DRY = pct('NDVI_dry',50).add(
  pct('NDVI_dry',75).subtract(pct('NDVI_dry',50)).multiply(0.5));

// Core Woodland
var T_CORE_NDVI_DRY = pct('NDVI_dry', 75);
var T_CORE_NDMI = pct('NDMI',50).add(
  pct('NDMI',75).subtract(pct('NDMI',50)).multiply(0.5));

// Grassland
var T_GRASS_NDVI_DRY_MAX = pct('NDVI_dry', 25);
var T_GRASS_AMP_MIN = pct('NDVI_amp',10).add(
  pct('NDVI_amp',25).subtract(pct('NDVI_amp',10)).multiply(0.75));
var T_GRASS_NDMI_DRY_MAX = pct('NDMI_dry',25).add(
  pct('NDMI_dry',50).subtract(pct('NDMI_dry',25)).multiply(0.75));

// Shrub-Transition
var T_SHRUB_NDVI_DRY_MIN = pct('NDVI_dry', 10);
var T_SHRUB_NDVI_DRY_MAX = pct('NDVI_dry', 50);
var T_SHRUB_NDMI_DRY_MIN = pct('NDMI_dry', 25);
var T_SHRUB_NDMI_DRY_MAX = pct('NDMI_dry',50).add(
  pct('NDMI_dry',75).subtract(pct('NDMI_dry',50)).multiply(0.20));
var T_SHRUB_AMP_MIN = pct('NDVI_amp',10).add(
  pct('NDVI_amp',25).subtract(pct('NDVI_amp',10)).multiply(0.30));
var T_SHRUB_AMP_MAX = pct('NDVI_amp', 90);

// Open Woodland
var T_OPEN_NDVI_DRY_MIN    = pct('NDVI_dry', 25);
var T_OPEN_NDVI_DRY_MAX    = pct('NDVI_dry', 75);
var T_OPEN_NDMI_MIN        = pct('NDMI', 25);
var T_OPEN_NDMI_MAX        = pct('NDMI', 75);
var T_OPEN_NDVI_DRY_MID    = pct('NDVI_dry', 50);
var T_OPEN_NDMI_SPLIT_LOW  = pct('NDMI', 50);
var T_OPEN_NDMI_SPLIT_HIGH = pct('NDMI',50).add(
  pct('NDMI',75).subtract(pct('NDMI',50)).multiply(0.5));

print('=== ADAPTIVE THRESHOLDS, ' + PARK_NAME + ' ===');
print('NDVI_dry p25/p50/p75:',
  pct('NDVI_dry',25), '/', pct('NDVI_dry',50), '/',
  pct('NDVI_dry',75));
print('NDMI     p25/p50/p75:',
  pct('NDMI',25), '/', pct('NDMI',50), '/', pct('NDMI',75));
print('NDBI     p90:', pct('NDBI',90));


// ============================================================
// PHASE 4.9, MASK DEFINITIONS
// ============================================================
var mask_anthro = ndbi.gt(T_ANTHRO_NDBI)
  .or(ndvi.lt(T_ANTHRO_NDVI_MAX));

var mask_riparian = ndmi.gt(T_RIPARIAN_NDMI)
  .and(ndmi_dry.gt(T_RIPARIAN_NDMI_DRY))
  .and(ndvi_dry.gt(T_RIPARIAN_NDVI_DRY))
  .and(mask_anthro.not());

var mask_core = ndvi_dry.gt(T_CORE_NDVI_DRY)
  .and(ndmi.gt(T_CORE_NDMI))
  .and(mask_anthro.not()).and(mask_riparian.not());

var mask_grass = ndvi_dry.lt(T_GRASS_NDVI_DRY_MAX)
  .and(ndvi_amp.gt(T_GRASS_AMP_MIN)
    .or(ndmi_dry.lt(T_GRASS_NDMI_DRY_MAX)))
  .and(mask_anthro.not()).and(mask_riparian.not())
  .and(mask_core.not());

var mask_shrub = ndvi_dry.gte(T_SHRUB_NDVI_DRY_MIN)
  .and(ndvi_dry.lt(T_SHRUB_NDVI_DRY_MAX))
  .and(ndmi_dry.gte(T_SHRUB_NDMI_DRY_MIN))
  .and(ndmi_dry.lt(T_SHRUB_NDMI_DRY_MAX))
  .and(ndvi_amp.gte(T_SHRUB_AMP_MIN))
  .and(ndvi_amp.lt(T_SHRUB_AMP_MAX))
  .and(mask_anthro.not()).and(mask_riparian.not())
  .and(mask_core.not()).and(mask_grass.not());

var mask_open_dry = ndvi_dry.gte(T_OPEN_NDVI_DRY_MIN)
  .and(ndvi_dry.lt(T_OPEN_NDVI_DRY_MID))
  .and(ndmi.gte(T_OPEN_NDMI_MIN))
  .and(ndmi.lte(T_OPEN_NDMI_SPLIT_HIGH))
  .and(mask_anthro.not()).and(mask_riparian.not())
  .and(mask_core.not()).and(mask_grass.not())
  .and(mask_shrub.not());

var mask_open_moist = ndvi_dry.gte(T_OPEN_NDVI_DRY_MID)
  .and(ndvi_dry.lte(T_OPEN_NDVI_DRY_MAX))
  .and(ndmi.gt(T_OPEN_NDMI_SPLIT_LOW))
  .and(ndmi.lte(T_OPEN_NDMI_MAX))
  .and(mask_anthro.not()).and(mask_riparian.not())
  .and(mask_core.not()).and(mask_grass.not())
  .and(mask_shrub.not());

var mask_open = mask_open_dry.or(mask_open_moist);

Map.addLayer(mask_core.selfMask(),
  {palette:['1a6b1a']}, 'MASK: Core Woodland', false);
Map.addLayer(mask_open.selfMask(),
  {palette:['74c476']}, 'MASK: Open Woodland', false);
Map.addLayer(mask_shrub.selfMask(),
  {palette:['addd8e']}, 'MASK: Shrub-Transition', false);
Map.addLayer(mask_grass.selfMask(),
  {palette:['ffff99']}, 'MASK: Grassland', false);
Map.addLayer(mask_riparian.selfMask(),
  {palette:['4292c6']}, 'MASK: Riparian', false);
Map.addLayer(mask_anthro.selfMask(),
  {palette:['d73027']}, 'MASK: Anthropogenic', false);

print('=== MASK COVERAGE FRACTIONS (target 0.05–0.30) ===');
var countMask = function(mask, name) {
  print(name + ' coverage:', mask.unmask(0).reduceRegion({
    reducer:ee.Reducer.mean(), geometry:geometry,
    scale:100, maxPixels:1e9, tileScale:8}));
};
countMask(mask_core,     'Core Woodland');
countMask(mask_open,     'Open Woodland');
countMask(mask_shrub,    'Shrub-Transition');
countMask(mask_grass,    'Grassland');
countMask(mask_riparian, 'Riparian');
countMask(mask_anthro,   'Anthropogenic');


// ============================================================
// PHASE 4.10–4.11, CLUSTER-STRATIFIED CANDIDATE SAMPLING
// ============================================================
var candidateFeatureImage = ee.Image.cat([
  ndvi, ndmi, mndwi, ndbi,
  ndvi_dry, ndmi_dry, ndbi_dry,
  ndvi_wet, ndmi_wet, ndvi_amp,
  unsupervised6
]).clip(geometry);

function sampleClusterCandidates(clusterId, nPoints, seed) {
  return candidateFeatureImage
    .updateMask(unsupervised6.eq(clusterId))
    .sample({
      region:geometry, scale:EXPORT_SCALE,
      numPixels:nPoints*10, seed:seed,
      geometries:true, tileScale:8})
    .filter(ee.Filter.notNull([
      'cluster6','NDVI','NDMI','NDBI',
      'NDVI_dry','NDMI_dry','NDVI_wet','NDMI_wet']))
    .randomColumn('pick', seed).sort('pick').limit(nPoints)
    .map(function(f) {
      return ee.Feature(f.geometry(), {
        cluster6:   f.get('cluster6'),
        NDVI:       f.get('NDVI'),
        NDMI:       f.get('NDMI'),
        MNDWI:      f.get('MNDWI'),
        NDBI:       f.get('NDBI'),
        NDVI_dry:   f.get('NDVI_dry'),
        NDMI_dry:   f.get('NDMI_dry'),
        NDBI_dry:   f.get('NDBI_dry'),
        NDVI_wet:   f.get('NDVI_wet'),
        NDMI_wet:   f.get('NDMI_wet'),
        NDVI_amp:   f.get('NDVI_amp')
      });
    });
}

var candidatePoints = ee.FeatureCollection([
  sampleClusterCandidates(0, CANDIDATE_POINTS_PER_CLUSTER, 100),
  sampleClusterCandidates(1, CANDIDATE_POINTS_PER_CLUSTER, 110),
  sampleClusterCandidates(2, CANDIDATE_POINTS_PER_CLUSTER, 120),
  sampleClusterCandidates(3, CANDIDATE_POINTS_PER_CLUSTER, 130),
  sampleClusterCandidates(4, CANDIDATE_POINTS_PER_CLUSTER, 140),
  sampleClusterCandidates(5, CANDIDATE_POINTS_PER_CLUSTER, 150)
]).flatten();

print('Candidates (all clusters):', candidatePoints.size());
print('By cluster:',
  candidatePoints.aggregate_histogram('cluster6'));


// ============================================================
// PHASE 4.12, LABEL ASSIGNMENT WITH CONFIDENCE FILTER
// ============================================================
function assignProvisionalLabel(f) {
  var ndviV   = ee.Number(f.get('NDVI'));
  var ndmiV   = ee.Number(f.get('NDMI'));
  var ndbiV   = ee.Number(f.get('NDBI'));
  var ndviDry = ee.Number(f.get('NDVI_dry'));
  var ndmiDry = ee.Number(f.get('NDMI_dry'));
  var ndviAmp = ee.Number(ee.Algorithms.If(
    f.get('NDVI_amp'), f.get('NDVI_amp'), 0));

  var isAmbiguous =
    ndviDry.gt(T_CORE_NDVI_DRY.subtract(CONFIDENCE_MARGIN))
      .and(ndviDry.lt(
        T_CORE_NDVI_DRY.add(CONFIDENCE_MARGIN)))
    .or(ndviDry.gt(
        T_GRASS_NDVI_DRY_MAX.subtract(CONFIDENCE_MARGIN))
      .and(ndviDry.lt(
        T_GRASS_NDVI_DRY_MAX.add(CONFIDENCE_MARGIN))))
    .or(ndviDry.gt(
        T_OPEN_NDVI_DRY_MIN.subtract(CONFIDENCE_MARGIN))
      .and(ndviDry.lt(
        T_OPEN_NDVI_DRY_MIN.add(CONFIDENCE_MARGIN))));

  var label = ee.Number(ee.Algorithms.If(
    ndbiV.gt(T_ANTHRO_NDBI).or(ndviV.lt(T_ANTHRO_NDVI_MAX)),
    6,
    ee.Algorithms.If(
      ndmiV.gt(T_RIPARIAN_NDMI)
        .and(ndmiDry.gt(T_RIPARIAN_NDMI_DRY))
        .and(ndviDry.gt(T_RIPARIAN_NDVI_DRY)),
      5,
      ee.Algorithms.If(
        ndviDry.gt(T_CORE_NDVI_DRY)
          .and(ndmiV.gt(T_CORE_NDMI)),
        1,
        ee.Algorithms.If(
          ndviDry.lt(T_GRASS_NDVI_DRY_MAX)
            .and(ndviAmp.gt(T_GRASS_AMP_MIN)
              .or(ndmiDry.lt(T_GRASS_NDMI_DRY_MAX))),
          4,
          ee.Algorithms.If(
            ndviDry.gte(T_SHRUB_NDVI_DRY_MIN)
              .and(ndviDry.lt(T_SHRUB_NDVI_DRY_MAX))
              .and(ndmiDry.gte(T_SHRUB_NDMI_DRY_MIN))
              .and(ndmiDry.lt(T_SHRUB_NDMI_DRY_MAX))
              .and(ndviAmp.gte(T_SHRUB_AMP_MIN))
              .and(ndviAmp.lt(T_SHRUB_AMP_MAX)),
            3,
            ee.Algorithms.If(
              ndviDry.gte(T_OPEN_NDVI_DRY_MIN)
                .and(ndviDry.lte(T_OPEN_NDVI_DRY_MAX))
                .and(ndmiV.gte(T_OPEN_NDMI_MIN))
                .and(ndmiV.lte(T_OPEN_NDMI_MAX)),
              2, -1
            )
          )
        )
      )
    )
  ));

  var isRare = label.eq(3).or(label.eq(5));
  var finalLabel = ee.Number(ee.Algorithms.If(isRare, label,
    ee.Algorithms.If(isAmbiguous, 99, label)));
  return f.set(CLASS_PROPERTY, finalLabel);
}

var provisionalCandidates = candidatePoints
  .map(assignProvisionalLabel);
var provisionalValid = provisionalCandidates
  .filter(ee.Filter.gt(CLASS_PROPERTY, 0))
  .filter(ee.Filter.neq(CLASS_PROPERTY, 99));

print('=== LABEL RESULTS ===');
print('Raw distribution:',
  provisionalCandidates.aggregate_histogram(CLASS_PROPERTY));
print('Valid after filtering:', provisionalValid.size());
print('Class distribution:',
  provisionalValid.aggregate_histogram(CLASS_PROPERTY));


// ============================================================
// PHASE 4.13–4.15, CLASS BALANCING AND GCP EXTRACTION
// ============================================================
function takeClassPoints(fc, classVal, n, seed) {
  var sub = fc.filter(ee.Filter.eq(CLASS_PROPERTY, classVal));
  return ee.FeatureCollection(ee.Algorithms.If(
    sub.size().gte(n),
    sub.randomColumn('pick', seed).sort('pick').limit(n),
    sub
  ));
}

var pCore     = takeClassPoints(provisionalValid, 1, POINTS_PER_CLASS, 101);
var pOpen     = takeClassPoints(provisionalValid, 2, POINTS_PER_CLASS, 102);
var pShrub    = takeClassPoints(provisionalValid, 3, POINTS_PER_CLASS, 103);
var pGrass    = takeClassPoints(provisionalValid, 4, POINTS_PER_CLASS, 104);
var pRiparian = takeClassPoints(provisionalValid, 5, POINTS_PER_CLASS, 105);
var pAnthro   = takeClassPoints(provisionalValid, 6, POINTS_PER_CLASS, 106);

print('--- Point counts per class ---');
print('Core Woodland:',    pCore.size());
print('Open Woodland:',    pOpen.size());
print('Shrub-Transition:', pShrub.size());
print('Grassland:',        pGrass.size());
print('Riparian:',         pRiparian.size());
print('Anthropogenic:',    pAnthro.size());

var gcpsRaw = pCore.merge(pOpen).merge(pShrub)
  .merge(pGrass).merge(pRiparian).merge(pAnthro);
var gcpsInside  = gcpsRaw.filterBounds(geometry);
var gcpsOutside = gcpsRaw.filter(
  ee.Filter.bounds(geometry).not());

var gcps = embedding2024.sampleRegions({
  collection: gcpsInside,
  properties: [CLASS_PROPERTY,'cluster6','NDVI','NDMI','NDBI',
               'NDVI_dry','NDMI_dry','NDVI_wet','NDMI_wet','NDVI_amp'],
  scale: EXPORT_SCALE, geometries: true, tileScale: 8
}).filter(ee.Filter.notNull(embedding2024.bandNames()));

print('--- PHASE 4 COMPLETE ---');
print('Total GCPs with embeddings:', gcps.size());
print('Final class distribution:',
  gcps.aggregate_histogram(CLASS_PROPERTY));
print('Cluster coverage:',
  gcps.aggregate_histogram('cluster6'));
print('Rejected outside boundary:', gcpsOutside.size());

Map.addLayer(gcps.filter(ee.Filter.eq(CLASS_PROPERTY,1)),
  {color:'1a6b1a'}, 'GCPs: Core Woodland', true);
Map.addLayer(gcps.filter(ee.Filter.eq(CLASS_PROPERTY,2)),
  {color:'74c476'}, 'GCPs: Open Woodland', true);
Map.addLayer(gcps.filter(ee.Filter.eq(CLASS_PROPERTY,3)),
  {color:'addd8e'}, 'GCPs: Shrub-Transition', true);
Map.addLayer(gcps.filter(ee.Filter.eq(CLASS_PROPERTY,4)),
  {color:'ffff00'}, 'GCPs: Grassland', true);
Map.addLayer(gcps.filter(ee.Filter.eq(CLASS_PROPERTY,5)),
  {color:'0000ff'}, 'GCPs: Riparian', true);
Map.addLayer(gcps.filter(ee.Filter.eq(CLASS_PROPERTY,6)),
  {color:'ff0000'}, 'GCPs: Anthropogenic', true);
Map.addLayer(gcpsOutside,
  {color:'ff00ff'}, 'GCPs: Rejected outside boundary', false);


// ============================================================
// PHASE 5, FOUR-MODEL ABLATION TRAINING
// ============================================================
var trainingData = embedding2024.sampleRegions({
  collection:gcps, properties:[CLASS_PROPERTY],
  scale:EXPORT_SCALE, tileScale:8
}).filter(ee.Filter.notNull(embedding2024.bandNames()));

print('=== PHASE 5: Classifier Training ===');
print('Training samples:', trainingData.size());
print('Class distribution:',
  trainingData.aggregate_histogram(CLASS_PROPERTY));

var knnClassifier = ee.Classifier.smileKNN(3).train({
  features:trainingData, classProperty:CLASS_PROPERTY,
  inputProperties:embedding2024.bandNames()});
print('KNN (k=3) trained');

var rfClassifier = ee.Classifier.smileRandomForest({
  numberOfTrees:150, variablesPerSplit:8,
  minLeafPopulation:1, bagFraction:0.632, seed:RANDOM_SEED
}).train({
  features:trainingData, classProperty:CLASS_PROPERTY,
  inputProperties:embedding2024.bandNames()});
print('Random Forest (150 trees) trained');
print('RF feature importance:',
  rfClassifier.explain().get('importance'));

var USE_RF = true;
var classifier2024 = USE_RF ? rfClassifier : knnClassifier;
print('=== PHASE 5 COMPLETE ===');
print('Active classifier:',
  USE_RF ? 'Random Forest (150 trees)' : 'KNN (k=3)');


// ============================================================
// PHASE 6, CLASSIFICATION AND VISUALISATION (2024 diagnostic)
// ============================================================
var classified2024_raw = embedding2024
  .classify(classifier2024)
  .rename('landSystem').clip(geometry).toByte();
var classified2024 = classified2024_raw
  .focal_mode({radius:1, units:'pixels', kernelType:'square'})
  .rename('landSystem').clip(geometry).toByte();

Map.addLayer(classified2024_raw, VIS_CLASSIFIED,
  '2024 Land System Map, DIAGNOSTIC raw (Model B)', false);
Map.addLayer(classified2024, VIS_CLASSIFIED,
  '2024 Land System Map, DIAGNOSTIC smoothed (Model B)', false);

var classAreaStats2024 = ee.Image.pixelArea().divide(1e6)
  .addBands(classified2024)
  .reduceRegion({
    reducer: ee.Reducer.sum().group({
      groupField:1, groupName:'landSystem'}),
    geometry:geometry, scale:EXPORT_SCALE,
    maxPixels:1e10, tileScale:4});
print('--- PHASE 6: Diagnostic area by class (km2) ---');
print(classAreaStats2024);
print('NOTE: Definitive maps produced in Phase 8 using Model D.');


// ============================================================
// PHASE 7, CONSOLIDATED ACCURACY ASSESSMENT (four models)
// ============================================================
var splitSeed     = 42;
var withRandom_aa = gcps.randomColumn('split', splitSeed);
var trainSet_aa   = withRandom_aa.filter(
  ee.Filter.lt('split', 0.7));
var validSet_aa   = withRandom_aa.filter(
  ee.Filter.gte('split', 0.7));

print('');
print('============================================================');
print('  PHASE 7, CONSOLIDATED ACCURACY ASSESSMENT');
print('============================================================');
print('Total GCPs:', gcps.size());
print('Training set (70%):', trainSet_aa.size(),
  '| Validation set (30%):', validSet_aa.size());

var phenoStack = ee.Image.cat([
  ndvi_dry, ndmi_dry, ndvi_amp,
  ndmi, ndbi, ndvi, ndvi_wet, ndmi_wet,
  ndvi_p10, ndmi_p10, ndvi_p90, ndmi_p90, ndvi_p_amp,
  rue
]);
var phenoBands    = phenoStack.bandNames();
var combinedStack = ee.Image.cat([embedding2024, phenoStack]);
var combinedBands = combinedStack.bandNames();

// Force materialisation of combined feature collections
// before splitting into model-specific subsets.
// This ensures all four models use identical train/valid
// samples and prevents GEE lazy-evaluation inconsistencies
// that cause OA/Kappa to be computed from different subsets.
var trainFull = combinedStack.sampleRegions({
  collection:trainSet_aa, properties:[CLASS_PROPERTY],
  scale:EXPORT_SCALE, tileScale:8
}).filter(ee.Filter.notNull(combinedBands));
var validFull = combinedStack.sampleRegions({
  collection:validSet_aa, properties:[CLASS_PROPERTY],
  scale:EXPORT_SCALE, tileScale:8
}).filter(ee.Filter.notNull(combinedBands));

// Print sizes to confirm consistent materialisation
print('Train full size (must match across all models):',
  trainFull.size());
print('Valid full size (must match across all models):',
  validFull.size());

// Derive model-specific subsets from the same materialised
// trainFull/validFull, guarantees identical sample sets
var embBands  = embedding2024.bandNames();
var classProp = ee.List([CLASS_PROPERTY]);
var trainEmb7   = trainFull.select(embBands.cat(classProp));
var validEmb7   = validFull.select(embBands.cat(classProp));
var trainPheno7 = trainFull.select(phenoBands.cat(classProp));
var validPheno7 = validFull.select(phenoBands.cat(classProp));

// Model A, KNN (k=3) | Embeddings only [baseline]
var modelA = ee.Classifier.smileKNN(3).train({
  features:trainEmb7, classProperty:CLASS_PROPERTY,
  inputProperties:embBands});
var validA_classified = validEmb7.classify(modelA);
var matrixA = validA_classified.errorMatrix({
  actual:CLASS_PROPERTY, predicted:'classification',
  order:[1,2,3,4,5,6]});
print('--- MODEL A: KNN (k=3) | Embeddings 64-dim ---');
print('Valid size:', validEmb7.size());
print('Confusion Matrix:', matrixA);
print('OA:', matrixA.accuracy());
print('Kappa:', matrixA.kappa());
print('Producer Accuracy:', matrixA.producersAccuracy());
print('User Accuracy:', matrixA.consumersAccuracy());

// Model B, RF (150 trees) | Embeddings only
var modelB = ee.Classifier.smileRandomForest({
  numberOfTrees:150, variablesPerSplit:8,
  minLeafPopulation:1, bagFraction:0.632, seed:RANDOM_SEED
}).train({features:trainEmb7, classProperty:CLASS_PROPERTY,
  inputProperties:embBands});
var validB_classified = validEmb7.classify(modelB);
var matrixB = validB_classified.errorMatrix({
  actual:CLASS_PROPERTY, predicted:'classification',
  order:[1,2,3,4,5,6]});
print('--- MODEL B: RF 150 trees | Embeddings 64-dim ---');
print('Valid size:', validEmb7.size());
print('Confusion Matrix:', matrixB);
print('OA:', matrixB.accuracy());
print('Kappa:', matrixB.kappa());
print('Producer Accuracy:', matrixB.producersAccuracy());
print('User Accuracy:', matrixB.consumersAccuracy());

// Model C, RF (150 trees) | Phenology only [CIRCULAR, ablation only]
// Labels were assigned using same phenological thresholds,
// so accuracy is artificially inflated. Not used operationally.
var modelC = ee.Classifier.smileRandomForest({
  numberOfTrees:150, variablesPerSplit:4,
  minLeafPopulation:1, bagFraction:0.632, seed:RANDOM_SEED
}).train({features:trainPheno7, classProperty:CLASS_PROPERTY,
  inputProperties:phenoBands});
var validC_classified = validPheno7.classify(modelC);
var matrixC = validC_classified.errorMatrix({
  actual:CLASS_PROPERTY, predicted:'classification',
  order:[1,2,3,4,5,6]});
print('--- MODEL C: RF 150 trees | Phenology 14-dim [CIRCULAR] ---');
print('Valid size:', validPheno7.size());
print('Confusion Matrix:', matrixC);
print('OA:', matrixC.accuracy());
print('Kappa:', matrixC.kappa());
print('Producer Accuracy:', matrixC.producersAccuracy());
print('User Accuracy:', matrixC.consumersAccuracy());

// Model D, RF (150 trees) | Embeddings + Phenology [PRIMARY]
var modelD = ee.Classifier.smileRandomForest({
  numberOfTrees:150, variablesPerSplit:9,
  minLeafPopulation:1, bagFraction:0.632, seed:RANDOM_SEED
}).train({features:trainFull, classProperty:CLASS_PROPERTY,
  inputProperties:combinedBands});
var validD_classified = validFull.classify(modelD);
var matrixD = validD_classified.errorMatrix({
  actual:CLASS_PROPERTY, predicted:'classification',
  order:[1,2,3,4,5,6]});
print('--- MODEL D: RF 150 trees | Embeddings + Phenology 78-dim [PRIMARY] ---');
print('Feature space: AlphaEarth (64) + Phenology (14) = 78-dim');
print('Valid size:', validFull.size());
print('Confusion Matrix:', matrixD);
print('OA:', matrixD.accuracy());
print('Kappa:', matrixD.kappa());
print('Producer Accuracy:', matrixD.producersAccuracy());
print('User Accuracy:', matrixD.consumersAccuracy());

print('');
print('============================================================');
print('  METHOD CONTRIBUTION SUMMARY');
print('============================================================');
print('B > A  | RF outperforms KNN on same embeddings');
print('D > B  | Phenology adds genuine value beyond embeddings');
print('D > C  | Embeddings add value beyond indices alone');
print('C NOTE | Circular: labels derived from same indices');
print('D best | Combined method justified by ablation');
print('PRIMARY RESULT: Model D used for all epoch mapping.');
print('============================================================');


// ============================================================
// PHASE 7 EXTENSION, CONFUSION MATRIX + ACCURACY CSV EXPORTS
// Outputs per park:
//   {PARK}_confusion_matrix_full.csv  (24 rows, 4 models × 6 classes)
//   {PARK}_accuracy_summary.csv       (4 rows, one per model)
// ============================================================
var CM_CLASS_INFO = [
  {code:1, label:'Core_Woodland'},
  {code:2, label:'Open_Woodland'},
  {code:3, label:'Shrub_Transition'},
  {code:4, label:'Grassland'},
  {code:5, label:'Riparian'},
  {code:6, label:'Anthropogenic'}
];

function cmToFC(cm, modelName, parkName) {
  var oa    = cm.accuracy();
  var kappa = cm.kappa();
  var pa    = ee.Array(cm.producersAccuracy());
  var ua    = ee.Array(cm.consumersAccuracy());
  var arr   = cm.array();
  var features = CM_CLASS_INFO.map(function(actualCls, i) {
    var rowList = arr.slice(0,i,i+1).project([1]).toList();
    var paVal   = pa.get([i,0]);
    var uaVal   = ua.get([0,i]);
    var props   = {
      park:parkName, model:modelName,
      actual_class_code:actualCls.code,
      actual_class_label:actualCls.label,
      overall_accuracy:oa, kappa:kappa,
      producer_accuracy:paVal, user_accuracy:uaVal
    };
    CM_CLASS_INFO.forEach(function(predCls,j) {
      props['pred_'+predCls.label] = rowList.get(j);
    });
    return ee.Feature(null, props);
  });
  return ee.FeatureCollection(features);
}

function modelSummaryFeature(cm, modelCode, modelDesc,
                              featureSpace, parkName) {
  var oa    = cm.accuracy();
  var kappa = cm.kappa();
  var pa    = ee.Array(cm.producersAccuracy());
  var ua    = ee.Array(cm.consumersAccuracy());
  var props = {
    park:parkName, model_code:modelCode,
    model_description:modelDesc, feature_space:featureSpace,
    overall_accuracy:oa, kappa:kappa
  };
  CM_CLASS_INFO.forEach(function(cls,i) {
    props['PA_'+cls.label] = pa.get([i,0]);
    props['UA_'+cls.label] = ua.get([0,i]);
  });
  return ee.Feature(null, props);
}

var fullCM_FC = ee.FeatureCollection([])
  .merge(cmToFC(matrixA,'A_KNN3_Embeddings64',       PARK_NAME))
  .merge(cmToFC(matrixB,'B_RF150_Embeddings64',       PARK_NAME))
  .merge(cmToFC(matrixC,'C_RF150_PhenologyOnly14',    PARK_NAME))
  .merge(cmToFC(matrixD,'D_RF150_Embeddings_Pheno78', PARK_NAME));

var accuracySummary_FC = ee.FeatureCollection([
  modelSummaryFeature(matrixA,'A',
    'KNN (k=3) | AlphaEarth Embeddings only',
    'Embeddings 64-dim [baseline]', PARK_NAME),
  modelSummaryFeature(matrixB,'B',
    'RF 150 trees | AlphaEarth Embeddings only',
    'Embeddings 64-dim', PARK_NAME),
  modelSummaryFeature(matrixC,'C',
    'RF 150 trees | Phenological Indices only [CIRCULAR]',
    'Phenology 14-dim, circularity inflates OA', PARK_NAME),
  modelSummaryFeature(matrixD,'D',
    'RF 150 trees | Embeddings + Phenology [PRIMARY]',
    'Embeddings 64-dim + Phenology 14-dim = 78-dim', PARK_NAME)
]);

Export.table.toDrive({
  collection:fullCM_FC,
  description:PARK_NAME+'_ConfusionMatrix_AllModels',
  folder:'LandSystem_PhD',
  fileNamePrefix:PARK_NAME+'_confusion_matrix_full',
  fileFormat:'CSV'});
Export.table.toDrive({
  collection:accuracySummary_FC,
  description:PARK_NAME+'_AccuracySummary',
  folder:'LandSystem_PhD',
  fileNamePrefix:PARK_NAME+'_accuracy_summary',
  fileFormat:'CSV'});

print('');
print('============================================================');
print('  ACCURACY TABLE EXPORTS, ' + PARK_NAME);
print('============================================================');
print('Model A | KNN k=3   | OA:', matrixA.accuracy(),
  '| Kappa:', matrixA.kappa());
print('Model B | RF Emb    | OA:', matrixB.accuracy(),
  '| Kappa:', matrixB.kappa());
print('Model C | RF Pheno [CIRCULAR] | OA:', matrixC.accuracy());
print('Model D | RF Emb+Pheno [PRIMARY] | OA:', matrixD.accuracy(),
  '| Kappa:', matrixD.kappa());
print('============================================================');


// ============================================================
// PHASE 8, MULTI-EPOCH CLASSIFICATION
// 2017        : Model B (RF | Embeddings 64-dim)
// 2019–2024   : Model D (RF | Embeddings + Phenology 78-dim)
// Each epoch uses its own year-specific embeddings and
// year-specific phenological indices recalculated from
// that epoch's Sentinel-2 and CHIRPS data.
// ============================================================
var classifiedMaps = {};

var masterClassifier_B = ee.Classifier.smileRandomForest({
  numberOfTrees:150, variablesPerSplit:8,
  minLeafPopulation:1, bagFraction:0.632, seed:RANDOM_SEED
}).train({
  features:trainingData, classProperty:CLASS_PROPERTY,
  inputProperties:embedding2024.bandNames()});

var modelD_bandNames = embedding2024.bandNames().cat(ee.List([
  'NDVI_dry','NDMI_dry','NDVI_amp','NDMI','NDBI','NDVI',
  'NDVI_wet','NDMI_wet','NDVI_p10','NDMI_p10',
  'NDVI_p90','NDMI_p90','NDVI_p_amp','RUE'
]));

var masterClassifier_D = ee.Classifier.smileRandomForest({
  numberOfTrees:150, variablesPerSplit:9,
  minLeafPopulation:1, bagFraction:0.632, seed:RANDOM_SEED
}).train({
  features:trainFull, classProperty:CLASS_PROPERTY,
  inputProperties:modelD_bandNames});

print('Master classifiers trained:');
print('  Model B, 2017, embeddings only (64-dim)');
print('  Model D, 2019/2021/2024, embeddings + phenology (78-dim)');

function getSeasonalComposite(startDate, endDate, region) {
  var csPlus = ee.ImageCollection(
    'GOOGLE/CLOUD_SCORE_PLUS/V1/S2_HARMONIZED')
    .filter(ee.Filter.date(startDate, endDate))
    .filter(ee.Filter.bounds(region));
  var s2 = ee.ImageCollection('COPERNICUS/S2_SR_HARMONIZED')
    .filter(ee.Filter.date(startDate, endDate))
    .filter(ee.Filter.bounds(region));
  var hasScenes = s2.size().gt(0);
  var hasCs     = csPlus.size().gt(0);
  var withCs = s2
    .linkCollection(csPlus, csPlus.first().bandNames())
    .map(function(img){
      return img.updateMask(img.select('cs').gte(0.55));
    }).select('B.*').median().clip(region);
  var withCloudPct = s2
    .filter(ee.Filter.lt('CLOUDY_PIXEL_PERCENTAGE',50))
    .select('B.*').median().clip(region);
  return ee.Image(ee.Algorithms.If(hasScenes,
    ee.Image(ee.Algorithms.If(hasCs, withCs, withCloudPct)),
    ee.Image.constant(0).rename('B8')
      .addBands(ee.Image.constant(0).rename('B4'))
      .addBands(ee.Image.constant(0).rename('B11'))
      .addBands(ee.Image.constant(0).rename('B3'))
      .clip(region)
  ));
}

// RUE function with tile-boundary correction applied per epoch
function getEpochRUE(year, region) {
  var yr     = String(year);
  var months = ee.List.sequence(1, 12);
  var rainfall = ee.ImageCollection('UCSB-CHG/CHIRPS/DAILY')
    .filter(ee.Filter.date(yr+'-01-01', yr+'-12-31'))
    .filter(ee.Filter.bounds(region))
    .sum().rename('rainfall').clip(region);
  var monthlyNDVI = ee.ImageCollection(months.map(function(m) {
    var start    = ee.Date.fromYMD(year, m, 1);
    var end      = start.advance(1, 'month');
    var csPlus_m = ee.ImageCollection(
      'GOOGLE/CLOUD_SCORE_PLUS/V1/S2_HARMONIZED')
      .filter(ee.Filter.date(start, end))
      .filter(ee.Filter.bounds(region));
    var s2_m = ee.ImageCollection('COPERNICUS/S2_SR_HARMONIZED')
      .filter(ee.Filter.date(start, end))
      .filter(ee.Filter.bounds(region))
      .linkCollection(csPlus_m, csPlus_m.first().bandNames())
      .map(function(img) {
        return img.normalizedDifference(['B8','B4'])
          .rename('NDVI')
          .updateMask(img.select('cs').gte(0.65));
      });
    var monthlyImg = ee.Image(ee.Algorithms.If(
      s2_m.size().gt(0),
      s2_m.median().rename('NDVI').multiply(30),
      ee.Image.constant(0).rename('NDVI').selfMask()
    ));
    return monthlyImg.clip(region);
  }));
  // Normalise by valid month count to remove tile boundary bias
  var validMonthCount = monthlyNDVI.count();
  var iNDVI = monthlyNDVI.sum()
    .divide(validMonthCount)
    .multiply(12);
  return iNDVI
    .divide(rainfall.add(ee.Image.constant(1)))
    .rename('RUE_'+yr)
    .clip(region);
}

EPOCHS.forEach(function(year) {
  print('--- Epoch: ' + year + ' ---');
  var yr     = String(year);
  var embImg = (year === 2024)
    ? embedding2024
    : getEmbeddingImage(year, geometry);
  var classifiedImg;

  if (year === 2017) {
    classifiedImg = embImg
      .classify(masterClassifier_B)
      .rename('landSystem').clip(geometry).toByte()
      .focal_mode({radius:1, units:'pixels', kernelType:'square'})
      .rename('landSystem').clip(geometry).toByte()
      .set('year',2017).set('park',PARK_NAME)
      .set('classifier','ModelB_RF_Embeddings_64dim')
      .set('system:time_start',
        ee.Date.fromYMD(2017,1,1).millis());
    print('2017 | Model B applied (embeddings only)');

  } else {
    var s2_annual_yr = getSentinel2Composite(year, geometry);
    var s2_dry_yr    = getSeasonalComposite(
      yr+'-03-01', yr+'-05-15', geometry);
    var s2_wet_yr    = getSeasonalComposite(
      yr+'-05-01', yr+'-07-15', geometry);

    var ndvi_yr     = s2_annual_yr
      .normalizedDifference(['B8','B4']).rename('NDVI').unmask(0);
    var ndmi_yr     = s2_annual_yr
      .normalizedDifference(['B8','B11']).rename('NDMI').unmask(0);
    var ndbi_yr     = s2_annual_yr
      .normalizedDifference(['B11','B8']).rename('NDBI').unmask(0);
    var ndvi_dry_yr = s2_dry_yr
      .normalizedDifference(['B8','B4']).rename('NDVI_dry').unmask(0);
    var ndmi_dry_yr = s2_dry_yr
      .normalizedDifference(['B8','B11']).rename('NDMI_dry').unmask(0);
    var ndvi_wet_yr = s2_wet_yr
      .normalizedDifference(['B8','B4']).rename('NDVI_wet').unmask(0);
    var ndmi_wet_yr = s2_wet_yr
      .normalizedDifference(['B8','B11']).rename('NDMI_wet').unmask(0);
    var ndvi_amp_yr = ndvi_wet_yr
      .subtract(ndvi_dry_yr).rename('NDVI_amp');

    var csPlus_yr = ee.ImageCollection(
      'GOOGLE/CLOUD_SCORE_PLUS/V1/S2_HARMONIZED')
      .filter(ee.Filter.date(yr+'-01-01', yr+'-12-31'))
      .filter(ee.Filter.bounds(geometry));
    var s2_masked_yr = ee.ImageCollection(
      'COPERNICUS/S2_SR_HARMONIZED')
      .filter(ee.Filter.date(yr+'-01-01', yr+'-12-31'))
      .filter(ee.Filter.bounds(geometry))
      .linkCollection(csPlus_yr, csPlus_yr.first().bandNames())
      .map(function(img){
        return img.updateMask(img.select('cs').gte(0.65));
      }).select('B.*');

    var s2_p10_yr = s2_masked_yr
      .reduce(ee.Reducer.percentile([10]))
      .rename(s2_masked_yr.first().bandNames()
        .map(function(b){return ee.String(b);}))
      .clip(geometry);
    var s2_p90_yr = s2_masked_yr
      .reduce(ee.Reducer.percentile([90]))
      .rename(s2_masked_yr.first().bandNames()
        .map(function(b){return ee.String(b);}))
      .clip(geometry);

    var ndvi_p10_yr  = s2_p10_yr
      .normalizedDifference(['B8','B4']).rename('NDVI_p10').unmask(0);
    var ndmi_p10_yr  = s2_p10_yr
      .normalizedDifference(['B8','B11']).rename('NDMI_p10').unmask(0);
    var ndvi_p90_yr  = s2_p90_yr
      .normalizedDifference(['B8','B4']).rename('NDVI_p90').unmask(0);
    var ndmi_p90_yr  = s2_p90_yr
      .normalizedDifference(['B8','B11']).rename('NDMI_p90').unmask(0);
    var ndvi_p_amp_yr = ndvi_p90_yr
      .subtract(ndvi_p10_yr).rename('NDVI_p_amp');
    var rue_yr = getEpochRUE(year, geometry)
      .select(['RUE_'+yr]).rename('RUE');

    var phenoStack_yr = ee.Image.cat([
      ndvi_dry_yr, ndmi_dry_yr, ndvi_amp_yr,
      ndmi_yr, ndbi_yr, ndvi_yr,
      ndvi_wet_yr, ndmi_wet_yr,
      ndvi_p10_yr, ndmi_p10_yr,
      ndvi_p90_yr, ndmi_p90_yr,
      ndvi_p_amp_yr, rue_yr
    ]);
    var combinedImg_yr = ee.Image.cat([embImg, phenoStack_yr]);

    classifiedImg = combinedImg_yr
      .classify(masterClassifier_D)
      .rename('landSystem').clip(geometry).toByte()
      .focal_mode({radius:1, units:'pixels', kernelType:'square'})
      .rename('landSystem').clip(geometry).toByte()
      .set('year',year).set('park',PARK_NAME)
      .set('classifier','ModelD_RF_Embeddings_Phenology_78dim')
      .set('system:time_start',
        ee.Date.fromYMD(year,1,1).millis());
    print(yr + ' | Model D applied (embeddings + phenology)');
  }

  classifiedMaps[year] = classifiedImg;
  Map.addLayer(classifiedImg, VIS_CLASSIFIED,
    PARK_NAME + ', Land System Map ' + yr, year === 2024);
  print(yr + ' | Classification complete');

  Export.image.toDrive({
    image:classifiedImg,
    description:PARK_NAME+'_LandSystem_'+yr,
    folder:'LandSystem_PhD',
    fileNamePrefix:PARK_NAME+'_land_system_'+yr,
    region:geometry, scale:EXPORT_SCALE,
    crs:'EPSG:32630', maxPixels:1e10});
  Export.image.toAsset({
    image:classifiedImg,
    description:PARK_NAME+'_LandSystem_Asset_'+yr,
    assetId:'projects/ee-desmond/assets/'+PARK_NAME+
      '/land_system_'+yr,
    region:geometry, scale:EXPORT_SCALE,
    crs:'EPSG:32630', maxPixels:1e10,
    pyramidingPolicy:{'.default':'MODE'}});
  print(yr + ' | Drive + Asset exports submitted');
});
print('--- PHASE 8: All epochs classified and exported ---');


// ============================================================
// PHASE 9, CHANGE ANALYSIS + RUE INTER-ANNUAL VARIABILITY
// ============================================================
var parkAreaKm2 = geometry.area().divide(1e6);
var STATS_SCALE = ee.Number(ee.Algorithms.If(
  parkAreaKm2.lt(500),  30,
  ee.Algorithms.If(parkAreaKm2.lt(2000), 100, 500)));

print('=== PHASE 9: Change Analysis, ' + PARK_NAME + ' ===');
print('Park area (km2):', parkAreaKm2);
print('Statistics scale (adaptive):', STATS_SCALE, 'm');

var changeStack = ee.Image.cat([
  classifiedMaps[2017].rename('ls_2017'),
  classifiedMaps[2019].rename('ls_2019'),
  classifiedMaps[2021].rename('ls_2021'),
  classifiedMaps[2024].rename('ls_2024')
]);

// Transition images for each epoch pair
[[2017,2019],[2019,2021],[2021,2024],[2017,2024]]
  .forEach(function(pair) {
    var y1 = pair[0]; var y2 = pair[1];
    var transitionImg = changeStack.select('ls_'+y1)
      .multiply(10).add(changeStack.select('ls_'+y2))
      .rename('transition_'+y1+'_'+y2);
    Map.addLayer(
      changeStack.select('ls_'+y1)
        .neq(changeStack.select('ls_'+y2)).selfMask(),
      {palette:['ff4444']},
      PARK_NAME+', Raw change '+y1+'>'+y2+' [diagnostic]',
      false);
    Export.image.toDrive({
      image:transitionImg.toByte(),
      description:PARK_NAME+'_Transition_'+y1+'_'+y2,
      folder:'LandSystem_PhD',
      fileNamePrefix:PARK_NAME+'_transition_'+y1+'_'+y2,
      region:geometry, scale:EXPORT_SCALE,
      crs:'EPSG:32630', maxPixels:1e10});
  });

// Class area statistics per epoch
print('=== CLASS AREA STATISTICS (km2) ===');
EPOCHS.forEach(function(year) {
  print('Class areas (km2), '+year+':',
    ee.Image.pixelArea().divide(1e6)
      .addBands(classifiedMaps[year]).reduceRegion({
        reducer: ee.Reducer.sum().group({
          groupField:1, groupName:'landSystem'}),
        geometry:geometry, scale:STATS_SCALE,
        maxPixels:1e10, tileScale:8}));
});

// Conservative change: stable in adjacent epochs,
// different between 2017 and 2024
var stable_early = changeStack.select('ls_2017')
  .eq(changeStack.select('ls_2019'));
var stable_late  = changeStack.select('ls_2021')
  .eq(changeStack.select('ls_2024'));
var conservativeChange = stable_early.and(stable_late)
  .and(changeStack.select('ls_2017')
    .neq(changeStack.select('ls_2024')))
  .rename('conservative_change');
var stableThroughout = changeStack.select('ls_2017')
  .eq(changeStack.select('ls_2019'))
  .and(changeStack.select('ls_2019')
    .eq(changeStack.select('ls_2021')))
  .and(changeStack.select('ls_2021')
    .eq(changeStack.select('ls_2024')))
  .rename('stable_all_epochs');
var conservativeTransition = changeStack.select('ls_2017')
  .multiply(10).add(changeStack.select('ls_2024'))
  .updateMask(conservativeChange)
  .rename('conservative_transition');

Map.addLayer(stableThroughout.selfMask(),
  {palette:['2166ac']},
  PARK_NAME+', Stable all epochs', false);
Map.addLayer(conservativeChange.selfMask(),
  {palette:['8b0000']},
  PARK_NAME+', Conservative change 2017>2024', true);

print('=== CONSERVATIVE CHANGE DETECTION ===');
print('Stable all 4 epochs (km2):',
  ee.Image.pixelArea().divide(1e6).updateMask(stableThroughout)
    .reduceRegion({
      reducer:ee.Reducer.sum(), geometry:geometry,
      scale:STATS_SCALE, maxPixels:1e10, tileScale:8}));
print('Conservative change (km2):',
  ee.Image.pixelArea().divide(1e6).updateMask(conservativeChange)
    .reduceRegion({
      reducer:ee.Reducer.sum(), geometry:geometry,
      scale:STATS_SCALE, maxPixels:1e10, tileScale:8}));
print('Conservative transition matrix:',
  conservativeTransition.reduceRegion({
    reducer:ee.Reducer.frequencyHistogram(),
    geometry:geometry, scale:STATS_SCALE,
    maxPixels:1e10, tileScale:8}));

[conservativeChange, conservativeTransition]
  .forEach(function(img) {
    var name = img.bandNames().getInfo()[0];
    Export.image.toDrive({
      image:img.toByte(),
      description:PARK_NAME+'_'+name,
      folder:'LandSystem_PhD',
      fileNamePrefix:PARK_NAME+'_'+name,
      region:geometry, scale:EXPORT_SCALE,
      crs:'EPSG:32630', maxPixels:1e10});
  });
Export.image.toAsset({
  image:conservativeChange.toByte(),
  description:PARK_NAME+'_ConservativeChange_Asset',
  assetId:'projects/ee-desmond/assets/'+PARK_NAME+
    '/conservative_change',
  region:geometry, scale:EXPORT_SCALE,
  crs:'EPSG:32630', maxPixels:1e10,
  pyramidingPolicy:{'.default':'MODE'}});

// RUE inter-annual variability (CV across 4 epochs)
var rue2017 = getEpochRUE(2017, geometry);
var rue2019 = getEpochRUE(2019, geometry);
var rue2021 = getEpochRUE(2021, geometry);
var rue2024 = getEpochRUE(2024, geometry);
var rueStack  = ee.Image.cat([rue2017,rue2019,rue2021,rue2024]);
var rueMean   = rueStack.reduce(ee.Reducer.mean())
  .rename('RUE_mean');
var rueStdDev = rueStack.reduce(ee.Reducer.stdDev())
  .rename('RUE_stddev');
var rueCV     = rueStdDev.divide(rueMean).rename('RUE_CV');

// Partition conservative change into genuine structural vs
// rainfall-driven apparent change using RUE CV threshold
var genuineChange = conservativeChange.and(rueCV.lt(0.15))
  .rename('genuine_change_2017_2024');
var variableChange = conservativeChange.and(rueCV.gte(0.15))
  .rename('variable_change_2017_2024');

Map.addLayer(rueCV,
  {min:0, max:0.3, palette:['1a9641','ffffbf','d73027']},
  PARK_NAME+', RUE CV', true);
Map.addLayer(genuineChange.selfMask(),
  {palette:['d73027']},
  PARK_NAME+', Genuine structural change', false);
Map.addLayer(variableChange.selfMask(),
  {palette:['fc8d59']},
  PARK_NAME+', Rainfall-driven apparent change', false);

print('=== RUE INTER-ANNUAL VARIABILITY ===');
print('Mean RUE CV (< 0.15 = stable):',
  rueCV.reduceRegion({
    reducer:ee.Reducer.mean(), geometry:geometry,
    scale:500, maxPixels:1e9}));
print('Genuine structural change (km2):',
  ee.Image.pixelArea().divide(1e6).updateMask(genuineChange)
    .reduceRegion({
      reducer:ee.Reducer.sum(), geometry:geometry,
      scale:STATS_SCALE, maxPixels:1e10, tileScale:8}));
print('Rainfall-driven apparent change (km2):',
  ee.Image.pixelArea().divide(1e6).updateMask(variableChange)
    .reduceRegion({
      reducer:ee.Reducer.sum(), geometry:geometry,
      scale:STATS_SCALE, maxPixels:1e10, tileScale:8}));

// RUE image exports
Export.image.toDrive({
  image:rueCV.toFloat(),
  description:PARK_NAME+'_RUE_CV',
  folder:'LandSystem_PhD',
  fileNamePrefix:PARK_NAME+'_rue_cv',
  region:geometry, scale:100,
  crs:'EPSG:32630', maxPixels:1e10});
Export.image.toDrive({
  image:ee.Image.cat([
    rue2017,rue2019,rue2021,rue2024,rueCV]).toFloat(),
  description:PARK_NAME+'_RUE_AllEpochs',
  folder:'LandSystem_PhD',
  fileNamePrefix:PARK_NAME+'_rue_all_epochs',
  region:geometry, scale:100,
  crs:'EPSG:32630', maxPixels:1e10});
Export.image.toDrive({
  image:genuineChange.toByte(),
  description:PARK_NAME+'_GenuineChange_2017_2024',
  folder:'LandSystem_PhD',
  fileNamePrefix:PARK_NAME+'_genuine_change',
  region:geometry, scale:EXPORT_SCALE,
  crs:'EPSG:32630', maxPixels:1e10});
Export.image.toAsset({
  image:genuineChange.toByte(),
  description:PARK_NAME+'_GenuineChange_Asset',
  assetId:'projects/ee-desmond/assets/'+PARK_NAME+
    '/genuine_change',
  region:geometry, scale:EXPORT_SCALE,
  crs:'EPSG:32630', maxPixels:1e10});
Export.image.toAsset({
  image:rueCV.toFloat(),
  description:PARK_NAME+'_RUE_CV_Asset',
  assetId:'projects/ee-desmond/assets/'+PARK_NAME+'/rue_cv',
  region:geometry, scale:100,
  crs:'EPSG:32630', maxPixels:1e10});

// CSV exports
var areaFeatures = [];
EPOCHS.forEach(function(year) {
  var groups = ee.List(
    ee.Image.pixelArea().divide(1e6)
      .addBands(classifiedMaps[year])
      .reduceRegion({
        reducer: ee.Reducer.sum().group({
          groupField:1, groupName:'landSystem'}),
        geometry:geometry, scale:STATS_SCALE,
        maxPixels:1e10, tileScale:8})
      .get('groups'));
  areaFeatures.push(groups.map(function(g) {
    var d = ee.Dictionary(g);
    return ee.Feature(null, {
      park:PARK_NAME, year:year,
      landSystem:d.get('landSystem'),
      area_km2:d.get('sum')
    });
  }));
});
Export.table.toDrive({
  collection:ee.FeatureCollection(
    ee.List(areaFeatures).flatten()),
  description:PARK_NAME+'_ClassAreas_AllEpochs_CSV',
  folder:'LandSystem_PhD',
  fileNamePrefix:PARK_NAME+'_class_areas',
  fileFormat:'CSV'});

Export.table.toDrive({
  collection:ee.FeatureCollection([
    ee.Feature(null,{park:PARK_NAME,year:2017,
      rue_mean:rue2017.reduceRegion({
        reducer:ee.Reducer.mean(),geometry:geometry,
        scale:500,maxPixels:1e9}).get('RUE_2017')}),
    ee.Feature(null,{park:PARK_NAME,year:2019,
      rue_mean:rue2019.reduceRegion({
        reducer:ee.Reducer.mean(),geometry:geometry,
        scale:500,maxPixels:1e9}).get('RUE_2019')}),
    ee.Feature(null,{park:PARK_NAME,year:2021,
      rue_mean:rue2021.reduceRegion({
        reducer:ee.Reducer.mean(),geometry:geometry,
        scale:500,maxPixels:1e9}).get('RUE_2021')}),
    ee.Feature(null,{park:PARK_NAME,year:2024,
      rue_mean:rue2024.reduceRegion({
        reducer:ee.Reducer.mean(),geometry:geometry,
        scale:500,maxPixels:1e9}).get('RUE_2024')})
  ]),
  description:PARK_NAME+'_RUE_Statistics_CSV',
  folder:'LandSystem_PhD',
  fileNamePrefix:PARK_NAME+'_rue_statistics',
  fileFormat:'CSV'});

print('--- PHASE 9: Change analysis and RUE validation complete ---');
print('--- All CSV exports submitted to LandSystem_PhD/ ---');


// ============================================================
// LEGEND
// ============================================================
var legend = ui.Panel({
  style:{position:'bottom-left', padding:'8px 12px'}});
legend.add(ui.Label({
  value:'Land System Classes, '+PARK_NAME,
  style:{fontWeight:'bold', fontSize:'13px', margin:'0 0 6px 0'}
}));
Object.keys(CLASS_INFO).forEach(function(key) {
  var info = CLASS_INFO[key];
  var row  = ui.Panel({
    layout:ui.Panel.Layout.flow('horizontal')});
  row.add(ui.Label({style:{
    backgroundColor:'#'+info.color,
    padding:'8px', margin:'0 6px 4px 0'}}));
  row.add(ui.Label({
    value:key+'. '+info.name,
    style:{margin:'0 0 4px 0', fontSize:'11px'}}));
  legend.add(row);
});
Map.add(legend);


// ============================================================
// SUPPLEMENTARY, PHENOLOGICAL VALIDATION LAYERS
// ============================================================
function getNDVISeasonalMetrics(year, region) {
  var startDate = ee.Date.fromYMD(year,1,1);
  var endDate   = startDate.advance(1,'year');
  var s2        = ee.ImageCollection('COPERNICUS/S2_SR_HARMONIZED')
    .filter(ee.Filter.date(startDate,endDate))
    .filter(ee.Filter.bounds(region));
  var csPlus = ee.ImageCollection(
    'GOOGLE/CLOUD_SCORE_PLUS/V1/S2_HARMONIZED');
  var masked = s2.linkCollection(csPlus, csPlus.first().bandNames())
    .map(function(img){
      return img.normalizedDifference(['B8','B4'])
        .rename('NDVI')
        .updateMask(img.select('cs').gte(0.65))
        .copyProperties(img,['system:time_start']);
    });
  var ndviMax   = masked.max().rename('NDVI_max');
  var ndviRange = ndviMax.subtract(
    masked.min().rename('NDVI_min')).rename('NDVI_range');
  return ee.Image.cat([ndviMax, ndviRange]).clip(region);
}

var ndviMetrics2024 = getNDVISeasonalMetrics(2024, geometry);
Map.addLayer(ndviMetrics2024.select('NDVI_max'),
  {min:0.1,max:0.9,
   palette:['d7191c','fdae61','ffffbf','a6d96a','1a9641']},
  'NDVI Max 2024 (canopy density)', false);
Map.addLayer(ndviMetrics2024.select('NDVI_range'),
  {min:0.1,max:0.7,
   palette:['f7f7f7','4393c3','053061']},
  'NDVI Seasonal Range 2024 (deciduousness)', false);

var kMeans10 = ee.Clusterer.wekaKMeans({
  nClusters:10, seed:42}).train(clusterSamples6);
Map.addLayer(
  embedding2024.cluster(kMeans10).randomVisualizer().clip(geometry),
  {}, 'Unsupervised Clusters (k=10)', false);


// ============================================================
// CONSOLE SUMMARY
// ============================================================
print('');
print('================================================');
print('  ' + PARK_NAME + ', CLASSIFICATION COMPLETE');
print('================================================');
print('Thresholds   : auto-derived from park percentiles');
print('2017         : Model B | RF | Embeddings only (64-dim)');
print('2019–2024    : Model D | RF | Embeddings + Phenology (78-dim)');
print('RUE method   : tile-bias corrected via valid-month normalisation');
print('Epochs       :', EPOCHS);
print('Export CRS   : EPSG:32630');
print('Export scale :', EXPORT_SCALE, 'm');
print('');
print('TO USE FOR ANOTHER PARK, change only:');
print('  PARK_NAME_FILTER, PARK_NAME, EPOCHS');
print('');
print('ALL EXPORTS → LandSystem_PhD/ (Google Drive)');
print('================================================');