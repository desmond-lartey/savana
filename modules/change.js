// ============================================================
// MODULE: change
// Conservative change detection + RUE variability analysis
// ============================================================

var RUE_MOD = require('users/Desmond/landuse_studies:utils/rue');

exports.analyse = function(classifiedMaps, epochs, geometry, parkName) {
  var parkAreaKm2 = geometry.area().divide(1e6);
  var STATS_SCALE = ee.Number(ee.Algorithms.If(
    parkAreaKm2.lt(500),   30,
    ee.Algorithms.If(parkAreaKm2.lt(2000), 100, 500)));

  print('=== PHASE 9: Change Analysis, ' + parkName + ' ===');
  print('Park area (km2):', parkAreaKm2);
  print('Statistics scale:', STATS_SCALE, 'm');

  // Multi-band change stack
  var changeStack = ee.Image.cat([
    classifiedMaps[2017].rename('ls_2017'),
    classifiedMaps[2019].rename('ls_2019'),
    classifiedMaps[2021].rename('ls_2021'),
    classifiedMaps[2024].rename('ls_2024')
  ]);

  // Pairwise raw transition layers (diagnostic)
  [[2017,2019],[2019,2021],[2021,2024],[2017,2024]]
    .forEach(function(pair) {
      var y1 = pair[0]; var y2 = pair[1];
      Map.addLayer(
        changeStack.select('ls_'+y1)
          .neq(changeStack.select('ls_'+y2)).selfMask(),
        {palette:['ff4444']},
        parkName+' Raw change '+y1+'>'+y2, false);
    });

  // Class area statistics per epoch
  print('=== CLASS AREA STATISTICS (km2) ===');
  epochs.forEach(function(year) {
    print('Areas ' + year + ':',
      ee.Image.pixelArea().divide(1e6)
        .addBands(classifiedMaps[year])
        .reduceRegion({
          reducer:ee.Reducer.sum().group({
            groupField:1, groupName:'landSystem'}),
          geometry:geometry, scale:STATS_SCALE,
          maxPixels:1e10, tileScale:8
        }));
  });

  // Conservative change detection
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
    {palette:['2166ac']}, parkName+' Stable all epochs', false);
  Map.addLayer(conservativeChange.selfMask(),
    {palette:['8b0000']},
    parkName+' Conservative change 2017-2024', true);

  print('=== CONSERVATIVE CHANGE DETECTION ===');
  print('Stable all epochs (km2):',
    ee.Image.pixelArea().divide(1e6).updateMask(stableThroughout)
    .reduceRegion({reducer:ee.Reducer.sum(),
      geometry:geometry, scale:STATS_SCALE,
      maxPixels:1e10, tileScale:8}));
  print('Conservative change (km2):',
    ee.Image.pixelArea().divide(1e6).updateMask(conservativeChange)
    .reduceRegion({reducer:ee.Reducer.sum(),
      geometry:geometry, scale:STATS_SCALE,
      maxPixels:1e10, tileScale:8}));
  print('Transition matrix:',
    conservativeTransition.reduceRegion({
      reducer:ee.Reducer.frequencyHistogram(),
      geometry:geometry, scale:STATS_SCALE,
      maxPixels:1e10, tileScale:8}));
  print('Code: fromClass x10 + toClass | Stable=11,22,33,44,55,66');

  // RUE inter-annual variability
  var rue2017 = RUE_MOD.getEpochRUE(2017, geometry);
  var rue2019 = RUE_MOD.getEpochRUE(2019, geometry);
  var rue2021 = RUE_MOD.getEpochRUE(2021, geometry);
  var rue2024 = RUE_MOD.getEpochRUE(2024, geometry);
  var rueStack = ee.Image.cat([rue2017,rue2019,rue2021,rue2024]);
  var rueCV    = rueStack.reduce(ee.Reducer.stdDev())
    .divide(rueStack.reduce(ee.Reducer.mean()))
    .rename('RUE_CV');

  var genuineChange  = conservativeChange.and(rueCV.lt(0.15))
    .rename('genuine_change_2017_2024');
  var variableChange = conservativeChange.and(rueCV.gte(0.15))
    .rename('variable_change_2017_2024');

  Map.addLayer(rueCV,
    {min:0,max:0.3,palette:['1a9641','ffffbf','d73027']},
    parkName+' RUE CV', false);
  Map.addLayer(genuineChange.selfMask(),
    {palette:['d73027']}, parkName+' Genuine structural change', false);
  Map.addLayer(variableChange.selfMask(),
    {palette:['fc8d59']}, parkName+' Rainfall-driven change', false);

  print('=== RUE INTER-ANNUAL VARIABILITY ===');
  print('Mean RUE CV (< 0.15 = stable):',
    rueCV.reduceRegion({reducer:ee.Reducer.mean(),
      geometry:geometry, scale:500, maxPixels:1e9}));
  print('Genuine structural change (km2):',
    ee.Image.pixelArea().divide(1e6).updateMask(genuineChange)
    .reduceRegion({reducer:ee.Reducer.sum(),
      geometry:geometry, scale:STATS_SCALE,
      maxPixels:1e10, tileScale:8}));
  print('Rainfall-driven apparent change (km2):',
    ee.Image.pixelArea().divide(1e6).updateMask(variableChange)
    .reduceRegion({reducer:ee.Reducer.sum(),
      geometry:geometry, scale:STATS_SCALE,
      maxPixels:1e10, tileScale:8}));

  return {
    changeStack:             changeStack,
    conservativeChange:      conservativeChange,
    conservativeTransition:  conservativeTransition,
    stableThroughout:        stableThroughout,
    genuineChange:           genuineChange,
    variableChange:          variableChange,
    rueCV:                   rueCV,
    rue2017:rue2017, rue2019:rue2019,
    rue2021:rue2021, rue2024:rue2024,
    statsScale:              STATS_SCALE
  };
};