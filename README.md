# Savana: A Geospatial Intelligence Ecosystem

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
  <img src="https://visitor-badge.laobi.icu/badge?page_id=desmond-lartey.savana" alt="Visitors">
</p>

**A growing ecosystem of geospatial intelligence tools, under one Python package.**

`savana` is not a single-purpose library — it's an umbrella package for
geospatial analysis modules that share a common design philosophy: adaptive
rather than hardcoded methods, grounded rather than fabricated insights, and
natural-language access to real computed results, not just static maps and
tables. Each module targets a different question, and each is independently
usable — install only what you need via the `[extra]` that matches it. Two
modules ship today: **land-system classification** for savanna landscapes,
and **precipitation product assessment** for validating global rainfall
datasets against gauge observations. More are planned; see
[Roadmap](#roadmap).

## Modules

### 🌳 Land-system classification (`savana`)

Resolves savanna landscapes into ecologically meaningful structural classes
— Core Woodland, Open Woodland, Shrub-Transition Savanna, Grassland,
Riparian/Wetland Vegetation, Anthropogenic Disturbance — for *any* AOI, with
every threshold derived from that landscape's own index percentiles at run
time rather than assumed from one park's spectral range. Built on
Sentinel-2, Google AlphaEarth satellite embeddings, and rainfall-normalised
phenology, with a 4-model ablation and RUE-validated change detection.
[Quick start ↓](#quick-start--land-system-classification)

### 🌧️ Precipitation product assessment (`savana.rainfall`)

Zone-stratified validation of global precipitation products (CHIRPS,
ERA5-Land, GPM IMERG, MERRA-2, PERSIANN-CDR, TerraClimate by default — bring
your own subset or additions) against real GPCC gauge observations, at any
station location you choose — the built-in West Africa 16-station network,
your own coordinates, or a `.geojson`/`.csv` file of stations. Produces
continuous and categorical validation metrics, threshold-sensitivity
analysis, and an application-weighted decision matrix ranking products for
specific management uses (fire risk, drought early warning, flood
forecasting, and more), plus an interactive Excel decision-support workbook.
[Quick start ↓](#quick-start--precipitation-product-assessment)

## Why "adaptive" and "grounded" matter here

Every classification threshold (canopy density, moisture, seasonal
amplitude cutoffs) is derived from **percentiles of that AOI's own spectral
index distribution** at run time — nothing hardcoded to one park's spectral
range. Every rainfall validation defaults to the published West Africa study
configuration but accepts your own stations, products, zones, and
application weights at every stage — nothing hardcoded to that one dataset
either. And every plain-English summary or Q&A answer, in both modules, is
generated strictly from real computed results — never a plausible-sounding
guess.

## Install

```bash
pip install savana
# land-system classification with local vector file (shapefile/GeoPackage) AOI support:
pip install "savana[vector]"
# precipitation product assessment:
pip install "savana[rainfall]"
# the AI agent (works with either module):
pip install "savana[agents]"
```

Both modules need a Google Earth Engine account with a registered Cloud
project ([register here](https://code.earthengine.google.com/register)).

## Quick start — land-system classification

```python
import savana

clf = savana.classify_landscape(
    aoi="path/to/my_area.geojson",   # or an EE asset ID, ee.Geometry, or geopandas GeoDataFrame
    epochs=[2019, 2021, 2024],
    park_name="My Study Area",
)

clf.show()                  # interactive map in Jupyter (geemap)
clf.accuracy_summary()      # pandas.DataFrame, one row per model (A/B/C/D)
clf.class_areas()           # pandas.DataFrame, area (km2) per class per epoch
clf.show_change()           # conservative + RUE-validated change map
clf.summarize()             # plain-English report, grounded in real computed results

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

## Quick start — precipitation product assessment

```python
from savana.rainfall import validate_against_gpcc

# Reproduces the published West Africa study exactly: 16 GPCC stations,
# all 6 products, 2001-2020.
result = validate_against_gpcc(ee_project="your-gcp-project-id")

print(result.summarize())
result.export_workbook("decision_tool.xlsx")
```

Your own stations, your own products, your own years — same call, different
parameters:

```python
result = validate_against_gpcc(
    stations=[(-1.5, 12.4), (2.1, 6.5)],   # or a single (lon, lat), a DataFrame,
                                             # or a .geojson/.csv file of stations
    products=["CHIRPS", "GPM_IMERG"],
    start_year=2015,
    end_year=2023,
    ee_project="your-gcp-project-id",
)
print(result.validation_overall_df)
print(result.answer("which product is best for drought early warning?"))
```

Step-by-step control, with interactive previews before committing to a full
validation run:

```python
from savana.rainfall import RainfallAssessment

ra = RainfallAssessment(stations=(-1.5, 12.4), ee_project="your-gcp-project-id")
ra.preview_stations()                       # is this actually where you think it is?
ra.ingest(start="2020-01-01", end="2020-12-31")
ra.preview_map("CHIRPS", show_gpcc=True)    # product raster + real GPCC points, same scale

ra.get_observations(source="download")
ra.extract().merge()
ra.compare_table()                          # GPCC vs every product, side by side

ra.validate().score()
ra.show("recommendation_heatmap")
```

## Ask your results questions

One agent class works with either module — pass a classifier, a rainfall
assessment, or both at once.

```python
from savana.agents import SavanaGeoAgent

agent = SavanaGeoAgent(clf, model="anthropic", model_id="claude-sonnet-4-6")
agent.ask("How much core woodland is there in 2024?")
agent.ask("Show 2019 and 2024 on the map")
agent.show_ui()   # live map + chat, inline in the notebook
```

```python
agent = SavanaGeoAgent(rainfall=ra, model="anthropic")
agent.ask("Which product would you recommend for fire risk monitoring?")
```

## Core classification pipeline

1. **Composites** (`savana.composites`): cloud-masked Sentinel-2 annual/seasonal/percentile
   composites + AlphaEarth annual embeddings (64-dim).
2. **Indices** (`savana.indices`): NDVI/NDMI/NDBI/MNDWI across annual, dry-season,
   wet-season, and percentile composites; a 14-band phenological feature stack.
3. **RUE** (`savana.rue`): Rain Use Efficiency, integrated NDVI normalised by rainfall,
   with valid-month normalisation to remove Sentinel-2 tile-boundary bias.
4. **Thresholds** (`savana.thresholds`): fully adaptive, percentile-derived cutoffs.
5. **Masks** (`savana.masks`): six mutually exclusive land-system masks.
6. **Sampling** (`savana.sampling`): unsupervised k-means stratified candidate sampling
   → rule-based provisional labels → confidence-margin filter → class balancing.
7. **Classifiers** (`savana.classifiers`): 4-model ablation and multi-epoch mapping.
8. **Change** (`savana.change`): conservative, RUE-validated change detection.
9. **Insights** (`savana.insights`): grounded facts, summaries, and Q&A.
10. **Agents** (`savana.agents`): natural-language access to results and map control.
11. **Accuracy / Exports** (`savana.accuracy`, `savana.exports`): confusion matrices,
    accuracy summaries, and Drive/Asset/CSV export helpers.

## Precipitation assessment pipeline

1. **Config** (`savana.rainfall.config`): every default (products, stations,
   zones, application weights) as overridable data, not hardcoded logic.
2. **Stations** (`savana.rainfall.stations`): flexible station input (DataFrame,
   file, coordinates), GPCC observation loading (public archive, EE asset, or CSV).
3. **Zones** (`savana.rainfall.zones`): build ecological/climatic zones from your
   own base regions and split rules, load your own zone file, or use one AOI
   with no stratification at all.
4. **Ingestion** (`savana.rainfall.ingestion`): per-product harmonisation to a
   common monthly mm/day grid, including the MERRA-2 hourly→daily workaround.
5. **Extraction** (`savana.rainfall.extraction`): point-sample products at
   stations, with optional CSV caching per product.
6. **Validation** (`savana.rainfall.validation`): continuous (bias, RMSE, r,
   NSE, KGE, ...) and categorical (POD, FAR, CSI, ETS, ...) metrics, at any
   aggregation level (station/zone/season/pooled).
7. **Thresholds** (`savana.rainfall.thresholds`): categorical metric
   sensitivity across a rain-detection threshold sweep.
8. **Spatial** (`savana.rainfall.spatial`): interactive preview maps —
   product climatology, inter-product bias, real GPCC point overlays,
   per-station bias against ground truth.
9. **Decision** (`savana.rainfall.decision`): application-weighted composite
   scoring and the interactive Excel decision-support workbook.
10. **Insights** (`savana.rainfall.insights`): grounded facts, summaries, and Q&A.
11. **Viz** (`savana.rainfall.viz`): static comparison and ranking figures.
12. **Pipeline** (`savana.rainfall.pipeline`): the `RainfallAssessment`
    orchestrator and the one-call `validate_against_gpcc()`.

## Roadmap

`savana` is an umbrella for a growing set of independently-usable geospatial
modules, not a single fixed pipeline. Land-system classification and
precipitation assessment are the first two. Planned additions include:

- Additional class schemes / configurable taxonomies for other savanna biomes
- A temperature product assessment module, following the same pattern as
  `savana.rainfall`
- Integrated climate risk / impact indices (drought, heat stress, compound
  hazard) combining validated precipitation and temperature products
- Alternative embedding backbones (e.g. other foundation models) as drop-in
  options for classification
- Local (non-GEE) inference for pre-exported imagery
- Deeper agent integration with map-hosted UIs, beyond the current notebook
  experience
- A CLI

New modules should be addable without breaking the existing API — see
[Contributing](docs/contributing.md).

## Citation

If you use this package in your research, please cite the associated manuscript(s).

## License

Savana is free and open source software, licensed under the MIT License.

## Acknowledgments

We gratefully acknowledge the support of the following organizations:

-   [Irish Research Council](https://research.ie/funding/goipg/): This research is supported by the Government of Ireland Postgraduate Scholarship through Grant No. GOIPG/2025/8306, awarded under the [Research Ireland Programme](https://www.researchireland.ie/funding/government-ireland-postgraduate/).
-   [Department of Geography](https://www.mic.ul.ie/faculty-of-arts/department/geography?index=0): This work is also partially supported by the department of Geography, Mary Immaculate College.
