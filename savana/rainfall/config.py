"""Default configuration for global precipitation product assessment.

Everything here is a *default*, every public function in
``savana.rainfall`` accepts overrides, so a user assessing a different
region, a different subset of products, their own gauge network, or
their own application weights is not locked into the West Africa study
configuration. The WA study (16 GPCC FDD v2022 stations, 5 ecological
zones, 6 global precipitation products, 7 conservation/water-management
applications) ships as the default so ``savana.rainfall`` is useful out
of the box and reproduces the original manuscript, but nothing here is
required to use the package on a different AOI.

Nothing in this module touches Earth Engine or hits the network, it is
pure data, safe to import eagerly. EE objects (``ee.FeatureCollection``,
``ee.Geometry``) are built lazily, inside functions in :mod:`.stations`
and :mod:`.ingestion`, exactly where the JS/EE equivalents built them.
"""

from __future__ import annotations

# ════════════════════════════════════════════════════════════
# Study period & spatial resolution
# ════════════════════════════════════════════════════════════

# Default study window, matches the GPCC gauge extraction and the
# published validation (2001-2020). Override per-call for a different
# period; product availability is still clipped via PRODUCT_DATE_RANGES.
DEFAULT_START_DATE = "2001-01-01"
DEFAULT_END_DATE = "2020-12-31"

# 0.25 deg ~ 25 km, matches the coarsest product in the default catalogue
# (MERRA-2). All products are resampled to this common grid for
# inter-comparison. Override if your own product set has a different
# coarsest native resolution.
DEFAULT_TARGET_RESOLUTION_DEG = 0.25
DEFAULT_TARGET_RESOLUTION_M = 27830
DEFAULT_RESAMPLE_METHOD = "bilinear"

# WMO standard wet/dry detection threshold (mm/day) for categorical
# metrics (POD, FAR, CSI, ETS, frequency bias).
DEFAULT_RAIN_THRESHOLD_MM_DAY = 1.0

# Thresholds swept in the threshold-sensitivity analysis.
DEFAULT_THRESHOLD_SWEEP_MM_DAY = [0.1, 0.5, 1.0, 2.0, 5.0]


# ════════════════════════════════════════════════════════════
# Precipitation product catalogue
# ════════════════════════════════════════════════════════════
#
# Fields
# ──────
# collection      : GEE ImageCollection ID
# band            : band name to select
# native_temporal : "daily" | "monthly" | "hourly", controls how
#                   ingestion.py aggregates to monthly mean mm/day
# conversion      : "none" | "scale" | "era5_monthly" | "terra_monthly"
#                  , selects the harmonisation function in ingestion.py
# scale_factor    : multiplier applied before monthly aggregation
#                   (None for era5_monthly/terra_monthly, those need a
#                   per-image days-in-month division, done in ingestion.py)
# units_raw       : physical unit of the raw band values
# units_out       : always "mm/day" after harmonisation
# type            : product category, for grouping in plots/tables
# native_res_deg  : native spatial resolution (documentation only)
# notes           : caveats specific to that product's conversion
#
# A user assessing a different product set passes their own dict with
# this same shape to any ``savana.rainfall`` function that accepts
# ``products=``; nothing downstream assumes exactly these six keys.

