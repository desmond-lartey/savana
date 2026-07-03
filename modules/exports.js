// ============================================================
// MODULE: exports
// All Drive, Asset, CSV and legend exports
// ============================================================
 
var EXPORT_SCALE = 10;
var FOLDER       = 'LandSystem_PhD';

// ── Classified map exports (Drive + Asset) per epoch ────────
exports.classifiedMaps = function(maps, epochs, geometry, parkName) {
  epochs.forEach(function(year) {
    var img = maps[year];
    Export.image.toDrive({
      image:          img,
      description:    parkName + '_LandSystem_' + year,
      folder:         FOLDER,
      fileNamePrefix: parkName + '_land_system_' + year,
      region:geometry, scale:EXPORT_SCALE,
      crs:'EPSG:32630', maxPixels:1e10
    });
    Export.image.toAsset({
      image:           img,
      description:     parkName + '_LandSystem_Asset_' + year,
      assetId: 'projects/ee-desmond/assets/' +
               parkName + '/land_system_' + year,
      region:geometry, scale:EXPORT_SCALE,
      crs:'EPSG:32630', maxPixels:1e10,
      pyramidingPolicy:{'.default':'MODE'}
    });
    print(year + ' | Drive + Asset exports submitted');
  });
};

// ── Change product exports ───────────────────────────────────
exports.changeProducts = function(chg, geometry, parkName) {
  // Pairwise transition images
  [[2017,2019],[2019,2021],[2021,2024],[2017,2024]]
    .forEach(function(pair) {
      var y1 = pair[0]; var y2 = pair[1];
      var transImg = chg.changeStack.select('ls_'+y1).multiply(10)
        .add(chg.changeStack.select('ls_'+y2))
        .rename('transition_'+y1+'_'+y2);
      Export.image.toDrive({
        image:transImg.toByte(),
        description:    parkName+'_Transition_'+y1+'_'+y2,
        folder:         FOLDER,
        fileNamePrefix: parkName+'_transition_'+y1+'_'+y2,
        region:geometry, scale:EXPORT_SCALE,
        crs:'EPSG:32630', maxPixels:1e10
      });
    });

  // Conservative change
  Export.image.toDrive({
    image:chg.conservativeChange.toByte(),
    description:    parkName+'_ConservativeChange',
    folder:         FOLDER,
    fileNamePrefix: parkName+'_conservative_change',
    region:geometry, scale:EXPORT_SCALE,
    crs:'EPSG:32630', maxPixels:1e10
  });
  Export.image.toDrive({
    image:chg.conservativeTransition.toByte(),
    description:    parkName+'_ConservativeTransition',
    folder:         FOLDER,
    fileNamePrefix: parkName+'_conservative_transition',
    region:geometry, scale:EXPORT_SCALE,
    crs:'EPSG:32630', maxPixels:1e10
  });
  Export.image.toAsset({
    image:chg.conservativeChange.toByte(),
    description:    parkName+'_ConservativeChange_Asset',
    assetId: 'projects/ee-desmond/assets/'+parkName+'/conservative_change',
    region:geometry, scale:EXPORT_SCALE,
    crs:'EPSG:32630', maxPixels:1e10,
    pyramidingPolicy:{'.default':'MODE'}
  });

  // Genuine change
  Export.image.toDrive({
    image:chg.genuineChange.toByte(),
    description:    parkName+'_GenuineChange',
    folder:         FOLDER,
    fileNamePrefix: parkName+'_genuine_change',
    region:geometry, scale:EXPORT_SCALE,
    crs:'EPSG:32630', maxPixels:1e10
  });
  Export.image.toAsset({
    image:chg.genuineChange.toByte(),
    description:    parkName+'_GenuineChange_Asset',
    assetId: 'projects/ee-desmond/assets/'+parkName+'/genuine_change',
    region:geometry, scale:EXPORT_SCALE,
    crs:'EPSG:32630', maxPixels:1e10
  });

  // RUE images
  Export.image.toDrive({
    image:chg.rueCV.toFloat(),
    description:    parkName+'_RUE_CV',
    folder:         FOLDER,
    fileNamePrefix: parkName+'_rue_cv',
    region:geometry, scale:100,
    crs:'EPSG:32630', maxPixels:1e10
  });
  Export.image.toDrive({
    image: ee.Image.cat([
      chg.rue2017,chg.rue2019,
      chg.rue2021,chg.rue2024,chg.rueCV]).toFloat(),
    description:    parkName+'_RUE_AllEpochs',
    folder:         FOLDER,
    fileNamePrefix: parkName+'_rue_all_epochs',
    region:geometry, scale:100,
    crs:'EPSG:32630', maxPixels:1e10
  });
  Export.image.toAsset({
    image:chg.rueCV.toFloat(),
    description:    parkName+'_RUE_CV_Asset',
    assetId: 'projects/ee-desmond/assets/'+parkName+'/rue_cv',
    region:geometry, scale:100,
    crs:'EPSG:32630', maxPixels:1e10
  });

  print('Change product exports submitted.');
};

