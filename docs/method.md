# Method Overview

## Land-system classification

Every classification threshold is derived from **percentiles of that AOI's own
spectral index distribution** at run time — nothing is hardcoded to one
landscape's spectral range. Point `savana` at a different savanna system and
it recalibrates automatically.

1. **Composites** (`savana.composites`) — cloud-masked Sentinel-2
   annual/seasonal/percentile composites + AlphaEarth annual embeddings (64-dim).
2. **Indices** (`savana.indices`) — NDVI/NDMI/NDBI/MNDWI across annual,
   dry-season, wet-season, and percentile composites; a 14-band phenological
   feature stack.
3. **RUE** (`savana.rue`) — Rain Use Efficiency: integrated NDVI normalised by
   rainfall, with valid-month normalisation to remove Sentinel-2 tile-boundary
   bias.
4. **Thresholds** (`savana.thresholds`) — fully adaptive, percentile-derived
   cutoffs.
5. **Masks** (`savana.masks`) — six mutually exclusive land-system masks.
6. **Sampling** (`savana.sampling`) — unsupervised k-means stratified
   candidate sampling → rule-based provisional labels → confidence-margin
   filter → class balancing.
7. **Classifiers** (`savana.classifiers`) — four-model ablation:

   | Model | Features | Role |
   |---|---|---|
   | A | KNN (k=3), AlphaEarth embeddings | Baseline |
   | B | Random Forest, AlphaEarth embeddings | Embeddings-only |
   | C | Random Forest, phenology indices | Diagnostic only — circular (labels derived from the same indices) |
   | D | Random Forest, embeddings + phenology | **Primary** — used for all epoch mapping |

   Years without reliable seasonal Sentinel-2 coverage automatically fall back
   to Model B (embeddings-only).
8. **Change** (`savana.change`) — conservative change detection
   cross-validated against RUE inter-annual variability, separating genuine
   structural change from rainfall-driven apparent change.
9. **Accuracy / Exports** (`savana.accuracy`, `savana.exports`) — confusion
   matrices, accuracy summaries, and Drive/Asset/CSV export helpers.

See the [API Reference](api.md) for the full function/class listing.

---

## Precipitation product assessment

Zone-stratified, dual-class validation of global precipitation products
against real GPCC gauge observations, following a published West Africa
study's methodology as the default configuration — every default
(products, stations, zones, application weights) is data, not hardcoded
logic, so a different region, gauge network, or set of products uses the
exact same pipeline.

1. **Config** (`savana.rainfall.config`) — the default 6-product catalogue
   (CHIRPS, ERA5-Land, GPM IMERG, MERRA-2, PERSIANN-CDR, TerraClimate) with
   per-product unit-harmonisation rules, the default 16 GPCC gauge stations,
   the default 5-zone West Africa ecological scheme, and the 7
   application-weight profiles used for decision scoring — all overridable.
2. **Stations** (`savana.rainfall.stations`) — flexible station input
   (DataFrame, `.geojson`/`.csv` file, coordinate list, single coordinate)
   normalised through one entry point; GPCC observations loaded from the
   public daily archive (any station, anywhere), a pre-extracted Earth Engine
   table asset (fast, limited to that asset's stations), a CSV you already
   have, or synthetic demo data for testing.
3. **Zones** (`savana.rainfall.zones`) — ecological/climatic zones built from
   your own named base regions split by latitude bands (a generalised port of
   the original GEE zone-delineation tool), loaded from your own zone file,
   wrapped from a single custom AOI with no stratification, or a documented
   latitude-band fallback when no zone geometry is available at all.
4. **Ingestion** (`savana.rainfall.ingestion`) — every product harmonised to
   a common monthly mean mm/day grid via its own conversion rule (direct
   scale, ERA5-Land's per-month day-count division, TerraClimate's monthly
   accumulation division, or MERRA-2's hourly→daily pre-aggregation to stay
   within Earth Engine's per-request compute limits).
5. **Extraction** (`savana.rainfall.extraction`) — point-sampling each
   product's grid at every station, with optional per-product CSV caching so
   a re-run reuses what's already been pulled instead of re-hitting Earth
   Engine.
6. **Validation** (`savana.rainfall.validation`) — two metric classes,
   computed at any aggregation level (per-station, per-zone, per-season, or
   pooled) via one shared grouping function:
   - *Continuous*: Bias, PBIAS, MAE, RMSE, r, r², NSE, KGE (the primary
     ranking metric).
   - *Categorical*: POD, FAR, CSI, ETS, frequency bias, from a 2×2 wet/dry
     contingency table at the WMO standard 1.0 mm/day threshold by default.
7. **Thresholds** (`savana.rainfall.thresholds`) — categorical metric
   sensitivity swept across multiple rain-detection thresholds, since
   categorical detection is structurally unstable in near-zero-rainfall
   dryland environments regardless of which product is used.
8. **Spatial** (`savana.rainfall.spatial`) — interactive `geemap`-based
   preview maps: a product's climatology, inter-product bias (never a GPCC
   comparison — GPCC has no gridded form in this package), real GPCC point
   values overlaid on a product's raster on the same color scale, and
   per-station bias against true GPCC ground truth.
9. **Decision** (`savana.rainfall.decision`) — application-weighted composite
   scoring (default: fixed-bound normalisation, matching the published
   results; a per-zone relative normalisation is available as an alternate),
   and an interactive Excel workbook with dropdown-driven live lookups
   (`SELECTOR`/`SCORECARD` sheets) alongside the flat result tables.
10. **Insights** (`savana.rainfall.insights`) — grounded facts, a
    plain-English summary, and keyword-matched Q&A, following the exact
    facts/summarize/answer pattern used by the classification module's
    `savana.insights`.
11. **Viz** (`savana.rainfall.viz`) — static comparison figures: metric
    heatmaps, zonal boxplots, a Taylor diagram, application-ranking bar
    charts, and the app×zone recommendation heatmap.
12. **Pipeline** (`savana.rainfall.pipeline`) — the `RainfallAssessment`
    chainable orchestrator tying every stage together, plus the one-call
    `validate_against_gpcc()` convenience function for reproducing the whole
    assessment from a handful of plain parameters.

See the [Precipitation Assessment API Reference](api_rainfall.md) for the
full function/class listing.