DEFAULT_PRODUCTS: dict[str, dict] = {
    "CHIRPS": {
        "collection": "UCSB-CHG/CHIRPS/DAILY",
        "band": "precipitation",
        "native_temporal": "daily",
        "conversion": "none",
        "scale_factor": 1.0,
        "units_raw": "mm/day",
        "units_out": "mm/day",
        "type": "satellite_gauge_merged",
        "native_res_deg": 0.05,
        "notes": "Aggregation: monthly mean of daily mm/day values.",
    },
    "PERSIANN_CDR": {
        "collection": "NOAA/PERSIANN-CDR",
        "band": "precipitation",
        "native_temporal": "daily",
        "conversion": "none",
        "scale_factor": 1.0,
        "units_raw": "mm/day",
        "units_out": "mm/day",
        "type": "satellite",
        "native_res_deg": 0.25,
        "notes": "Aggregation: monthly mean of daily mm/day values.",
    },
    "GPM_IMERG": {
        "collection": "NASA/GPM_L3/IMERG_MONTHLY_V07",
        "band": "precipitation",
        "native_temporal": "monthly",
        "conversion": "scale",
        "scale_factor": 24.0,
        "units_raw": "mm/hr",
        "units_out": "mm/day",
        "type": "satellite_gauge_merged",
        "native_res_deg": 0.1,
        "notes": "mm/day = raw x 24. Available 2000-06 onward.",
    },
    "ERA5_LAND": {
        "collection": "ECMWF/ERA5_LAND/MONTHLY_AGGR",
        "band": "total_precipitation_sum",
        "native_temporal": "monthly",
        "conversion": "era5_monthly",
        "scale_factor": None,
        "units_raw": "m/month",
        "units_out": "mm/day",
        "type": "reanalysis",
        "native_res_deg": 0.1,
        "notes": (
            "mm/day = raw(m) x 1000 / days_in_month. Cannot use a fixed "
            "scale_factor since days-in-month varies (28-31)."
        ),
    },
    "MERRA2": {
        "collection": "NASA/GSFC/MERRA/flx/2",
        "band": "PRECTOTCORR",
        "native_temporal": "hourly",
        "conversion": "scale",
        "scale_factor": 86400.0,
        "units_raw": "kg/m2/s",
        "units_out": "mm/day",
        "type": "reanalysis",
        "native_res_deg": 0.5,
        "notes": (
            "Hourly images pre-aggregated to daily before monthly mean, "
            "to keep the collection size manageable (~7,300 vs ~175,000 "
            "images over 20 years)."
        ),
    },
    "TERRACLIMATE": {
        "collection": "IDAHO_EPSCOR/TERRACLIMATE",
        "band": "pr",
        "native_temporal": "monthly",
        "conversion": "terra_monthly",
        "scale_factor": None,
        "units_raw": "mm/month",
        "units_out": "mm/day",
        "type": "reanalysis_interpolated",
        "native_res_deg": 0.04,
        "notes": "mm/day = raw(mm/month) / days_in_month.",
    },
}

# Full known availability window per product, ingestion.py clips the
# requested [start, end] to this AND to CONFIG dates, so no product is
# ever queried outside its real availability.
DEFAULT_PRODUCT_DATE_RANGES: dict[str, tuple[str, str]] = {
    "CHIRPS": ("1981-01-01", "2024-12-31"),
    "PERSIANN_CDR": ("1983-01-01", "2024-12-31"),
    "GPM_IMERG": ("2000-06-01", "2024-12-31"),
    "ERA5_LAND": ("1950-01-01", "2024-12-31"),
    "MERRA2": ("1980-01-01", "2024-12-31"),
    "TERRACLIMATE": ("1958-01-01", "2023-12-31"),
}


# ════════════════════════════════════════════════════════════
# Validation metrics
# ════════════════════════════════════════════════════════════

DEFAULT_METRICS: dict[str, list[str]] = {
    "continuous": [
        "bias",  # Mean Bias = mean(sim) - mean(obs)          [mm/day]
        "pbias",  # Percent Bias = bias / mean(obs) x 100       [%]
        "mae",  # Mean Absolute Error                         [mm/day]
        "rmse",  # Root Mean Squared Error                     [mm/day]
        "r",  # Pearson correlation coefficient              [-1, 1]
        "r2",  # Coefficient of determination                 [0, 1]
        "nse",  # Nash-Sutcliffe Efficiency                    [-inf, 1]
        "kge",  # Kling-Gupta Efficiency                       [-inf, 1]
    ],
    "categorical": [
        "pod",  # Probability of Detection = H/(H+M)          [0, 1]
        "far",  # False Alarm Ratio        = FA/(H+FA)        [0, 1]
        "csi",  # Critical Success Index   = H/(H+M+FA)       [0, 1]
        "ets",  # Equitable Threat Score (bias-corrected CSI) [0, 1]
        "freq_bias",  # Frequency Bias    = (H+FA)/(H+M)      [>0]
    ],
}

