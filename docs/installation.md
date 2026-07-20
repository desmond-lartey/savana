# Installation

## Using pip

```bash
pip install savana
```

Extras, installable individually or combined:

```bash
# land-system classification with local vector file (shapefile/GeoPackage) AOI support:
pip install "savana[vector]"

# precipitation product assessment (xarray, netCDF4, requests, openpyxl,
# matplotlib, geopandas, shapely):
pip install "savana[rainfall]"

# the AI agent -- works with either module:
pip install "savana[agents]"

# everything:
pip install "savana[vector,rainfall,agents]"
```

## Requirements

- Python >= 3.10
- A Google Earth Engine account with a registered Cloud project
  ([register here](https://code.earthengine.google.com/register)) —
  required by both the classification and precipitation-assessment modules

## Verifying the install

```python
import savana
print(savana.__version__)

import savana.rainfall as rf   # only if you installed the [rainfall] extra
print(rf)
```

## Earth Engine authentication

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

For `savana.rainfall`, Earth Engine initialization is handled the same way
but lazily — it only fires right before a call that actually needs it
(`.ingest()`, `.extract()`, `.preview_stations()`, `.preview_map()`, or
`get_observations(source="ee_asset")`), so a purely offline run (e.g.
`obs_source="csv"` or `"demo"`) never prompts for Earth Engine auth at all.
Pass your project explicitly wherever you construct a `RainfallAssessment`
or call `validate_against_gpcc()`:

```python
from savana.rainfall import RainfallAssessment

ra = RainfallAssessment(ee_project="your-gcp-project-id")
```

## Precipitation data sources

`savana.rainfall` needs two kinds of data, both handled for you, neither
requiring you to manage local raster files:

- **Gridded precipitation products** (CHIRPS, ERA5-Land, GPM IMERG, MERRA-2,
  PERSIANN-CDR, TerraClimate by default): pulled directly from their public
  Earth Engine collections — nothing to download.
- **GPCC gauge observations** (the validation reference): either the public
  GPCC Full Data Daily archive, downloaded and point-extracted automatically
  (`obs_source="download"`, works for any station location), or a
  pre-extracted Earth Engine table asset if you have one
  (`obs_source="ee_asset"`, faster but limited to whichever stations are in
  that asset). Both stay point data — nothing here is rasterized or
  interpolated into a gridded GPCC surface.
