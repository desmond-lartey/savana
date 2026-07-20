// ============================================================
// MODULE: indices
// Spectral index computation and phenological stack builder
// ============================================================

// Compute all spectral indices from seasonal composites.
// Returns a named object, access as idx.ndvi, idx.ndvi_dry etc.
exports.compute = function(s2Annual, s2Dry, s2Wet, p10, p90) {
  var ndvi     = s2Annual.normalizedDifference(['B8','B4']).rename('NDVI');
  var ndmi     = s2Annual.normalizedDifference(['B8','B11']).rename('NDMI');
  var mndwi    = s2Annual.normalizedDifference(['B3','B11']).rename('MNDWI');
  var ndbi     = s2Annual.normalizedDifference(['B11','B8']).rename('NDBI');
  var ndvi_dry = s2Dry.normalizedDifference(['B8','B4']).rename('NDVI_dry');
  var ndmi_dry = s2Dry.normalizedDifference(['B8','B11']).rename('NDMI_dry');
  var ndbi_dry = s2Dry.normalizedDifference(['B11','B8']).rename('NDBI_dry');
  var ndvi_wet = s2Wet.normalizedDifference(['B8','B4']).rename('NDVI_wet');
  var ndmi_wet = s2Wet.normalizedDifference(['B8','B11']).rename('NDMI_wet');
  var ndvi_amp = ndvi_wet.subtract(ndvi_dry).rename('NDVI_amp');
  var ndvi_p10 = p10.normalizedDifference(['B8','B4']).rename('NDVI_p10');
  var ndmi_p10 = p10.normalizedDifference(['B8','B11']).rename('NDMI_p10');
  var ndvi_p90 = p90.normalizedDifference(['B8','B4']).rename('NDVI_p90');
  var ndmi_p90 = p90.normalizedDifference(['B8','B11']).rename('NDMI_p90');
  var ndvi_p_amp = ndvi_p90.subtract(ndvi_p10).rename('NDVI_p_amp');
  return {
    ndvi: ndvi, ndmi: ndmi, mndwi: mndwi, ndbi: ndbi,
    ndvi_dry: ndvi_dry, ndmi_dry: ndmi_dry, ndbi_dry: ndbi_dry,
    ndvi_wet: ndvi_wet, ndmi_wet: ndmi_wet, ndvi_amp: ndvi_amp,
    ndvi_p10: ndvi_p10, ndmi_p10: ndmi_p10,
    ndvi_p90: ndvi_p90, ndmi_p90: ndmi_p90,
    ndvi_p_amp: ndvi_p_amp
  };
};

// Build the 14-band phenological stack used in Model D training.
// Band order must match masterClassifier_D inputProperties exactly.
exports.buildPhenoStack = function(idx, rue) {
  return ee.Image.cat([
    idx.ndvi_dry,   // 1
    idx.ndmi_dry,   // 2
    idx.ndvi_amp,   // 3
    idx.ndmi,       // 4
    idx.ndbi,       // 5
    idx.ndvi,       // 6
    idx.ndvi_wet,   // 7
    idx.ndmi_wet,   // 8
    idx.ndvi_p10,   // 9
    idx.ndmi_p10,   // 10
    idx.ndvi_p90,   // 11
    idx.ndmi_p90,   // 12
    idx.ndvi_p_amp, // 13
    rue             // 14, RUE (must be named 'RUE')
  ]);
};