DEFAULT_METRICS_FLAT = DEFAULT_METRICS["continuous"] + DEFAULT_METRICS["categorical"]

# Fixed-bound normalisation ranges used by the *default* product-ranking
# score (see rainfall.decision.score_products). This is the formula
# actually used to produce the reported results and the shipped
# decision-support workbook: each metric is normalised against a fixed
# plausible range rather than the min/max actually observed across
# products in a given zone. A relative (per-zone min-max) normalisation,
# closer to the manuscript's written formula, is available as an
# alternative, see rainfall.decision.score_products(normalization=...).
#
# Tuple shape: (metric_name -> (min, max, invert)). ``invert=True`` means
# lower-is-better (FAR, |PBIAS|) so the normalised score is 1 - fraction.
DEFAULT_NORMALIZATION_BOUNDS: dict[str, tuple[float, float, bool]] = {
    "kge": (-1.0, 1.0, False),
    "r": (0.0, 1.0, False),
    "nse": (-5.0, 1.0, False),
    "pod": (0.0, 1.0, False),
    "far": (0.0, 1.0, True),
    "csi": (0.0, 1.0, False),
    "pbias": (0.0, 60.0, True),  # applied to abs(pbias)
}


# ════════════════════════════════════════════════════════════
# Applications & weights (decision-support scoring)
# ════════════════════════════════════════════════════════════
#
# Metric weights per management application, summing to 1.0 each.
# A user with different applications/priorities passes their own dict
# with this same shape to rainfall.decision.score_products(weights=...).

DEFAULT_APP_WEIGHTS: dict[str, dict[str, float]] = {
    "Fire risk monitoring": {
        "kge": 0.10,
        "r": 0.20,
        "nse": 0.05,
        "pod": 0.15,
        "far": 0.30,
        "csi": 0.15,
        "pbias": 0.05,
    },
    "Wildlife & habitat": {
        "kge": 0.25,
        "r": 0.20,
        "nse": 0.15,
        "pod": 0.15,
        "far": 0.10,
        "csi": 0.10,
        "pbias": 0.05,
    },
    "Drought early warning": {
        "kge": 0.15,
        "r": 0.10,
        "nse": 0.10,
        "pod": 0.30,
        "far": 0.20,
        "csi": 0.10,
        "pbias": 0.05,
    },
    "Flood forecasting": {
        "kge": 0.10,
        "r": 0.10,
        "nse": 0.10,
        "pod": 0.20,
        "far": 0.10,
        "csi": 0.25,
        "pbias": 0.15,
    },
    "Agricultural planning": {
        "kge": 0.20,
        "r": 0.25,
        "nse": 0.15,
        "pod": 0.15,
        "far": 0.10,
        "csi": 0.10,
        "pbias": 0.05,
    },
    "Hydrological modelling": {
        "kge": 0.30,
        "r": 0.20,
        "nse": 0.25,
        "pod": 0.10,
        "far": 0.05,
        "csi": 0.05,
        "pbias": 0.05,
    },
    "Climate trend analysis": {
        "kge": 0.15,
        "r": 0.25,
        "nse": 0.25,
        "pod": 0.10,
        "far": 0.10,
        "csi": 0.10,
        "pbias": 0.05,
    },
}

DEFAULT_APP_FOCUS: dict[str, str] = {
    "Fire risk monitoring": "FAR critical - false rain forecast = unpreparedness",
    "Wildlife & habitat": "KGE + r - habitat depends on magnitude and seasonal pattern",
    "Drought early warning": "POD critical - missed dry spell = missed intervention",
    "Flood forecasting": "CSI + POD - capturing extreme events matters most",
    "Agricultural planning": "r + KGE - seasonal onset and totals equally important",
    "Hydrological modelling": "KGE + NSE - standard water balance benchmarks",
    "Climate trend analysis": "r + NSE - temporal consistency over absolute accuracy",
}

