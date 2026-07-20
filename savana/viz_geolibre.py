"""Display savana classification results inside the GeoLibre Jupyter widget.

GeoLibre (https://geolibre.app, MIT-licensed, by the same author as geoai)
ships a Jupyter-native Python package with a leafmap-style API. This module
is a thin adapter: it converts savana's ``ee.Image`` outputs into XYZ tile
URLs (via Earth Engine's own tile server) that GeoLibre's
``add_tile_layer()`` can display, the same way you'd add any other raster
tile source.

This is intentionally a *lightweight* integration, it depends only on the
public ``geolibre`` PyPI package, versioned and released the same way as
every other savana dependency. It is not a GeoLibre plugin (that would be
TypeScript code living inside GeoLibre's own repo/build system); see the
project roadmap for that as a possible future, separate effort.

Requires: ``pip install "savana[geolibre]"`` (needs Python >= 3.11, since
that is GeoLibre's own minimum, this is stricter than savana's core
Python >= 3.10 requirement).

Known limitation: GeoLibre's swipe/compare tool is currently a UI-only
plugin (Plugins menu > Swipe) with no scriptable Python entry point yet.
Once GeoLibre exposes one, a ``compare_geolibre()`` will be added here to
match ``savana.viz.compare_split_map()``.
"""

from __future__ import annotations

from . import config


def _ee_image_to_tile_url(image, vis_params: dict) -> str:
    """Get an XYZ tile URL template for an ee.Image via Earth Engine's own tile server."""
    map_id_dict = image.getMapId(vis_params)
    return map_id_dict["tile_fetcher"].url_format


def _region_center(region) -> tuple[float, float]:
    """Return (lng, lat) centroid of an ee.Geometry, for GeoLibre's Map(center=...)."""
    lng, lat = region.centroid(maxError=1).coordinates().getInfo()
    return lng, lat


def show_classified_map(
    classified_image,
    region=None,
    class_info: dict | None = None,
    m=None,
    zoom: int = 10,
    layout: str = "embed",
):
    """Display one classified land-system image inside the GeoLibre widget.

    Returns a ``geolibre.Map``, display it in a notebook cell by putting
    it as the last expression, same as any other Jupyter widget.
    """
    from geolibre import Map

    info = class_info or config.DEFAULT_CLASS_INFO
    tile_url = _ee_image_to_tile_url(classified_image, config.class_vis_params(info))

    if m is None:
        if region is not None:
            lng, lat = _region_center(region)
            m = Map(center=(lng, lat), zoom=zoom, layout=layout)
        else:
            m = Map(layout=layout)
    elif region is not None:
        lng, lat = _region_center(region)
        m.set_center(lng, lat, zoom=zoom)

    m.add_tile_layer(tile_url, name="Land System Classification")
    return m


def show_multi_year_map(
    classified_maps: dict,
    years: list[int] | None = None,
    region=None,
    class_info: dict | None = None,
    m=None,
    zoom: int = 10,
    layout: str = "embed",
):
    """Add every requested epoch as its own toggleable tile layer in GeoLibre.

    Each year appears as its own entry in GeoLibre's Layers panel, with its
    own visibility checkbox and opacity slider (the same panel you already
    saw in the app), no extra code needed on your end to toggle between
    them once this cell has run.
    """
    from geolibre import Map

    info = class_info or config.DEFAULT_CLASS_INFO
    years = sorted(years or classified_maps.keys())

    if m is None:
        if region is not None:
            lng, lat = _region_center(region)
            m = Map(center=(lng, lat), zoom=zoom, layout=layout)
        else:
            m = Map(layout=layout)
    elif region is not None:
        lng, lat = _region_center(region)
        m.set_center(lng, lat, zoom=zoom)

    vis_params = config.class_vis_params(info)
    for year in years:
        tile_url = _ee_image_to_tile_url(classified_maps[year], vis_params)
        m.add_tile_layer(tile_url, name=f"Land System {year}")
    return m
