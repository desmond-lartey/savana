# Quick Start

`savana` ships two independently-usable modules today. Pick the section for
the one you need, nothing here requires the other.

## Land-system classification

### One-call classification

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

clf.export(drive_folder="MyProject")   # push results to Google Drive
```

### Using an Earth Engine parks database, filtered by name

```python
clf = savana.classify_landscape(
    aoi="projects/ee-desmond/assets/NewParkMerged",
    name_filter="Kogyae",
    park_name="Kogyae",
    epochs=[2017, 2019, 2021, 2024],
)
```

### Step-by-step control

If you want to inspect intermediate results (masks, thresholds, GCPs) instead
of running the full pipeline in one call:

```python
clf = savana.SavanaClassifier(
    aoi="path/to/my_area.geojson",
    epochs=[2019, 2021, 2024],
    park_name="My Study Area",
)

clf.build_features()          # composites, indices, RUE, thresholds, masks
clf.sample_training_points()  # unsupervised clustering + rule-based labels
clf.train()                   # 4-model ablation
clf.classify()                # multi-epoch classification
clf.analyse_change()          # conservative + RUE-validated change detection

clf.masks       # dict of ee.Image masks
clf.T           # dict of ee.Number adaptive thresholds
clf.gcps        # ee.FeatureCollection of ground control points
clf.models      # trained classifiers + confusion matrices
```

---

## Precipitation product assessment

### One-call validation

```python
from savana.rainfall import validate_against_gpcc

# Reproduces the published West Africa study exactly: 16 GPCC stations,
# all 6 default products (CHIRPS, ERA5-Land, GPM IMERG, MERRA-2,
# PERSIANN-CDR, TerraClimate), 2001-2020.
result = validate_against_gpcc(ee_project="your-gcp-project-id")

print(result.summarize())
result.export_workbook("decision_tool.xlsx")
```

Your own stations, your own products, your own years, same call:

```python
result = validate_against_gpcc(
    stations=[(-1.5, 12.4), (2.1, 6.5)],   # a single (lon, lat), a list of them,
                                             # a DataFrame, or a .geojson/.csv path
    products=["CHIRPS", "GPM_IMERG"],       # any subset of the default 6
    start_year=2015,
    end_year=2023,
    ee_project="your-gcp-project-id",
)
print(result.validation_overall_df)
print(result.answer("which product is best for drought early warning?"))
```

### Step-by-step control, with previews before you commit

Every stage can be inspected before moving to the next, useful before
running a full multi-year, multi-product assessment.

```python
from savana.rainfall import RainfallAssessment

ra = RainfallAssessment(stations=(-1.5, 12.4), ee_project="your-gcp-project-id")

ra.preview_stations()                        # is this actually where you think it is?

ra.ingest(start="2020-01-01", end="2020-12-31")
ra.preview_map("CHIRPS")                      # one product's spatial pattern
ra.preview_map("CHIRPS", reference="GPM_IMERG")  # inter-product bias (never vs GPCC directly)

ra.get_observations(source="download")        # or source="ee_asset" for the built-in 16 stations
ra.preview_observations()                     # raw GPCC time series, sanity check
ra.preview_map("CHIRPS", show_gpcc=True)      # product raster + real GPCC points, same color scale

ra.extract().merge()
ra.compare_table()                            # GPCC vs every product, side by side, per station-month
ra.preview_comparison()                       # obs-vs-sim scatter, before any formal metric
ra.preview_station_bias("CHIRPS")             # per-station bias against real GPCC, on the map

ra.assign_zones()                             # optional, pooled validation if skipped
ra.validate().analyze_thresholds().score()

print(ra.summarize())
ra.show("recommendation_heatmap")
ra.export_workbook("decision_tool.xlsx")
```

### Using your own ecological/climatic zones

```python
from savana.rainfall import zones

# Option A: one custom AOI, no stratification needed
one_zone = zones.single_region_zone((-2.0, 5.0, 1.0, 8.0), zone_name="My Study Area")
ra.assign_zones(zones_gdf=one_zone)

# Option B: build real zones from your own base regions + latitude-band splits
zones_fc = zones.build_zones_from_bands(
    base_zones={"my_region": "projects/your-project/assets/your_region"},
    zone_defs=[
        {"zone_name": "North", "source_zone": "my_region", "lat_min": 5, "lat_max": 15},
        {"zone_name": "South", "source_zone": "my_region", "lat_min": -5, "lat_max": 5},
    ],
)
ra.assign_zones(zones_fc=zones_fc)

# Option C: do nothing -- .validate() runs pooled, using a documented
# latitude-band fallback for the zone column
```

## Ask your results questions

One agent class, either module (or both at once):

```python
from savana.agents import SavanaGeoAgent

agent = SavanaGeoAgent(clf, model="anthropic", model_id="claude-sonnet-4-6")
agent.ask("How much core woodland is there in 2024?")
agent.show_ui()   # live map + chat, inline in the notebook
```

```python
agent = SavanaGeoAgent(rainfall=ra, model="anthropic")
agent.ask("Which product would you recommend for fire risk monitoring, and why?")
```

```python
# both loaded at once -- one agent, one conversation, covers both result sets
agent = SavanaGeoAgent(clf=clf, rainfall=ra, model="anthropic")
```
