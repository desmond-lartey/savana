# Changelog

## 0.1.0

- Initial release
- Ported the full land-system classification pipeline: composites, indices,
  RUE, adaptive thresholds, masks, GCP sampling, 4-model ablation training,
  multi-epoch classification, RUE-validated change detection, accuracy
  reporting, and Drive/Asset export
- Generalised AOI input to accept EE assets, local vector files, `ee.Geometry`,
  and `geopandas.GeoDataFrame` (not just one hardcoded parks database)
- `SavanaClassifier` / `classify_landscape()` high-level API