# Zone-level caveats surfaced alongside rankings in the decision tool
# and in rainfall.insights.answer(). Keyed on zone_name; "All West
# Africa" is the pooled-across-zones entry.
DEFAULT_ZONE_NOTES: dict[str, str] = {
    "Saharian": (
        "Hyperarid. Near-zero rainfall makes FAR inherently unstable at any "
        "threshold. Use MERRA-2 or PERSIANN-CDR for best false-alarm "
        "control. Never use absolute PBIAS alone for ranking here."
    ),
    "Sahelian": (
        "Strong unimodal wet season Jul-Sep. Most products perform well - "
        "GPM-IMERG leads on KGE. Threshold choice significantly affects "
        "CSI; report threshold sensitivity in publications."
    ),
    "Soudanian": (
        "Reliable transitional rainfall. CHIRPS and GPM-IMERG consistently "
        "strong. Safe zone for hydrological modelling - NSE and KGE most "
        "meaningful. ERA5-Land good for co-variables."
    ),
    "Guinean": (
        "Bimodal pattern Jun + Oct. Most products overestimate magnitude - "
        "use r and CSI over KGE for ranking. GPM-IMERG best overall. Avoid "
        "TerraClimate for absolute rainfall amounts."
    ),
    "Guineo-Congolean": (
        "High-rainfall equatorial. GPM-IMERG best KGE. TerraClimate "
        "severely overestimates - do not use for water balance. CHIRPS "
        "reliable for wet-dry detection. ERA5-Land weakest."
    ),
    "All West Africa": (
        "Pooled across all stations and zones. Zone-specific selection is "
        "always preferred over the pooled ranking when the zone is known."
    ),
}


# ════════════════════════════════════════════════════════════
# Default gauge network (West Africa, GPCC FDD v2022)
# ════════════════════════════════════════════════════════════
#
# These are the 16 real GPCC station locations used in the manuscript
# validation (not synthetic placeholders). A user validating against a
# different gauge network builds their own stations DataFrame with this
# same shape (station_id, station_name, lon, lat, elevation_m, source)
# and passes it to any savana.rainfall function that accepts
# ``stations_df=``, nothing downstream assumes exactly these 16.

DEFAULT_STATIONS_WA_RAW: list[tuple] = [
    ("WA001", "Dakar", -17.47, 14.73, 27, "GPCC_FDD_v2022"),
    ("WA002", "Bamako", -7.95, 12.65, 381, "GPCC_FDD_v2022"),
    ("WA003", "Ouagadougou", -1.52, 12.36, 306, "GPCC_FDD_v2022"),
    ("WA004", "Niamey", 2.17, 13.51, 222, "GPCC_FDD_v2022"),
    ("WA005", "Abuja", 7.33, 9.07, 476, "GPCC_FDD_v2022"),
    ("WA006", "Accra", -0.17, 5.56, 61, "GPCC_FDD_v2022"),
    ("WA007", "Abidjan", -3.93, 5.35, 7, "GPCC_FDD_v2022"),
    ("WA008", "Conakry", -13.67, 9.53, 27, "GPCC_FDD_v2022"),
    ("WA009", "Freetown", -13.23, 8.49, 27, "GPCC_FDD_v2022"),
    ("WA010", "Monrovia", -10.80, 6.30, 23, "GPCC_FDD_v2022"),
    ("WA011", "Lome", 1.22, 6.13, 25, "GPCC_FDD_v2022"),
    ("WA012", "Cotonou", 2.42, 6.37, 9, "GPCC_FDD_v2022"),
    ("WA013", "Kano", 8.52, 12.05, 481, "GPCC_FDD_v2022"),
    ("WA014", "Kumasi", -1.62, 6.69, 287, "GPCC_FDD_v2022"),
    ("WA015", "Banjul", -16.68, 13.45, 28, "GPCC_FDD_v2022"),
    ("WA016", "Nouakchott", -15.97, 18.07, 4, "GPCC_FDD_v2022"),
]

