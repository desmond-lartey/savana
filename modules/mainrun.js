// ============================================================
// MAIN — Land System Classification
// Change only the 3 lines below when switching parks
// ============================================================

var PARK_NAME_FILTER = 'Old Oyo';
var PARK_NAME        = 'Old Oyo';
var EPOCHS           = [2017, 2019, 2021, 2024];

// ── Load modules ─────────────────────────────────────────────
var C   = require('users/Desmond/landuse_studies:utils/composites');
var IDX = require('users/Desmond/landuse_studies:utils/indices');
var RUE = require('users/Desmond/landuse_studies:utils/rue');
var THR = require('users/Desmond/landuse_studies:utils/thresholds');
var MSK = require('users/Desmond/landuse_studies:utils/masks');
var SMP = require('users/Desmond/landuse_studies:utils/sampling');
var CLF = require('users/Desmond/landuse_studies:utils/classifiers');
var CHG = require('users/Desmond/landuse_studies:utils/change');
var EXP = require('users/Desmond/landuse_studies:utils/exports');
var ACC = require('users/Desmond/landuse_studies:utils/accuracy');

// ── Study area ───────────────────────────────────────────────
var protectedAreas = ee.FeatureCollection(
  'projects/ee-desmond/assets/NewParkMerged');
print('Parks:', protectedAreas.aggregate_array('NAME'));

var geometry = protectedAreas
  .filter(ee.Filter.eq('NAME', PARK_NAME_FILTER))
  .geometry().dissolve({maxError:1});

Map.centerObject(geometry, 12);
Map.setOptions('SATELLITE');
Map.addLayer(
  ee.Image().byte().paint({
    featureCollection: protectedAreas.filter(
      ee.Filter.eq('NAME', PARK_NAME_FILTER)),
    color:1, width:2}),
  {palette:['ffffff']}, PARK_NAME + ' — Boundary', true);
print('=== ' + PARK_NAME + ' ===');

// ── Build composites, indices, RUE, thresholds, masks ────────
var s2Annual = C.getSentinel2Annual(2024, geometry);
var s2Dry    = C.getSeasonalComposite('2024-03-01','2024-05-15',geometry);
var s2Wet    = C.getSeasonalComposite('2024-05-01','2024-07-15',geometry);
var pcts     = C.getPercentileComposites(2024, geometry);
var emb2024  = C.getEmbeddingImage(2024, geometry);
var idx      = IDX.compute(s2Annual, s2Dry, s2Wet, pcts.p10, pcts.p90);
var rue      = RUE.computeAnnual2024(geometry);
var T        = THR.compute(idx, geometry);
var masks    = MSK.compute(idx, T);

// ── Visualise (layers + coverage prints) ─────────────────────
MSK.addLayers(masks);
MSK.printCoverage(masks, geometry);

// ── GCP sampling ─────────────────────────────────────────────
var clusterResult = SMP.clusterEmbedding(emb2024, geometry);
var gcps = SMP.buildGCPs(
  emb2024, idx, clusterResult.clusters, T, geometry);

// ── Train models + accuracy assessment ───────────────────────
var models = CLF.trainAllModels(
  gcps, emb2024, idx, rue, geometry);
ACC.exportTables(
  models.matrixA, models.matrixB,
  models.matrixC, models.matrixD, PARK_NAME);

// ── Classify all epochs ───────────────────────────────────────
var classifiedMaps = CLF.classifyAllEpochs(
  EPOCHS, models, geometry, PARK_NAME);

// ── Change analysis ───────────────────────────────────────────
var chg = CHG.analyse(
  classifiedMaps, EPOCHS, geometry, PARK_NAME);

// ── All exports ───────────────────────────────────────────────
EXP.classifiedMaps(classifiedMaps, EPOCHS, geometry, PARK_NAME);
EXP.changeProducts(chg, geometry, PARK_NAME);
EXP.csvTables(classifiedMaps, chg, EPOCHS, geometry, PARK_NAME);
EXP.addLegend(PARK_NAME);

print('=== ' + PARK_NAME + ' — COMPLETE ===');
print('Switch park: change PARK_NAME_FILTER, PARK_NAME, EPOCHS only.');