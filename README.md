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

**A geospatial intelligence ecosystem for savanna landscapes.**

`savana` is a growing Python ecosystem for understanding, monitoring, and reasoning
about savanna landscapes. It's starting with a validated adaptive land-system
classification method, and built from the ground up so that every result it produces
can be queried, summarized, and acted on through natural language, not just read off
a map. Classification of landscapes from raw satellite data to actionalble insights is the foundation.

## Statement of need

Savannas cover roughly a fifth of the Earth's land surface and support some of the
highest concentrations of biodiversity, pastoralist livelihoods, and protected-area
coverage anywhere in the world. Nowhere more so than across West and Central Africa,
where savanna mosaics form the ecological backbone of national parks, wildlife
corridors, and rangelands under mounting pressure from land conversion, fire regime
change, and rainfall variability. But the land use / land cover (LULC) products most
available to researchers and park managers in this region routinely collapse this
entire structural complexity into one or two undifferentiated "grass/shrub" classes which is
too coarse to answer the questions that actually matter for management: where is
canopy genuinely closing versus opening, which areas show real structural
degradation versus rainfall-driven greenness swings, and where should limited
conservation and grazing-management resources actually go.

This gap is not just a mapping problem, it is also an *access* problem. Analysts in
under-resourced institutions often have the satellite data and the research question,
but not the specialized remote-sensing pipeline needed to turn one into the other,
nor the time to manually interrogate every output. `savana` addresses both halves at
once. That is, an adaptive classification method with no hardcoded thresholds, so it
recalibrates to any savanna landscape's own spectral distribution rather than
assuming one park's canopy density applies to another's; and a built-in AI layer that
lets anyone, not just remote-sensing specialists, ask what a result means, in plain
language, based on strictly in what was actually computed.

## Current Key features

**Adaptive land-system classification**
- Resolves savanna landscapes into ecologically meaningful classes, Core Woodland,
  Open Woodland, Shrub-Transition Savanna, Grassland, Riparian/Wetland Vegetation,
  Anthropogenic Disturbance, for *any* AOI, with every threshold derived from that
  landscape's own index percentiles at run time. Classes are extendable.
- Four-model ablation (KNN baseline / RF-embeddings / RF-phenology /
  RF-embeddings+phenology) built on Sentinel-2, Google AlphaEarth satellite
  embeddings, and rainfall-normalised phenology
- Multi-epoch mapping with automatic fallback to embeddings-only classification for
  years lacking reliable seasonal Sentinel-2 coverage

**Change detection**
- Conservative change detection cross-validated against Rain Use Efficiency
  inter-annual variability, separating genuine structural change from
  rainfall-driven apparent change

**Analytical insights**
- Plain-English summaries and question-answering generated entirely from real
  computed results, every figure traces back to an actual pipeline output.

**AI agent, `SavanaGeoAgent`**
- Natural-language access to your results and your map in one place: ask about
  class areas, accuracy, or change; ask it to show years on the map, compare them,
  fly to locations, or add basemaps
- Built on real, proven infrastructure (Strands + any geoai map tooling) with savana's own evidence tools layered on top
- Ships with an inline chat + live-map UI (`agent.show_ui()`) for exploring results
  without writing further code

**Interactive visualization**
- `geemap`, `geolibre` -based maps in Jupyter, with year-toggle, swipe/split comparison against
  another year or the underlying basemap, and change-layer visualization
- Optional GeoLibre backend for teams already working in that ecosystem

**Data export**
- Google Drive / Earth Engine Asset export for classified maps and change products;
  confusion matrices and area statistics as `pandas.DataFrame` or CSV

## Install

```bash
pip install savana
# or, for local vector file (shapefile/geopackage) AOI support:
pip install "savana[vector]"
# or, for the AI agent:
pip install "savana[agents]"
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

## Ask your results questions

```python
from savana.agents import SavanaGeoAgent

agent = SavanaGeoAgent(clf, model="anthropic", model_id="claude-sonnet-4-6")

agent.ask("How much core woodland is there in 2024?")
agent.ask("Show 2019 and 2024 on the map")
agent.ask("What changed between the years, and how much of it is genuine?")

agent.show_ui()   # live map + chat, inline in the notebook
```

## Why it's adaptive

Every classification threshold (canopy density cutoffs, moisture cutoffs, seasonal
amplitude cutoffs) is derived from **percentiles of that AOI's own spectral index
distribution** at run time, nothing is hardcoded to one park's spectral range. Point
this at a different savanna landscape and it recalibrates automatically.

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

## Roadmap

`savana` is the first module of a larger ecosystem. Planned additions include:
- Additional class schemes / configurable taxonomies for other savanna biomes
- Alternative embedding backbones (e.g. other foundation models) as drop-in options
- Local (non-GEE) inference for pre-exported imagery
- Deeper agent integration with map-hosted UIs, beyond the current notebook experience
- A CLI

Contributions and issues welcome.

## Citation

If you use this package in your research, please cite the associated manuscript.

## License

Savana is free and open source software, licensed under the MIT License.

## Acknowledgments

We gratefully acknowledge the support of the following organizations:

-   [Irish Research Council](https://research.ie/funding/goipg/): This research is supported by the Government of Ireland Postgraduate Scholarship through Grant No. GOIPG/2025/8306, awarded under the [Reseearch Ireland Program](https://www.researchireland.ie/funding/government-ireland-postgraduate/).
-   [Department of Geography](https://www.mic.ul.ie/faculty-of-arts/department/geography?index=0): This work is also partially supported by the department of Geography, Mary Immaculate College.