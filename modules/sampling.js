// ============================================================
// MODULE: sampling
// GCP generation: clustering, candidate sampling,
// label assignment, class balancing, embedding extraction
// ============================================================
 
var RANDOM_SEED    = 42;
var CONFIDENCE_MARGIN = 0.03;
var POINTS_PER_CLASS  = 30;
var CANDIDATES_PER_CLUSTER = 50;
var EXPORT_SCALE   = 10;
var CLASS_PROPERTY = 'landSystem';

// ── Unsupervised clustering in embedding space ───────────────
exports.clusterEmbedding = function(embedding, geometry) {
  var samples = embedding.sample({
    region:geometry, scale:30, numPixels:3000,
    seed:RANDOM_SEED, tileScale:8
  });
  var kmeans = ee.Clusterer.wekaKMeans({
    nClusters:6, seed:RANDOM_SEED
  }).train(samples);
  var clusters = embedding.cluster(kmeans).toInt().rename('cluster6');

  print('cluster6 band type (must be int):', clusters.bandTypes());
  Map.addLayer(clusters.randomVisualizer(),
    {}, 'Unsupervised Clusters (k=6)', false);

  // Cluster mean statistics
  var statImage = ee.Image.cat([
    ee.Image.cat(
      ee.List.sequence(0,7).map(function(i){
        return ee.Image(0).rename('placeholder');
      })
    ),
    clusters
  ]);
  return {clusters: clusters, samples: samples};
};

// ── Cluster-stratified candidate sampling ────────────────────
exports.sampleCandidates = function(idx, clusters, geometry) {
  var candidateImage = ee.Image.cat([
    idx.ndvi, idx.ndmi, idx.mndwi, idx.ndbi,
    idx.ndvi_dry, idx.ndmi_dry, idx.ndbi_dry,
    idx.ndvi_wet, idx.ndmi_wet, idx.ndvi_amp,
    clusters
  ]).clip(geometry);

  function sampleCluster(clusterId, seed) {
    return candidateImage
      .updateMask(clusters.eq(clusterId))
      .sample({
        region:geometry, scale:EXPORT_SCALE,
        numPixels:CANDIDATES_PER_CLUSTER * 10,
        seed:seed, geometries:true, tileScale:8
      })
      .filter(ee.Filter.notNull([
        'cluster6','NDVI','NDMI','NDBI',
        'NDVI_dry','NDMI_dry','NDVI_wet','NDMI_wet'
      ]))
      .randomColumn('pick', seed).sort('pick')
      .limit(CANDIDATES_PER_CLUSTER)
      .map(function(f) {
        return ee.Feature(f.geometry(), {
          cluster6: f.get('cluster6'),
          NDVI:     f.get('NDVI'),
          NDMI:     f.get('NDMI'),
          MNDWI:    f.get('MNDWI'),
          NDBI:     f.get('NDBI'),
          NDVI_dry: f.get('NDVI_dry'),
          NDMI_dry: f.get('NDMI_dry'),
          NDBI_dry: f.get('NDBI_dry'),
          NDVI_wet: f.get('NDVI_wet'),
          NDMI_wet: f.get('NDMI_wet'),
          NDVI_amp: f.get('NDVI_amp')
        });
      });
  }

  var candidates = ee.FeatureCollection([
    sampleCluster(0,100), sampleCluster(1,110),
    sampleCluster(2,120), sampleCluster(3,130),
    sampleCluster(4,140), sampleCluster(5,150)
  ]).flatten();

  print('Candidates (all clusters):', candidates.size());
  print('By cluster:', candidates.aggregate_histogram('cluster6'));
  return candidates;
};