// ── CSV table exports ────────────────────────────────────────
exports.csvTables = function(maps, chg, epochs, geometry, parkName) {
  var STATS_SCALE = chg.statsScale;

  // Class areas per epoch
  var areaFeatures = [];
  epochs.forEach(function(year) {
    var groups = ee.List(
      ee.Image.pixelArea().divide(1e6)
        .addBands(maps[year])
        .reduceRegion({
          reducer:ee.Reducer.sum().group({
            groupField:1, groupName:'landSystem'}),
          geometry:geometry, scale:STATS_SCALE,
          maxPixels:1e10, tileScale:8
        }).get('groups'));
    areaFeatures.push(groups.map(function(g) {
      var d = ee.Dictionary(g);
      return ee.Feature(null, {
        park:parkName, year:year,
        landSystem:d.get('landSystem'),
        area_km2:d.get('sum')
      });
    }));
  });
  Export.table.toDrive({
    collection:     ee.FeatureCollection(
      ee.List(areaFeatures).flatten()),
    description:    parkName+'_ClassAreas_AllEpochs',
    folder:         FOLDER,
    fileNamePrefix: parkName+'_class_areas',
    fileFormat:     'CSV'
  });

  // RUE statistics per epoch
  Export.table.toDrive({
    collection: ee.FeatureCollection([
      ee.Feature(null,{park:parkName,year:2017,
        rue_mean:chg.rue2017.reduceRegion({
          reducer:ee.Reducer.mean(),
          geometry:geometry,scale:500,maxPixels:1e9})
          .get('RUE_2017')}),
      ee.Feature(null,{park:parkName,year:2019,
        rue_mean:chg.rue2019.reduceRegion({
          reducer:ee.Reducer.mean(),
          geometry:geometry,scale:500,maxPixels:1e9})
          .get('RUE_2019')}),
      ee.Feature(null,{park:parkName,year:2021,
        rue_mean:chg.rue2021.reduceRegion({
          reducer:ee.Reducer.mean(),
          geometry:geometry,scale:500,maxPixels:1e9})
          .get('RUE_2021')}),
      ee.Feature(null,{park:parkName,year:2024,
        rue_mean:chg.rue2024.reduceRegion({
          reducer:ee.Reducer.mean(),
          geometry:geometry,scale:500,maxPixels:1e9})
          .get('RUE_2024')})
    ]),
    description:    parkName+'_RUE_Statistics',
    folder:         FOLDER,
    fileNamePrefix: parkName+'_rue_statistics',
    fileFormat:     'CSV'
  });

  print('CSV exports submitted.');
};

// ── Map legend ───────────────────────────────────────────────
exports.addLegend = function(parkName) {
  var CLASS_INFO = {
    1:{name:'Core Woodland',                color:'1a6b1a'},
    2:{name:'Open Woodland / Tree Savanna', color:'74c476'},
    3:{name:'Shrub-Transition Savanna',     color:'c7e9c0'},
    4:{name:'Grassland Systems',            color:'ffff99'},
    5:{name:'Riparian / Wetland Vegetation',color:'4292c6'},
    6:{name:'Anthropogenic Disturbance',    color:'d73027'}
  };
  var legend = ui.Panel({
    style:{position:'bottom-left',padding:'8px 12px'}});
  legend.add(ui.Label({
    value:'Land System Classes - '+parkName,
    style:{fontWeight:'bold',fontSize:'13px',
      margin:'0 0 6px 0'}}));
  Object.keys(CLASS_INFO).forEach(function(key) {
    var info = CLASS_INFO[key];
    var row  = ui.Panel(
      {layout:ui.Panel.Layout.flow('horizontal')});
    row.add(ui.Label({style:{
      backgroundColor:'#'+info.color,
      padding:'8px',margin:'0 6px 4px 0'}}));
    row.add(ui.Label({
      value:key+'. '+info.name,
      style:{margin:'0 0 4px 0',fontSize:'11px'}}));
    legend.add(row);
  });
  Map.add(legend);
};