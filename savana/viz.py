"""Interactive visualization helpers built on geemap/leafmap for Jupyter."""

from __future__ import annotations

from . import config


def show_classified_map(classified_image, region=None, class_info: dict | None = None, m=None, zoom: int = 12):
    """Display a classified land-system image on an interactive geemap.Map."""
    import geemap

    info = class_info or config.DEFAULT_CLASS_INFO
    if m is None:
        m = geemap.Map()
    if region is not None:
        m.centerObject(region, zoom)
    m.add_layer(classified_image, config.class_vis_params(info), "Land System Classification")
    add_legend(m, info)
    return m


def add_legend(m, class_info: dict | None = None, title: str = "Land System Classes"):
    """Add a class legend to a geemap.Map."""
    info = class_info or config.DEFAULT_CLASS_INFO
    legend_dict = {v["name"]: f"#{v['color']}" for v in info.values()}
    m.add_legend(title=title, legend_dict=legend_dict)
    return m


def show_change_map(chg: dict, region=None, m=None, zoom: int = 12):
    """Display conservative/genuine/variable change layers on a geemap.Map."""
    import geemap

    if m is None:
        m = geemap.Map()
    if region is not None:
        m.centerObject(region, zoom)
    m.add_layer(chg["conservative_change"].selfMask(), {"palette": ["8b0000"]}, "Conservative change", True)
    m.add_layer(chg["genuine_change"].selfMask(), {"palette": ["d73027"]}, "Genuine structural change", False)
    m.add_layer(chg["variable_change"].selfMask(), {"palette": ["fc8d59"]}, "Rainfall-driven apparent change", False)
    m.add_layer(
        chg["rue_cv"],
        {"min": 0, "max": 0.3, "palette": ["1a9641", "ffffbf", "d73027"]},
        "RUE coefficient of variation",
        False,
    )
    return m
