// ============================================================
// MODULE: accuracy
// Confusion matrix and accuracy summary CSV exports.
// Produces 2 files per park:
//   {park}_confusion_matrix_full.csv , 24 rows (4 models × 6 classes)
//   {park}_accuracy_summary.csv      , 4 rows (one per model)
// ============================================================

var CLASS_INFO = [
  {code:1, label:'Core_Woodland'},
  {code:2, label:'Open_Woodland'},
  {code:3, label:'Shrub_Transition'},
  {code:4, label:'Grassland'},
  {code:5, label:'Riparian'},
  {code:6, label:'Anthropogenic'}
];

// Convert a ConfusionMatrix to a labelled FeatureCollection.
// producersAccuracy() returns shape (6,1), use Array.get([i,0])
// consumersAccuracy() returns shape (1,6), use Array.get([0,i])
var cmToFC = function(cm, modelName, parkName) {
  var oa    = cm.accuracy();
  var kappa = cm.kappa();
  var pa    = ee.Array(cm.producersAccuracy());
  var ua    = ee.Array(cm.consumersAccuracy());
  var arr   = cm.array();
  var rows  = CLASS_INFO.map(function(actualCls, i) {
    var rowList = arr.slice(0, i, i+1).project([1]).toList();
    var props   = {
      park:               parkName,
      model:              modelName,
      actual_class_code:  actualCls.code,
      actual_class_label: actualCls.label,
      overall_accuracy:   oa,
      kappa:              kappa,
      producer_accuracy:  pa.get([i, 0]),
      user_accuracy:      ua.get([0, i])
    };
    CLASS_INFO.forEach(function(predCls, j) {
      props['pred_' + predCls.label] = rowList.get(j);
    });
    return ee.Feature(null, props);
  });
  return ee.FeatureCollection(rows);
};

// One summary row per model with flat PA/UA columns.
var modelSummary = function(cm, code, desc, space, parkName) {
  var oa   = cm.accuracy();
  var kap  = cm.kappa();
  var pa   = ee.Array(cm.producersAccuracy());
  var ua   = ee.Array(cm.consumersAccuracy());
  var props = {
    park:              parkName,
    model_code:        code,
    model_description: desc,
    feature_space:     space,
    overall_accuracy:  oa,
    kappa:             kap
  };
  CLASS_INFO.forEach(function(cls, i) {
    props['PA_' + cls.label] = pa.get([i, 0]);
    props['UA_' + cls.label] = ua.get([0, i]);
  });
  return ee.Feature(null, props);
};

// Main export function, call with the 4 error matrices and park name.
exports.exportTables = function(mA, mB, mC, mD, parkName) {
  var fullCM = ee.FeatureCollection([])
    .merge(cmToFC(mA, 'A_KNN3_Embeddings64',        parkName))
    .merge(cmToFC(mB, 'B_RF150_Embeddings64',        parkName))
    .merge(cmToFC(mC, 'C_RF150_PhenologyOnly14',     parkName))
    .merge(cmToFC(mD, 'D_RF150_Embeddings_Pheno78',  parkName));

  var summary = ee.FeatureCollection([
    modelSummary(mA,'A',
      'KNN (k=3) | AlphaEarth Embeddings only',
      'Embeddings 64-dim [baseline]', parkName),
    modelSummary(mB,'B',
      'RF 150 trees | AlphaEarth Embeddings only',
      'Embeddings 64-dim', parkName),
    modelSummary(mC,'C',
      'RF 150 trees | Phenological Indices only [CIRCULAR]',
      'Phenology 14-dim, label-feature circularity inflates OA',
      parkName),
    modelSummary(mD,'D',
      'RF 150 trees | Embeddings + Phenology [PRIMARY]',
      'Embeddings 64-dim + Phenology 14-dim = 78-dim', parkName)
  ]);

  Export.table.toDrive({
    collection:     fullCM,
    description:    parkName + '_ConfusionMatrix_AllModels',
    folder:         'LandSystem_PhD',
    fileNamePrefix: parkName + '_confusion_matrix_full',
    fileFormat:     'CSV'
  });
  Export.table.toDrive({
    collection:     summary,
    description:    parkName + '_AccuracySummary',
    folder:         'LandSystem_PhD',
    fileNamePrefix: parkName + '_accuracy_summary',
    fileFormat:     'CSV'
  });

  print('--- ACCURACY: ' + parkName + ' ---');
  print('Model A | OA:', mA.accuracy(), '| κ:', mA.kappa());
  print('Model B | OA:', mB.accuracy(), '| κ:', mB.kappa());
  print('Model C | OA:', mC.accuracy(), '[CIRCULAR, inflated]');
  print('Model D | OA:', mD.accuracy(), '| κ:', mD.kappa());
};