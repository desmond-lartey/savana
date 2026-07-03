// ============================================================
// MODULE: masks
// Mutually exclusive land system masks.
// Priority order: Anthro → Riparian → Core → Grass → Shrub → Open
// Each mask explicitly excludes all higher-priority classes.
// ============================================================
 
// Compute all 6 land system masks from indices and thresholds.
// Returns {anthro, riparian, core, grass, shrub, open}
exports.compute = function(idx, T) {

  var mask_anthro = idx.ndbi.gt(T.ANTHRO_NDBI)
    .or(idx.ndvi.lt(T.ANTHRO_NDVI_MAX));

  var mask_riparian = idx.ndmi.gt(T.RIPARIAN_NDMI)
    .and(idx.ndmi_dry.gt(T.RIPARIAN_NDMI_DRY))
    .and(idx.ndvi_dry.gt(T.RIPARIAN_NDVI_DRY))
    .and(mask_anthro.not());

  var mask_core = idx.ndvi_dry.gt(T.CORE_NDVI_DRY)
    .and(idx.ndmi.gt(T.CORE_NDMI))
    .and(mask_anthro.not())
    .and(mask_riparian.not());

  var mask_grass = idx.ndvi_dry.lt(T.GRASS_NDVI_DRY_MAX)
    .and(idx.ndvi_amp.gt(T.GRASS_AMP_MIN)
      .or(idx.ndmi_dry.lt(T.GRASS_NDMI_DRY_MAX)))
    .and(mask_anthro.not())
    .and(mask_riparian.not())
    .and(mask_core.not());

  var mask_shrub = idx.ndvi_dry.gte(T.SHRUB_NDVI_DRY_MIN)
    .and(idx.ndvi_dry.lt(T.SHRUB_NDVI_DRY_MAX))
    .and(idx.ndmi_dry.gte(T.SHRUB_NDMI_DRY_MIN))
    .and(idx.ndmi_dry.lt(T.SHRUB_NDMI_DRY_MAX))
    .and(idx.ndvi_amp.gte(T.SHRUB_AMP_MIN))
    .and(idx.ndvi_amp.lt(T.SHRUB_AMP_MAX))
    .and(mask_anthro.not())
    .and(mask_riparian.not())
    .and(mask_core.not())
    .and(mask_grass.not());

  // Open woodland split into drier/moister sub-populations
  var mask_open_dry = idx.ndvi_dry.gte(T.OPEN_NDVI_DRY_MIN)
    .and(idx.ndvi_dry.lt(T.OPEN_NDVI_DRY_MID))
    .and(idx.ndmi.gte(T.OPEN_NDMI_MIN))
    .and(idx.ndmi.lte(T.OPEN_NDMI_SPLIT_HIGH))
    .and(mask_anthro.not()).and(mask_riparian.not())
    .and(mask_core.not()).and(mask_grass.not())
    .and(mask_shrub.not());

  var mask_open_moist = idx.ndvi_dry.gte(T.OPEN_NDVI_DRY_MID)
    .and(idx.ndvi_dry.lte(T.OPEN_NDVI_DRY_MAX))
    .and(idx.ndmi.gt(T.OPEN_NDMI_SPLIT_LOW))
    .and(idx.ndmi.lte(T.OPEN_NDMI_MAX))
    .and(mask_anthro.not()).and(mask_riparian.not())
    .and(mask_core.not()).and(mask_grass.not())
    .and(mask_shrub.not());

  return {
    anthro:   mask_anthro,
    riparian: mask_riparian,
    core:     mask_core,
    grass:    mask_grass,
    shrub:    mask_shrub,
    open:     mask_open_dry.or(mask_open_moist)
  };
};


// ── Visualisation helpers ────────────────────────────────────
exports.addLayers = function(masks) {
  Map.addLayer(masks.core.selfMask(),
    {palette:['1a6b1a']}, 'MASK: Core Woodland', false);
  Map.addLayer(masks.open.selfMask(),
    {palette:['74c476']}, 'MASK: Open Woodland', false);
  Map.addLayer(masks.shrub.selfMask(),
    {palette:['addd8e']}, 'MASK: Shrub-Transition', false);
  Map.addLayer(masks.grass.selfMask(),
    {palette:['ffff99']}, 'MASK: Grassland', false);
  Map.addLayer(masks.riparian.selfMask(),
    {palette:['4292c6']}, 'MASK: Riparian', false);
  Map.addLayer(masks.anthro.selfMask(),
    {palette:['d73027']}, 'MASK: Anthropogenic', false);
};

exports.printCoverage = function(masks, geometry) {
  var check = function(mask, name) {
    print(name + ' coverage:', mask.unmask(0).reduceRegion({
      reducer:  ee.Reducer.mean(),
      geometry: geometry,
      scale:    100,
      maxPixels:1e9,
      tileScale:8
    }));
  };
  print('=== MASK COVERAGE FRACTIONS (target 0.05-0.30) ===');
  check(masks.core,     'Core Woodland');
  check(masks.open,     'Open Woodland');
  check(masks.shrub,    'Shrub-Transition');
  check(masks.grass,    'Grassland');
  check(masks.riparian, 'Riparian');
  check(masks.anthro,   'Anthropogenic');
};