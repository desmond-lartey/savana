"""Interactive visualization helpers built on geemap/leafmap for Jupyter."""

from __future__ import annotations

from . import config


def show_classified_map(
    classified_image,
    region=None,
    class_info: dict | None = None,
    m=None,
    zoom: int = 12,
):
    """Display a classified land-system image on an interactive geemap.Map."""
    import geemap

    info = class_info or config.DEFAULT_CLASS_INFO
    if m is None:
        m = geemap.Map()
    if region is not None:
        m.centerObject(region, zoom)
    m.add_layer(
        classified_image, config.class_vis_params(info), "Land System Classification"
    )
    add_legend(m, info)
    return m


def show_gcps(
    gcps,
    region=None,
    class_info: dict | None = None,
    class_property: str = config.CLASS_PROPERTY,
    background=None,
    m=None,
    zoom: int = 12,
    point_size: int = 5,
):
    """Display ground control points on a map, colored by assigned class.

    Lets you visually sanity-check the sampling/labelling step — where
    the training points actually landed, and whether their classes look
    spatially sensible — before trusting the classifier trained on them.

    Args:
        gcps: The ``ee.FeatureCollection`` of ground control points
            (e.g. ``clf.gcps``), with ``class_property`` set on each
            feature.
        region: AOI to center the map on (e.g. ``clf.region``).
        class_info: Class scheme (defaults to the standard 6-class one).
        class_property: Property name holding the class code on each
            point (defaults to savana's standard ``"landSystem"``).
        background: Optional ee.Image to show underneath the points
            (e.g. a classified year, or a Sentinel-2 composite) — makes
            it easier to judge whether points look correctly placed.
        m: Existing geemap.Map to add to, or a new one is created.
        point_size: Marker size in pixels.
    """
    import ee
    import geemap

    info = class_info or config.DEFAULT_CLASS_INFO
    if m is None:
        m = geemap.Map()
    if region is not None:
        m.centerObject(region, zoom)

    if background is not None:
        m.add_layer(background, config.class_vis_params(info), "Background", True, 0.6)

    for code, entry in sorted(info.items()):
        class_points = gcps.filter(ee.Filter.eq(class_property, code))
        styled = class_points.style(color=entry["color"], pointSize=point_size)
        m.add_layer(styled, {}, f"GCPs: {entry['name']}")

    add_legend(m, info, title="Ground Control Points")
    return m


def add_legend(m, class_info: dict | None = None, title: str = "Land System Classes"):
    """Add a class legend to a geemap.Map."""
    info = class_info or config.DEFAULT_CLASS_INFO
    legend_dict = {v["name"]: f"#{v['color']}" for v in info.values()}
    m.add_legend(title=title, legend_dict=legend_dict)
    return m


def show_multi_year_map(
    classified_maps: dict,
    years: list[int] | None = None,
    region=None,
    class_info: dict | None = None,
    m=None,
    zoom: int = 12,
):
    """Add every requested epoch as its own toggleable layer on one map.

    Uses geemap's built-in layer panel — each year gets its own checkbox,
    so you can flip between them (or view several at once with opacity
    sliders) without re-running anything.
    """
    import geemap

    info = class_info or config.DEFAULT_CLASS_INFO
    years = sorted(years or classified_maps.keys())
    if m is None:
        m = geemap.Map()
    if region is not None:
        m.centerObject(region, zoom)
    for year in years:
        m.add_layer(
            classified_maps[year], config.class_vis_params(info), f"Land System {year}"
        )
    add_legend(m, info)
    return m


def compare_split_map(
    left,
    right,
    left_label: str = "Left",
    right_label: str = "Right",
    region=None,
    class_info: dict | None = None,
    m=None,
    zoom: int = 12,
):
    """Side-by-side swipe comparison between two layers.

    Each of ``left``/``right`` can be either:
        - an ``ee.Image`` (e.g. a classified year, or ``clf.maps[2019]``) —
          rendered with the land-system palette/legend
        - a basemap name string (e.g. ``"SATELLITE"``, ``"HYBRID"``,
          ``"ROADMAP"``, ``"Esri.WorldImagery"``) — passed straight to geemap

    Drag the handle in the middle of the map to swipe between them —
    this also works for "classified year vs. underlying satellite
    imagery" by passing a basemap name string as one side.
    """
    import ee
    import geemap

    info = class_info or config.DEFAULT_CLASS_INFO

    def _to_layer(side, label):
        if isinstance(side, str):
            return side  # basemap name — geemap resolves this itself
        if isinstance(side, ee.Image):
            return geemap.ee_tile_layer(side, config.class_vis_params(info), label)
        raise TypeError(
            "compare_split_map sides must be an ee.Image or a basemap "
            f"name string, got {type(side)!r}"
        )

    left_layer = _to_layer(left, left_label)
    right_layer = _to_layer(right, right_label)

    if m is None:
        m = geemap.Map()
    if region is not None:
        m.centerObject(region, zoom)

    m.split_map(left_layer=left_layer, right_layer=right_layer)
    return m


def show_change_map(chg: dict, region=None, m=None, zoom: int = 12):
    """Display conservative/genuine/variable change layers on a geemap.Map."""
    import geemap

    if m is None:
        m = geemap.Map()
    if region is not None:
        m.centerObject(region, zoom)
    m.add_layer(
        chg["conservative_change"].selfMask(),
        {"palette": ["8b0000"]},
        "Conservative change",
        True,
    )
    m.add_layer(
        chg["genuine_change"].selfMask(),
        {"palette": ["d73027"]},
        "Genuine structural change",
        False,
    )
    m.add_layer(
        chg["variable_change"].selfMask(),
        {"palette": ["fc8d59"]},
        "Rainfall-driven apparent change",
        False,
    )
    m.add_layer(
        chg["rue_cv"],
        {"min": 0, "max": 0.3, "palette": ["1a9641", "ffffbf", "d73027"]},
        "RUE coefficient of variation",
        False,
    )
    return m
