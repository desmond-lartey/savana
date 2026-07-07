"""Earth Engine session setup and flexible AOI (area-of-interest) loading.

The original GEE script hardcoded a single park asset
(``projects/ee-desmond/assets/NewParkMerged``) and filtered it by name.
This module generalises that so any user can classify *their* study
area, supplied as an Earth Engine asset ID, a GeoJSON/Shapefile path,
a ``geopandas.GeoDataFrame``, or an ``ee.Geometry``/``ee.FeatureCollection``
directly.
"""

from __future__ import annotations

import json
import os
from typing import TYPE_CHECKING, Any

if (
    TYPE_CHECKING
):  # pragma: no cover - only for static analysis/IDE, never imported at runtime
    import ee

_EE_INITIALIZED = False


def initialize(project: str | None = None, force: bool = False) -> None:
    """Initialize the Earth Engine Python API (auth if needed).

    Args:
        project: Google Cloud project registered for Earth Engine use.
            If omitted, uses whatever is already configured for the
            environment (``EARTHENGINE_PROJECT`` env var or prior
            ``ee.Authenticate()`` state).
        force: Re-initialize even if already initialized this session.
    """
    global _EE_INITIALIZED
    import ee

    if _EE_INITIALIZED and not force:
        return

    project = project or os.environ.get("EARTHENGINE_PROJECT")
    try:
        if project:
            ee.Initialize(project=project)
        else:
            ee.Initialize()
    except Exception:
        ee.Authenticate()
        if project:
            ee.Initialize(project=project)
        else:
            ee.Initialize()
    _EE_INITIALIZED = True


def load_aoi(source: Any, name_filter: str | None = None) -> ee.Geometry:
    """Resolve any of several AOI input types into a single ``ee.Geometry``.

    Args:
        source: One of:
            - ``ee.Geometry`` or ``ee.FeatureCollection`` (used directly)
            - str Earth Engine asset ID, e.g. ``"projects/x/assets/parks"``
            - str path to a local GeoJSON / Shapefile / GeoPackage
            - ``geopandas.GeoDataFrame`` / ``geopandas.GeoSeries``
            - dict GeoJSON geometry or feature
        name_filter: If ``source`` resolves to a FeatureCollection with
            multiple features (e.g. a parks database), filter to the
            feature(s) whose ``NAME`` property equals this value before
            dissolving to a single geometry. If the asset uses a
            different property name, filter it yourself beforehand and
            pass an ``ee.Geometry`` instead.

    Returns:
        ee.Geometry: a single (possibly multi-part) dissolved geometry.
    """
    import ee

    initialize()

    if isinstance(source, ee.Geometry):
        return source

    if isinstance(source, ee.FeatureCollection):
        fc = source
        if name_filter is not None:
            fc = fc.filter(ee.Filter.eq("NAME", name_filter))
        return fc.geometry().dissolve(maxError=1)

    if isinstance(source, dict):
        geom = source.get("geometry", source)
        return ee.Geometry(geom)

    if isinstance(source, str):
        # Earth Engine asset IDs don't have file extensions and aren't
        # local paths; anything with a recognised geo file extension
        # (or that exists on disk) is treated as a local vector file.
        _, ext = os.path.splitext(source)
        if os.path.exists(source) or ext.lower() in (
            ".geojson",
            ".json",
            ".shp",
            ".gpkg",
        ):
            return _load_local_vector(source, name_filter)
        # Otherwise assume it's an EE asset ID.
        fc = ee.FeatureCollection(source)
        if name_filter is not None:
            fc = fc.filter(ee.Filter.eq("NAME", name_filter))
        return fc.geometry().dissolve(maxError=1)

    # geopandas GeoDataFrame / GeoSeries duck-typed via __geo_interface__
    if hasattr(source, "__geo_interface__"):
        return _geodataframe_to_ee_geometry(source)

    raise TypeError(
        f"Unsupported AOI source type: {type(source)!r}. Pass an "
        "ee.Geometry, ee.FeatureCollection, EE asset ID string, local "
        "vector file path, or a geopandas GeoDataFrame."
    )


def _load_local_vector(path: str, name_filter: str | None) -> ee.Geometry:
    import ee

    try:
        import geopandas as gpd
    except ImportError as exc:  # pragma: no cover
        raise ImportError(
            "Reading local vector files requires geopandas. "
            "Install with: pip install geopandas"
        ) from exc

    gdf = gpd.read_file(path)
    if name_filter is not None and "NAME" in gdf.columns:
        gdf = gdf[gdf["NAME"] == name_filter]
    if gdf.crs is not None and gdf.crs.to_epsg() != 4326:
        gdf = gdf.to_crs(epsg=4326)
    geo_json = json.loads(gdf.dissolve().geometry.iloc[0:1].to_json())
    geom = geo_json["features"][0]["geometry"]
    return ee.Geometry(geom)


def _geodataframe_to_ee_geometry(gdf: Any) -> ee.Geometry:
    import ee

    try:
        import geopandas as gpd
    except ImportError as exc:  # pragma: no cover
        raise ImportError(
            "This AOI type requires geopandas. Install with: " "pip install geopandas"
        ) from exc

    if isinstance(gdf, gpd.GeoSeries):
        gdf = gpd.GeoDataFrame(geometry=gdf)
    if gdf.crs is not None and gdf.crs.to_epsg() != 4326:
        gdf = gdf.to_crs(epsg=4326)
    dissolved = gdf.dissolve()
    geo_json = json.loads(dissolved.geometry.iloc[0:1].to_json())
    geom = geo_json["features"][0]["geometry"]
    return ee.Geometry(geom)
