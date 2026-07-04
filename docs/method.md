# Method Overview

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
