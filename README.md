# Savana: A Geosptaial Intelligence for Savannah Landscapes

<p align="center">
  <img src="https://raw.githubusercontent.com/desmond-lartey/savana/Fires/docs/assets/logo-readme.png" alt="savana logo" width="180">
</p>

<p align="center">
  <a href="https://pypi.org/project/savana/" target="_blank" rel="noopener noreferrer"><img src="https://img.shields.io/pypi/v/savana?color=blue" alt="PyPI"></a>
  <a href="https://pypistats.org/packages/savana" target="_blank" rel="noopener noreferrer"><img src="https://img.shields.io/pypi/dm/savana" alt="Downloads"></a>
  <a href="https://github.com/desmond-lartey/savana/blob/Fires/LICENSE" target="_blank" rel="noopener noreferrer"><img src="https://img.shields.io/github/license/desmond-lartey/savana" alt="License"></a>
  <a href="https://github.com/desmond-lartey/savana/stargazers" target="_blank" rel="noopener noreferrer"><img src="https://img.shields.io/github/stars/desmond-lartey/savana?style=social" alt="Stars"></a>
  <a href="https://github.com/desmond-lartey/savana/network/members" target="_blank" rel="noopener noreferrer"><img src="https://img.shields.io/github/forks/desmond-lartey/savana?style=social" alt="Forks"></a>
  <a href="https://www.youtube.com/@desmondlartey31" target="_blank" rel="noopener noreferrer"><img src="https://img.shields.io/badge/YouTube-Tutorials-red" alt="YouTube"></a>
</p>

**Adaptive classification of complex savanna landscapes into management-relevant land-system classes.**

Conventional LULC (land use / land cover) products typically collapse the internal
structure of savanna landscapes into one or two undifferentiated "grass/shrub" classes which iis
too coarse to be useful for protected-area management, grazing planning, or fire regime
analysis. `savana` implements a validated, fully adaptive classification method
(Sentinel-2 + Google AlphaEarth satellite embeddings + rainfall-normalised phenology)
that resolves savanna landscapes into ecologically meaningful classes such as Core
Woodland, Open Woodland, Shrub-Transition Savanna, Grassland, Riparian/Wetland
Vegetation, and Anthropogenic Disturbance, and does it for *any* AOI, with **no
hardcoded thresholds**: every cutoff is derived from that landscape's own index
percentiles.

This package started as the Google Earth Engine implementation behind a land-system
classification study of West African protected areas (Kogyae, Old Oyo, and others). It's
designed as a foundation, the four-model ablation (KNN baseline / RF-embeddings /
RF-phenology / RF-embeddings+phenology), the RUE-validated conservative change
detection, and the adaptive thresholding are all built as independent, composable
modules so new sensors, feature stacks, and classification schemes can be added
without breaking the existing API.

## Install

```bash
pip install savana
# or, for local vector file (shapefile/geopackage) AOI support:
pip install "savana[vector]"
```

You'll also need an Earth Engine account with a registered Cloud project
(https://code.earthengine.google.com/register).

## Quick start

```python
import savana

clf = savana.classify_landscape(
    aoi="path/to/my_area.geojson",   # or an EE asset ID, ee.Geometry, or geopandas GeoDataFrame
    epochs=[2019, 2021, 2024],
    park_name="My Study Area",
)

clf.show()                  # interactive map in Jupyter (geemap)
clf.accuracy_summary()      # pandas.DataFrame — one row per model (A/B/C/D)
clf.class_areas()           # pandas.DataFrame — area (km2) per class per epoch
clf.show_change()           # conservative + RUE-validated change map

clf.export(drive_folder="MyProject")   # push results to Google Drive
```

Using an Earth Engine parks database with multiple features, filtered by name
(as in the original manuscript workflow):

```python
clf = savana.classify_landscape(
    aoi="projects/ee-desmond/assets/NewParkMerged",
    name_filter="Kogyae",
    park_name="Kogyae",
    epochs=[2017, 2019, 2021, 2024],
)
```

## Why it's adaptive

Every classification threshold (canopy density cutoffs, moisture cutoffs, seasonal
amplitude cutoffs) is derived from **percentiles of that AOI's own spectral index
distribution** at run time — nothing is hardcoded to one park's spectral range. Point
this at a different savanna landscape and it recalibrates automatically.

## Method overview

1. **Composites** (`savana.composites`): cloud-masked Sentinel-2 annual/seasonal/percentile
   composites + AlphaEarth annual embeddings (64-dim).
2. **Indices** (`savana.indices`): NDVI/NDMI/NDBI/MNDWI across annual, dry-season,
   wet-season, and percentile composites; a 14-band phenological feature stack.
3. **RUE** (`savana.rue`): Rain Use Efficiency — integrated NDVI normalised by rainfall,
   with valid-month normalisation to remove Sentinel-2 tile-boundary bias.
4. **Thresholds** (`savana.thresholds`): fully adaptive, percentile-derived cutoffs.
5. **Masks** (`savana.masks`): six mutually exclusive land-system masks.
6. **Sampling** (`savana.sampling`): unsupervised k-means stratified candidate sampling
   → rule-based provisional labels → confidence-margin filter → class balancing.
7. **Classifiers** (`savana.classifiers`): 4-model ablation (KNN baseline, RF-embeddings,
   RF-phenology [diagnostic only — circular], RF-embeddings+phenology [primary]) and
   multi-epoch mapping, with automatic fallback to embeddings-only for years lacking
   reliable seasonal Sentinel-2 coverage.
8. **Change** (`savana.change`): conservative change detection cross-validated against
   RUE inter-annual variability, separating genuine structural change from
   rainfall-driven apparent change.
9. **Accuracy / Exports** (`savana.accuracy`, `savana.exports`): confusion matrices,
   accuracy summaries, and Drive/Asset/CSV export helpers.

## Roadmap

This is the first module of a larger package. Planned additions include:
- Additional class schemes / configurable taxonomies for other savanna biomes
- Alternative embedding backbones (e.g. other foundation models) as drop-in options
- Local (non-GEE) inference for pre-exported imagery
- A CLI

Contributions and issues welcome.

## Citation

If you use this package in your research, please cite the associated manuscript
(citation to be added on publication).


## 📄 License

Savana is free and open source software, licensed under the MIT License.

## Acknowledgments

We gratefully acknowledge the support of the following organizations:

-   [Irish Research Council](https://research.ie/funding/goipg/): This research is supported by the Government of Ireland Postgraduate Scholarship through Grant No. GOIPG/2025/8306, awarded under the [Reseearch Ireland Program](https://www.researchireland.ie/funding/government-ireland-postgraduate/).
-   [Department of Geography](https://www.mic.ul.ie/faculty-of-arts/department/geography?index=0): This work is also partially supported by the department of Geography, Mary Immaculate College.