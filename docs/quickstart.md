# Quick Start

## One-call classification

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

## Using an Earth Engine parks database, filtered by name

```python
clf = savana.classify_landscape(
    aoi="projects/ee-desmond/assets/NewParkMerged",
    name_filter="Kogyae",
    park_name="Kogyae",
    epochs=[2017, 2019, 2021, 2024],
)
```

## Step-by-step control

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