DEFAULT_STATION_COLUMNS = [
    "station_id",
    "station_name",
    "lon",
    "lat",
    "elevation_m",
    "source",
]

# The author's own pre-extracted GPCC observation table, uploaded once
# to Earth Engine as a FeatureCollection asset so the interactive GEE
# app doesn't need to re-run the NetCDF extraction. It covers ONLY the
# 16 stations above. Using this default with a different stations_df
# will simply return no matches for the extra stations - a user working
# on a different gauge network should either build their own equivalent
# asset (station_id, year, month, obs_mm_day) or use
# ``rainfall.stations.download_gpcc()`` to extract straight from the
# public GPCC NetCDF archive at their own station coordinates.
DEFAULT_GPCC_ASSET_WA = "projects/ee-desmond/assets/gpcc_obs_2001_2020"

# Public GPCC Full Data Daily v2022 archive (used by
# rainfall.stations.download_gpcc() for any station set, anywhere).
GPCC_FDD_BASE_URL = (
    "https://opendata.dwd.de/climate_environment/GPCC/full_data_daily_v2022/"
)


def default_stations_wa():
    """The 16 West Africa GPCC gauge stations, as a pandas.DataFrame.

    This is the manuscript's real validation network, not a synthetic
    placeholder, the default ``stations_df`` used throughout
    ``savana.rainfall`` when no ``stations_df`` is supplied. Any function
    accepting ``stations_df=`` accepts a DataFrame with this same shape
    (station_id, station_name, lon, lat, elevation_m, source) for a
    different gauge network.
    """
    import pandas as pd

    return pd.DataFrame(DEFAULT_STATIONS_WA_RAW, columns=DEFAULT_STATION_COLUMNS)


# ════════════════════════════════════════════════════════════
# Default ecological zones (West Africa, 5-class scheme)
# ════════════════════════════════════════════════════════════
#
# NOT a packaged shapefile, the 5 WA zones are built on demand from 3
# base climatic-zone EE assets via rainfall.zones.build_zones_from_bands()
# (a direct, generalised port of the author's GEE zone-delineation
# script: 3 climatic zones split into 5 ecological zones by intersecting
# with latitude bands). This is just the WA study's *configuration* of
# that generic builder, a different region/scheme is a different
# base_zones dict + zone_defs list passed to the same function; see
# rainfall.zones for the fully generic version, including a
# single-boundary convenience path for a user who just wants one AOI
# with no zone stratification at all.
#
# DEFAULT_ZONE_BASE_ASSETS_WA are the author's own EE table assets,
# usable as-is only within that EE project. Anyone else building the WA
# zones from scratch needs their own uploaded copies of the same 3
# source shapefiles (Sahelian-Desert, Soudanian_dissolved,
# Guinea_dissolved) at their own asset paths, passed as their own
# base_zones dict. Everyone else building zones for a DIFFERENT region
# supplies entirely their own base_zones + zone_defs.
DEFAULT_ZONE_BASE_ASSETS_WA: dict[str, str] = {
    "Sahelian": "projects/ee-desmond/assets/zone_sahelian",
    "Soudanian": "projects/ee-desmond/assets/zone_soudanian",
    "Guinean": "projects/ee-desmond/assets/zone_guinean",
}

