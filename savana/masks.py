"""Mutually exclusive land system masks.

Priority order: Anthropogenic -> Riparian -> Core -> Grassland ->
Shrub-Transition -> Open Woodland. Each mask explicitly excludes all
higher-priority classes. Direct port of ``masks.js``.
"""

from __future__ import annotations


def compute(idx: dict, T: dict) -> dict:
    """Compute all 6 land system masks from indices and thresholds.

    Returns ``{"anthro", "riparian", "core", "grass", "shrub", "open"}``.
    """
    mask_anthro = idx["ndbi"].gt(T["ANTHRO_NDBI"]).Or(
        idx["ndvi"].lt(T["ANTHRO_NDVI_MAX"])
    )

    mask_riparian = (
        idx["ndmi"]
        .gt(T["RIPARIAN_NDMI"])
        .And(idx["ndmi_dry"].gt(T["RIPARIAN_NDMI_DRY"]))
        .And(idx["ndvi_dry"].gt(T["RIPARIAN_NDVI_DRY"]))
        .And(mask_anthro.Not())
    )

    mask_core = (
        idx["ndvi_dry"]
        .gt(T["CORE_NDVI_DRY"])
        .And(idx["ndmi"].gt(T["CORE_NDMI"]))
        .And(mask_anthro.Not())
        .And(mask_riparian.Not())
    )

    mask_grass = (
        idx["ndvi_dry"]
        .lt(T["GRASS_NDVI_DRY_MAX"])
        .And(
            idx["ndvi_amp"]
            .gt(T["GRASS_AMP_MIN"])
            .Or(idx["ndmi_dry"].lt(T["GRASS_NDMI_DRY_MAX"]))
        )
        .And(mask_anthro.Not())
        .And(mask_riparian.Not())
        .And(mask_core.Not())
    )

    mask_shrub = (
        idx["ndvi_dry"]
        .gte(T["SHRUB_NDVI_DRY_MIN"])
        .And(idx["ndvi_dry"].lt(T["SHRUB_NDVI_DRY_MAX"]))
        .And(idx["ndmi_dry"].gte(T["SHRUB_NDMI_DRY_MIN"]))
        .And(idx["ndmi_dry"].lt(T["SHRUB_NDMI_DRY_MAX"]))
        .And(idx["ndvi_amp"].gte(T["SHRUB_AMP_MIN"]))
        .And(idx["ndvi_amp"].lt(T["SHRUB_AMP_MAX"]))
        .And(mask_anthro.Not())
        .And(mask_riparian.Not())
        .And(mask_core.Not())
        .And(mask_grass.Not())
    )

    mask_open_dry = (
        idx["ndvi_dry"]
        .gte(T["OPEN_NDVI_DRY_MIN"])
        .And(idx["ndvi_dry"].lt(T["OPEN_NDVI_DRY_MID"]))
        .And(idx["ndmi"].gte(T["OPEN_NDMI_MIN"]))
        .And(idx["ndmi"].lte(T["OPEN_NDMI_SPLIT_HIGH"]))
        .And(mask_anthro.Not())
        .And(mask_riparian.Not())
        .And(mask_core.Not())
        .And(mask_grass.Not())
        .And(mask_shrub.Not())
    )

    mask_open_moist = (
        idx["ndvi_dry"]
        .gte(T["OPEN_NDVI_DRY_MID"])
        .And(idx["ndvi_dry"].lte(T["OPEN_NDVI_DRY_MAX"]))
        .And(idx["ndmi"].gt(T["OPEN_NDMI_SPLIT_LOW"]))
        .And(idx["ndmi"].lte(T["OPEN_NDMI_MAX"]))
        .And(mask_anthro.Not())
        .And(mask_riparian.Not())
        .And(mask_core.Not())
        .And(mask_grass.Not())
        .And(mask_shrub.Not())
    )

    return {
        "anthro": mask_anthro,
        "riparian": mask_riparian,
        "core": mask_core,
        "grass": mask_grass,
        "shrub": mask_shrub,
        "open": mask_open_dry.Or(mask_open_moist),
    }


def coverage(masks: dict, region) -> dict:
    """Fraction of AOI covered by each mask (target range ~0.05-0.30 each)."""
    import ee

    out = {}
    for name, mask in masks.items():
        stats = mask.unmask(0).reduceRegion(
            reducer=ee.Reducer.mean(),
            geometry=region,
            scale=100,
            maxPixels=1e9,
            tileScale=8,
        )
        out[name] = stats
    return out


def add_layers(masks: dict, m=None, class_info: dict | None = None):
    """Add each mask as a layer to a geemap/folium Map (or ``ee.Map`` in Code Editor context).

    ``m`` should be a ``geemap.Map`` instance in a notebook. If omitted,
    a new one is created and returned.
    """
    from . import config

    if m is None:
        import geemap

        m = geemap.Map()

    info = class_info or config.DEFAULT_CLASS_INFO
    color_by_name = {
        "core": info[1]["color"],
        "open": info[2]["color"],
        "shrub": info[3]["color"],
        "grass": info[4]["color"],
        "riparian": info[5]["color"],
        "anthro": info[6]["color"],
    }
    labels = {
        "core": "MASK: Core Woodland",
        "open": "MASK: Open Woodland",
        "shrub": "MASK: Shrub-Transition",
        "grass": "MASK: Grassland",
        "riparian": "MASK: Riparian",
        "anthro": "MASK: Anthropogenic",
    }
    for key in ["core", "open", "shrub", "grass", "riparian", "anthro"]:
        m.addLayer(
            masks[key].selfMask(),
            {"palette": [color_by_name[key]]},
            labels[key],
            False,
        )
    return m
