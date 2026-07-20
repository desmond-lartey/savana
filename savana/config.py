"""Default configuration for savanna landscape classification.

Everything here is a *default*, every public function in the package
accepts overrides, so a user classifying a different savanna system
with a different class scheme is not locked into these values.
"""

from __future__ import annotations

# Property name used to store the class label on training features
# and on the classified output band.
CLASS_PROPERTY = "landSystem"

# Default 6-class land system scheme (Lartey et al., West Africa PA study).
# Keys are integer class codes 1..N; values give display name + hex color
# (no '#' prefix, to match Earth Engine palette conventions).
DEFAULT_CLASS_INFO: dict[int, dict[str, str]] = {
    1: {"name": "Core Woodland", "color": "1a6b1a"},
    2: {"name": "Open Woodland / Tree Savanna", "color": "74c476"},
    3: {"name": "Shrub-Transition Savanna", "color": "c7e9c0"},
    4: {"name": "Grassland Systems", "color": "ffff99"},
    5: {"name": "Riparian / Wetland Vegetation", "color": "4292c6"},
    6: {"name": "Anthropogenic Disturbance", "color": "d73027"},
}

DEFAULT_RANDOM_SEED = 42
DEFAULT_EXPORT_SCALE = 10  # metres
DEFAULT_CRS = "EPSG:32630"
DEFAULT_CONFIDENCE_MARGIN = 0.03
DEFAULT_POINTS_PER_CLASS = 30
DEFAULT_CANDIDATES_PER_CLUSTER = 50
DEFAULT_N_CLUSTERS = 6

# Earth Engine collection IDs used throughout the pipeline.
S2_COLLECTION = "COPERNICUS/S2_SR_HARMONIZED"
CLOUD_SCORE_COLLECTION = "GOOGLE/CLOUD_SCORE_PLUS/V1/S2_HARMONIZED"
EMBEDDING_COLLECTION = "GOOGLE/SATELLITE_EMBEDDING/V1/ANNUAL"
CHIRPS_COLLECTION = "UCSB-CHG/CHIRPS/DAILY"

# AlphaEarth embeddings are only reliably available and dense from this
# year onward for most regions; years before this fall back to the
# embeddings-only model (Model B) instead of embeddings+phenology (Model D).
DEFAULT_PHENOLOGY_MIN_YEAR = 2018


def class_palette(class_info: dict[int, dict[str, str]] | None = None) -> list[str]:
    """Ordered hex palette (by ascending class code) for map visualisation."""
    info = class_info or DEFAULT_CLASS_INFO
    return [info[k]["color"] for k in sorted(info)]


def class_vis_params(class_info: dict[int, dict[str, str]] | None = None) -> dict:
    """Earth Engine visualization params for a classified land-system image."""
    info = class_info or DEFAULT_CLASS_INFO
    keys = sorted(info)
    return {"min": min(keys), "max": max(keys), "palette": class_palette(info)}
