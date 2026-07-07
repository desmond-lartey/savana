// ============================================================
// MODULE: rue
// Rain Use Efficiency — annual and per-epoch computation
// ============================================================

var S2_COLLECTION  = 'COPERNICUS/S2_SR_HARMONIZED';
var CS_COLLECTION  = 'GOOGLE/CLOUD_SCORE_PLUS/V1/S2_HARMONIZED';
var CHIRPS         = 'UCSB-CHG/CHIRPS/DAILY';

// RUE for a specific epoch year.
// Returns single-band image named 'RUE_{year}'.
// Multiply by 1000 gives interpretable units
exports.getEpochRUE = function(year, region) {
  var yr       = String(year);
  var rainfall = ee.ImageCollection(CHIRPS)
    .filter(ee.Filter.date(yr+'-01-01', yr+'-12-31'))
    .filter(ee.Filter.bounds(region))
    .sum().rename('rainfall').clip(region);
  var csPlus   = ee.ImageCollection(CS_COLLECTION)
    .filter(ee.Filter.date(yr+'-01-01', yr+'-12-31'))
    .filter(ee.Filter.bounds(region));
  var s2       = ee.ImageCollection(S2_COLLECTION)
    .filter(ee.Filter.date(yr+'-01-01', yr+'-12-31'))
    .filter(ee.Filter.bounds(region));
  var annualNDVI = ee.Image(ee.Algorithms.If(
    s2.size().gt(0),
    s2.linkCollection(csPlus, csPlus.first().bandNames())
      .map(function(img) {
        return img.normalizedDifference(['B8','B4']).rename('NDVI')
          .updateMask(img.select('cs').gte(0.65));
      }).mean().rename('NDVI').clip(region),
    ee.Image.constant(0).rename('NDVI').clip(region)
  ));
  return annualNDVI.multiply(1000)
    .divide(rainfall.add(ee.Image.constant(1)))
    .rename('RUE_' + yr).clip(region);
};

// Full integrated NDVI / CHIRPS RUE for training year (2024).
// Returns {chirps, iNDVI, rue} — rue is named 'RUE'.
exports.computeAnnual2024 = function(geometry) {
  var chirps = ee.ImageCollection(CHIRPS)
    .filter(ee.Filter.date('2024-01-01','2024-12-31'))
    .filter(ee.Filter.bounds(geometry))
    .sum().clip(geometry).rename('annual_rainfall_mm');
  var months = ee.List.sequence(1, 12);
  var monthlyNDVI = ee.ImageCollection(months.map(function(m) {
    var start    = ee.Date.fromYMD(2024, m, 1);
    var end      = start.advance(1, 'month');
    var csPlus_m = ee.ImageCollection(CS_COLLECTION)
      .filter(ee.Filter.date(start, end))
      .filter(ee.Filter.bounds(geometry));
    var s2_m = ee.ImageCollection(S2_COLLECTION)
      .filter(ee.Filter.date(start, end))
      .filter(ee.Filter.bounds(geometry))
      .linkCollection(csPlus_m, csPlus_m.first().bandNames())
      .map(function(img) {
        return img.updateMask(img.select('cs').gte(0.65));
      });
    return ee.Image(ee.Algorithms.If(
      s2_m.size().gt(0),
      s2_m.select(['B8','B4']).median()
        .normalizedDifference().rename('NDVI').multiply(30),
      ee.Image.constant(0).rename('NDVI')
    )).clip(geometry);
  }));
  var iNDVI = monthlyNDVI.sum().rename('iNDVI');
  var rue   = iNDVI.divide(chirps.add(ee.Image.constant(1)))
    .rename('RUE').clip(geometry);
  return {chirps: chirps, iNDVI: iNDVI, rue: rue};
};