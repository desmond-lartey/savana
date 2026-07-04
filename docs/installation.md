# Installation

## Using pip

```bash
pip install savana
```

For local vector file (shapefile/GeoPackage) AOI support:

```bash
pip install "savana[vector]"
```

## Requirements

- Python >= 3.10
- A Google Earth Engine account with a registered Cloud project
  ([register here](https://code.earthengine.google.com/register))

## Verifying the install

```python
import savana
print(savana.__version__)
```

The first time you run anything that touches Earth Engine, you'll be prompted
to authenticate:

```python
import savana
savana.initialize(project="your-gcp-project-id")
```

If you've already run `earthengine authenticate` from the command line, or
have a valid Earth Engine session in your environment, `savana.initialize()`
(or simply calling `savana.classify_landscape(...)` directly) will pick that
up automatically.
