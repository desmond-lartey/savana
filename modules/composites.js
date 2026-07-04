// ============================================================
// MODULE: composites
// Sentinel-2 and AlphaEarth embedding image builders
// ============================================================
 
var S2_COLLECTION  = 'COPERNICUS/S2_SR_HARMONIZED';
var CS_COLLECTION  = 'GOOGLE/CLOUD_SCORE_PLUS/V1/S2_HARMONIZED';
var EMB_COLLECTION = 'GOOGLE/SATELLITE_EMBEDDING/V1/ANNUAL';

// Annual cloud-free Sentinel-2 median composite
exports.getSentinel2Annual = function(year, region) {
  var start  = ee.Date.fromYMD(year, 1, 1);
  var end    = start.advance(1, 'year');
  var s2     = ee.ImageCollection(S2_COLLECTION)
    .filter(ee.Filter.date(start, end))
    .filter(ee.Filter.bounds(region));
  var csPlus = ee.ImageCollection(CS_COLLECTION);
  return s2.linkCollection(csPlus, csPlus.first().bandNames())
    .map(function(img) {
      return img.updateMask(img.select('cs').gte(0.65));
    }).select('B.*').median().clip(region);
};

// Seasonal composite with cloud-score + fallback
exports.getSeasonalComposite = function(startDate, endDate, region) {
  var csPlus = ee.ImageCollection(CS_COLLECTION)
    .filter(ee.Filter.date(startDate, endDate))
    .filter(ee.Filter.bounds(region));
  var s2 = ee.ImageCollection(S2_COLLECTION)
    .filter(ee.Filter.date(startDate, endDate))
    .filter(ee.Filter.bounds(region));
  var withCs = s2.linkCollection(csPlus, csPlus.first().bandNames())
    .map(function(img) {
      return img.updateMask(img.select('cs').gte(0.55));
    }).select('B.*').median().clip(region);
  var withCloudPct = s2
    .filter(ee.Filter.lt('CLOUDY_PIXEL_PERCENTAGE', 50))
    .select('B.*').median().clip(region);
  var fallback = ee.Image.constant(0).rename('B8')
    .addBands(ee.Image.constant(0).rename('B4'))
    .addBands(ee.Image.constant(0).rename('B11'))
    .addBands(ee.Image.constant(0).rename('B3'))
    .clip(region);
  return ee.Image(ee.Algorithms.If(
    s2.size().gt(0),
    ee.Image(ee.Algorithms.If(csPlus.size().gt(0), withCs, withCloudPct)),
    fallback
  ));
};

// AlphaEarth 64-dimensional satellite embedding
exports.getEmbeddingImage = function(year, region) {
  var start = ee.Date.fromYMD(year, 1, 1);
  var end   = start.advance(1, 'year');
  return ee.ImageCollection(EMB_COLLECTION)
    .filter(ee.Filter.date(start, end))
    .filter(ee.Filter.bounds(region))
    .mosaic().clip(region);
};

// Annual p10 and p90 percentile composites for phenological indices
exports.getPercentileComposites = function(year, region) {
  var yr     = String(year);
  var csPlus = ee.ImageCollection(CS_COLLECTION)
    .filter(ee.Filter.date(yr+'-01-01', yr+'-12-31'))
    .filter(ee.Filter.bounds(region));
  var masked = ee.ImageCollection(S2_COLLECTION)
    .filter(ee.Filter.date(yr+'-01-01', yr+'-12-31'))
    .filter(ee.Filter.bounds(region))
    .linkCollection(csPlus, csPlus.first().bandNames())
    .map(function(img) {
      return img.updateMask(img.select('cs').gte(0.65));
    }).select('B.*');
  var rename = function(img) {
    return img.rename(
      masked.first().bandNames()
        .map(function(b) { return ee.String(b); })
    ).clip(region);
  };
  return {
    p10: rename(masked.reduce(ee.Reducer.percentile([10]))),
    p90: rename(masked.reduce(ee.Reducer.percentile([90])))
  };
};