// ── Label assignment with confidence filter ──────────────────
exports.assignLabels = function(candidates, T) {
  var labelled = candidates.map(function(f) {
    var ndviV   = ee.Number(f.get('NDVI'));
    var ndmiV   = ee.Number(f.get('NDMI'));
    var ndbiV   = ee.Number(f.get('NDBI'));
    var ndviDry = ee.Number(f.get('NDVI_dry'));
    var ndmiDry = ee.Number(f.get('NDMI_dry'));
    var ndviAmp = ee.Number(
      ee.Algorithms.If(f.get('NDVI_amp'), f.get('NDVI_amp'), 0));

    var isAmbiguous =
      ndviDry.gt(T.CORE_NDVI_DRY.subtract(CONFIDENCE_MARGIN))
        .and(ndviDry.lt(T.CORE_NDVI_DRY.add(CONFIDENCE_MARGIN)))
      .or(ndviDry.gt(T.GRASS_NDVI_DRY_MAX.subtract(CONFIDENCE_MARGIN))
        .and(ndviDry.lt(T.GRASS_NDVI_DRY_MAX.add(CONFIDENCE_MARGIN))))
      .or(ndviDry.gt(T.OPEN_NDVI_DRY_MIN.subtract(CONFIDENCE_MARGIN))
        .and(ndviDry.lt(T.OPEN_NDVI_DRY_MIN.add(CONFIDENCE_MARGIN))));

    var label = ee.Number(ee.Algorithms.If(
      ndbiV.gt(T.ANTHRO_NDBI).or(ndviV.lt(T.ANTHRO_NDVI_MAX)), 6,
      ee.Algorithms.If(
        ndmiV.gt(T.RIPARIAN_NDMI)
          .and(ndmiDry.gt(T.RIPARIAN_NDMI_DRY))
          .and(ndviDry.gt(T.RIPARIAN_NDVI_DRY)), 5,
        ee.Algorithms.If(
          ndviDry.gt(T.CORE_NDVI_DRY)
            .and(ndmiV.gt(T.CORE_NDMI)), 1,
          ee.Algorithms.If(
            ndviDry.lt(T.GRASS_NDVI_DRY_MAX).and(
              ndviAmp.gt(T.GRASS_AMP_MIN)
                .or(ndmiDry.lt(T.GRASS_NDMI_DRY_MAX))), 4,
            ee.Algorithms.If(
              ndviDry.gte(T.SHRUB_NDVI_DRY_MIN)
                .and(ndviDry.lt(T.SHRUB_NDVI_DRY_MAX))
                .and(ndmiDry.gte(T.SHRUB_NDMI_DRY_MIN))
                .and(ndmiDry.lt(T.SHRUB_NDMI_DRY_MAX))
                .and(ndviAmp.gte(T.SHRUB_AMP_MIN))
                .and(ndviAmp.lt(T.SHRUB_AMP_MAX)), 3,
              ee.Algorithms.If(
                ndviDry.gte(T.OPEN_NDVI_DRY_MIN)
                  .and(ndviDry.lte(T.OPEN_NDVI_DRY_MAX))
                  .and(ndmiV.gte(T.OPEN_NDMI_MIN))
                  .and(ndmiV.lte(T.OPEN_NDMI_MAX)), 2, -1
              )
            )
          )
        )
      )
    ));

    var isRare     = label.eq(3).or(label.eq(5));
    var finalLabel = ee.Number(ee.Algorithms.If(isRare, label,
      ee.Algorithms.If(isAmbiguous, 99, label)));
    return f.set(CLASS_PROPERTY, finalLabel);
  });

  var valid = labelled
    .filter(ee.Filter.gt(CLASS_PROPERTY, 0))
    .filter(ee.Filter.neq(CLASS_PROPERTY, 99));

  print('=== LABEL RESULTS ===');
  print('Valid after filtering:', valid.size());
  print('Class distribution:', valid.aggregate_histogram(CLASS_PROPERTY));
  return valid;
};

// ── Class balancing + embedding extraction ───────────────────
exports.buildGCPs = function(embedding, idx, clusters, T, geometry) {
  var candidates = exports.sampleCandidates(idx, clusters, geometry);
  var labelled   = exports.assignLabels(candidates, T);

  function take(fc, classVal, seed) {
    var sub = fc.filter(ee.Filter.eq(CLASS_PROPERTY, classVal));
    return ee.FeatureCollection(ee.Algorithms.If(
      sub.size().gte(POINTS_PER_CLASS),
      sub.randomColumn('pick',seed).sort('pick').limit(POINTS_PER_CLASS),
      sub
    ));
  }

  var balanced =
    take(labelled,1,101).merge(take(labelled,2,102))
    .merge(take(labelled,3,103)).merge(take(labelled,4,104))
    .merge(take(labelled,5,105)).merge(take(labelled,6,106));

  print('--- Point counts per class ---');
  print('Core Woodland:',
    balanced.filter(ee.Filter.eq(CLASS_PROPERTY,1)).size());
  print('Open Woodland:',
    balanced.filter(ee.Filter.eq(CLASS_PROPERTY,2)).size());
  print('Shrub-Transition:',
    balanced.filter(ee.Filter.eq(CLASS_PROPERTY,3)).size());
  print('Grassland:',
    balanced.filter(ee.Filter.eq(CLASS_PROPERTY,4)).size());
  print('Riparian:',
    balanced.filter(ee.Filter.eq(CLASS_PROPERTY,5)).size());
  print('Anthropogenic:',
    balanced.filter(ee.Filter.eq(CLASS_PROPERTY,6)).size());

  var gcps = embedding.sampleRegions({
    collection:  balanced.filterBounds(geometry),
    properties:  [CLASS_PROPERTY,'cluster6',
      'NDVI','NDMI','NDBI',
      'NDVI_dry','NDMI_dry','NDVI_wet','NDMI_wet','NDVI_amp'],
    scale:       EXPORT_SCALE,
    geometries:  true,
    tileScale:   8
  }).filter(ee.Filter.notNull(embedding.bandNames()));

  print('--- PHASE 4 COMPLETE ---');
  print('Total GCPs:', gcps.size());
  print('Final class distribution:',
    gcps.aggregate_histogram(CLASS_PROPERTY));

  // GCP visualisation
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

  return gcps;
};