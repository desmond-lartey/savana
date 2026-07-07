// ============================================================
// MODULE: thresholds
// Adaptive percentile-based threshold derivation.
// All thresholds derived from this park's own index distribution.
// No hardcoded values — transfers to any park automatically.
// ============================================================

// Compute all classification thresholds from index percentiles.
// Returns a named object — access as T.CORE_NDVI_DRY etc.
exports.compute = function(idx, geometry) {
  var pctImage = ee.Image.cat([
    idx.ndvi, idx.ndmi, idx.ndbi,
    idx.ndvi_dry, idx.ndmi_dry,
    idx.ndvi_wet, idx.ndmi_wet,
    idx.ndvi_amp
  ]);
  var pctDict = pctImage.reduceRegion({
    reducer:   ee.Reducer.percentile([5,10,25,50,75,90,95]),
    geometry:  geometry,
    scale:     100,
    maxPixels: 1e9,
    tileScale: 8
  });

  // Shorthand extractor — returns ee.Number
  var p = function(band, pct) {
    return ee.Number(pctDict.get(band + '_p' + pct));
  };

  return {
    // Anthropogenic — high NDBI or very sparse vegetation
    ANTHRO_NDBI:     p('NDBI', 90),
    ANTHRO_NDVI_MAX: ee.Number(0.20),

    // Riparian — evergreen gallery forest, high NDMI both seasons
    RIPARIAN_NDMI:     p('NDMI', 95),
    RIPARIAN_NDMI_DRY: p('NDMI_dry',75).add(
      p('NDMI_dry',90).subtract(p('NDMI_dry',75)).multiply(0.5)),
    RIPARIAN_NDVI_DRY: p('NDVI_dry',50).add(
      p('NDVI_dry',75).subtract(p('NDVI_dry',50)).multiply(0.5)),

    // Core Woodland — dense closed canopy, top 25% dry-season NDVI
    CORE_NDVI_DRY: p('NDVI_dry', 75),
    CORE_NDMI:     p('NDMI',50).add(
      p('NDMI',75).subtract(p('NDMI',50)).multiply(0.5)),

    // Grassland — loses canopy in dry season, high amplitude
    GRASS_NDVI_DRY_MAX: p('NDVI_dry', 25),
    GRASS_AMP_MIN:      p('NDVI_amp',10).add(
      p('NDVI_amp',25).subtract(p('NDVI_amp',10)).multiply(0.75)),
    GRASS_NDMI_DRY_MAX: p('NDMI_dry',25).add(
      p('NDMI_dry',50).subtract(p('NDMI_dry',25)).multiply(0.75)),

    // Shrub-Transition — intermediate dry NDVI, low dry moisture
    SHRUB_NDVI_DRY_MIN: p('NDVI_dry', 10),
    SHRUB_NDVI_DRY_MAX: p('NDVI_dry', 50),
    SHRUB_NDMI_DRY_MIN: p('NDMI_dry', 25),
    SHRUB_NDMI_DRY_MAX: p('NDMI_dry',50).add(
      p('NDMI_dry',75).subtract(p('NDMI_dry',50)).multiply(0.20)),
    SHRUB_AMP_MIN:      p('NDVI_amp',10).add(
      p('NDVI_amp',25).subtract(p('NDVI_amp',10)).multiply(0.30)),
    SHRUB_AMP_MAX:      p('NDVI_amp', 90),

    // Open Woodland — intermediate canopy, sub-populations split
    OPEN_NDVI_DRY_MIN:    p('NDVI_dry', 25),
    OPEN_NDVI_DRY_MAX:    p('NDVI_dry', 75),
    OPEN_NDMI_MIN:        p('NDMI', 25),
    OPEN_NDMI_MAX:        p('NDMI', 75),
    OPEN_NDVI_DRY_MID:    p('NDVI_dry', 50),
    OPEN_NDMI_SPLIT_LOW:  p('NDMI', 50),
    OPEN_NDMI_SPLIT_HIGH: p('NDMI',50).add(
      p('NDMI',75).subtract(p('NDMI',50)).multiply(0.5))
  };
};