# lat_min/lat_max define the latitude band each ecological zone is
# clipped to within its source climatic zone. A zone_def with no
# latitude split at all (lat_min/lat_max spanning the full source
# region) just passes the source zone through unmodified, the pattern
# to use when your own base regions don't need further splitting.
DEFAULT_ZONE_DEFS_WA: list[dict] = [
    {
        "zone_id": 1,
        "zone_name": "Saharian",
        "zone_name_fr": "Zone Saharienne",
        "source_zone": "Sahelian",
        "lat_min": 18.0,
        "lat_max": 30.0,
        "color_hex": "#F5DEB3",
        "rainfall_mm_yr": "<25 mm/yr",
    },
    {
        "zone_id": 2,
        "zone_name": "Sahelian",
        "zone_name_fr": "Zone Sah\u00e9lienne",
        "source_zone": "Sahelian",
        "lat_min": -5.0,
        "lat_max": 18.0,
        "color_hex": "#E8A838",
        "rainfall_mm_yr": "200-600 mm/yr",
    },
    {
        "zone_id": 3,
        "zone_name": "Soudanian",
        "zone_name_fr": "Zone Soudanienne",
        "source_zone": "Soudanian",
        "lat_min": -5.0,
        "lat_max": 30.0,
        "color_hex": "#CC6600",
        "rainfall_mm_yr": "600-1200 mm/yr",
    },
    {
        "zone_id": 4,
        "zone_name": "Guinean",
        "zone_name_fr": "Zone Guin\u00e9enne",
        "source_zone": "Guinean",
        "lat_min": 7.0,
        "lat_max": 30.0,
        "color_hex": "#78C850",
        "rainfall_mm_yr": "1200-2000 mm/yr",
    },
    {
        "zone_id": 5,
        "zone_name": "Guineo-Congolean",
        "zone_name_fr": "Zone Guin\u00e9o-Congolaise",
        "source_zone": "Guinean",
        "lat_min": -5.0,
        "lat_max": 7.0,
        "color_hex": "#1A6B1A",
        "rainfall_mm_yr": ">2000 mm/yr",
    },
]

# West Africa bounding box used to clip latitude bands to a sensible
# extent (matches the GEE script's WA_BOUNDS). A different region uses
# its own bounds, see build_zones_from_bands(bounds=...).
DEFAULT_ZONE_BOUNDS_WA = (
    -20.0,
    -5.0,
    25.0,
    25.0,
)  # (min_lon, min_lat, max_lon, max_lat)

DEFAULT_ZONE_NAME_FIELD = "zone_name"
DEFAULT_ZONE_ASSET_WA = "projects/ee-desmond/assets/ecological_zones_5class"


# ════════════════════════════════════════════════════════════
# Preview map visualisation params (geemap)
# ════════════════════════════════════════════════════════════
#
# Direct port of the GEE app's VIS object, used by
# rainfall.spatial's preview_*_map() functions so a quick look at a
# product's climatology/bias/correlation looks the same whether you're
# in the GEE Code Editor or a Jupyter notebook.
DEFAULT_VIS_PARAMS: dict[str, dict] = {
    "annual": {
        "min": 0,
        "max": 2500,
        "palette": ["#FFFDE7", "#FFF59D", "#FFCC02", "#FF8F00", "#E65100"],
    },
    "daily": {
        "min": 0,
        "max": 12,
        "palette": ["#E3F2FD", "#90CAF9", "#1565C0", "#0D47A1", "#01002E"],
    },
    "bias": {
        "min": -5,
        "max": 5,
        "palette": ["#B71C1C", "#EF9A9A", "#FFFFFF", "#90CAF9", "#0D47A1"],
    },
    "pbias": {
        "min": -80,
        "max": 80,
        "palette": ["#B71C1C", "#FFCDD2", "#FFFFFF", "#BBDEFB", "#0D47A1"],
    },
    "corr": {
        "min": 0,
        "max": 1,
        "palette": ["#FFFFFF", "#C8E6C9", "#66BB6A", "#2E7D32", "#1B5E20"],
    },
    "trend": {
        "min": -0.05,
        "max": 0.05,
        "palette": ["#4E342E", "#FF8A65", "#FFFFFF", "#80DEEA", "#006064"],
    },
    "pod": {
        "min": 0,
        "max": 1,
        "palette": ["#FFF8E1", "#FFE082", "#FFB300", "#FF6F00"],
    },
    "far": {
        "min": 0,
        "max": 1,
        "palette": ["#E8F5E9", "#A5D6A7", "#388E3C", "#1B5E20"],
    },
}
