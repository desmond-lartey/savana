# Changelog

## Unreleased

- New module: `savana.rainfall`, zone-stratified validation of global
  precipitation products (CHIRPS, ERA5-Land, GPM IMERG, MERRA-2,
  PERSIANN-CDR, TerraClimate by default) against GPCC gauge observations,
  reproducing a published West Africa study's methodology as the default
  configuration while accepting your own stations, products, zones, and
  application weights at every stage
- `RainfallAssessment` chainable orchestrator and one-call
  `validate_against_gpcc()` convenience function
- Continuous (Bias, PBIAS, MAE, RMSE, r, r², NSE, KGE) and categorical (POD,
  FAR, CSI, ETS, frequency bias) validation metrics at any aggregation level,
  plus rain-detection threshold-sensitivity analysis
- Application-weighted composite scoring and an interactive Excel
  decision-support workbook (dropdown-driven `SELECTOR`/`SCORECARD` sheets)
- Interactive preview maps before running a full assessment: station
  locations, product climatology, inter-product bias, real GPCC point
  observations overlaid on a product's raster, and per-station bias against
  GPCC ground truth
- Grounded facts/summary/Q&A (`savana.rainfall.insights`), following the same
  pattern as the classification module's `savana.insights`
- `SavanaGeoAgent` now accepts a `RainfallAssessment` (`rainfall=`) in
  addition to, or instead of, a `SavanaClassifier` (`clf=`), one agent, one
  conversation, either or both result sets
- New optional dependency group: `savana[rainfall]`

## 0.1.0

- Initial release
- Ported the full land-system classification pipeline: composites, indices,
  RUE, adaptive thresholds, masks, GCP sampling, 4-model ablation training,
  multi-epoch classification, RUE-validated change detection, accuracy
  reporting, and Drive/Asset export
- Generalised AOI input to accept EE assets, local vector files, `ee.Geometry`,
  and `geopandas.GeoDataFrame` (not just one hardcoded parks database)
- `SavanaClassifier` / `classify_landscape()` high-level API
