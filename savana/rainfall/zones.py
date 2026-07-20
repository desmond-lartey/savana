"""Ecological/climatic zone construction and station assignment.

No packaged shapefile, zones are *built*, from whatever base regions
and split logic you give :func:`build_zones_from_bands`. This is a
direct, generalised port of the author's GEE zone-delineation script:
3 named base climatic regions, each optionally split by a latitude band
into one or more final ecological zones. The West Africa 5-zone scheme
(:data:`config.DEFAULT_ZONE_DEFS_WA` + :data:`config.DEFAULT_ZONE_BASE_ASSETS_WA`)
is just one *configuration* of this generic builder, not special-cased
logic, a different region, a different number of base regions, or no
latitude splitting at all, all use the same function.

Three ways to get zone geometry, in order of generality:

1. :func:`build_zones_from_bands`, build zones yourself from any named
   base regions (EE assets, or ``ee.FeatureCollection``/``ee.Geometry``
   objects you already have) plus your own split rules. Fully general,
   works for any region, any number of zones, any split logic (or none).
2. :func:`load_zones_from_file`, you already have a zone boundary file
   (shapefile, GeoJSON, GeoPackage, ...) from QGIS or elsewhere. Fully
   general, no Earth Engine involved at all.
3. :func:`single_region_zone`, you don't want zone stratification at
   all, just one study-area boundary. Wraps any boundary (a file path,
   a geojson dict, an ``ee.Geometry``, or a bounding box) into a
   one-zone table so the rest of the package (which only ever asks "is
   this station's zone-name X") doesn't need a special no-zone code path.

:func:`assign_zones` then attaches a zone label to a stations DataFrame
from any of the above, or falls back to a documented latitude-band
heuristic if no zone geometry is available at all.
"""

from __future__ import annotations

from . import config

# ════════════════════════════════════════════════════════════
# Building zones from base regions + latitude-band splits
# ════════════════════════════════════════════════════════════


def _lat_band(
    lat_min: float, lat_max: float, bounds: tuple[float, float, float, float]
):
    """A latitude-band ``ee.Geometry`` clipped to ``bounds``
    (min_lon, min_lat, max_lon, max_lat), port of the GEE script's
    ``latBand()`` helper, generalised to any bounds rather than a
    hardcoded West Africa rectangle.
    """
    import ee

    min_lon, _, max_lon, _ = bounds
    band = ee.Geometry.Rectangle(
        [min_lon, lat_min, max_lon, lat_max], "EPSG:4326", False
    )
    region = ee.Geometry.Rectangle(list(bounds), "EPSG:4326", False)
    return band.intersection(region, ee.ErrorMargin(100))


def build_zones_from_bands(
    base_zones: dict,
    zone_defs: list[dict],
    bounds: tuple[float, float, float, float] | None = None,
):
    """Build a final zones ``ee.FeatureCollection`` from named base
    regions, each optionally split by a latitude band.

    This is the generic version of the GEE script's whole zone-building
    pipeline (its Sections 1, 3, 4), nothing here is specific to West
    Africa or to exactly 3 base regions / 5 output zones.

    Args:
        base_zones: ``{name: source}`` where each ``source`` is an EE
            asset ID (str), an already-loaded ``ee.FeatureCollection``,
            or an ``ee.Geometry``. These are your raw regions before any
            splitting, e.g. ``{"Sahelian": "projects/x/assets/y", ...}``
            for the WA case, or e.g. ``{"my_watershed": my_geometry}``
            for a single custom region.
        zone_defs: list of dicts, each describing one output zone:
            - ``zone_name`` (required): the label written to the
              ``zone_name`` property (or whatever ``config.DEFAULT_ZONE_NAME_FIELD``
              is).
            - ``source_zone`` (required): key into ``base_zones`` this
              output zone is derived from.
            - ``lat_min``, ``lat_max`` (optional): latitude band to
              clip to. Omit both (or span the full region) to pass the
              source region through unmodified, the pattern for "one
              base region = one output zone, no further splitting".
            - any other keys (``zone_id``, ``color_hex``,
              ``rainfall_mm_yr``, notes, ...) are copied through as
              feature properties, same as the GEE script's ZONE_DEFS.
        bounds: ``(min_lon, min_lat, max_lon, max_lat)`` used only to
            clip latitude bands to a sensible extent. Defaults to a
            generous global-ish box if not given, set this to your own
            study area's bounds for anything other than West Africa.

    Returns:
        ``ee.FeatureCollection`` of the final zone polygons, one
        feature per ``zone_defs`` entry, with all of that entry's keys
        as properties.
    """
    import ee

    bounds = bounds or (-180.0, -85.0, 180.0, 85.0)

    loaded_bases = {}
    for name, source in base_zones.items():
        if isinstance(source, str):
            loaded_bases[name] = (
                ee.FeatureCollection(source).geometry().dissolve(ee.ErrorMargin(100))
            )
        elif isinstance(source, ee.FeatureCollection):
            loaded_bases[name] = source.geometry().dissolve(ee.ErrorMargin(100))
        else:  # already an ee.Geometry
            loaded_bases[name] = source

    features = []
    for zdef in zone_defs:
        if "zone_name" not in zdef or "source_zone" not in zdef:
            raise ValueError(
                f"zone_def is missing required key(s): {zdef}. "
                f"Every zone_def needs at least 'zone_name' and 'source_zone'."
            )
        if zdef["source_zone"] not in loaded_bases:
            raise ValueError(
                f"zone_def {zdef['zone_name']!r} references source_zone "
                f"{zdef['source_zone']!r}, not found in base_zones "
                f"({sorted(base_zones)})."
            )

        source_geom = loaded_bases[zdef["source_zone"]]
        lat_min, lat_max = zdef.get("lat_min"), zdef.get("lat_max")
        if lat_min is not None and lat_max is not None:
            band = _lat_band(lat_min, lat_max, bounds)
            geometry = source_geom.intersection(band, ee.ErrorMargin(100))
        else:
            geometry = source_geom

        props = {k: v for k, v in zdef.items() if k not in ("lat_min", "lat_max")}
        features.append(ee.Feature(geometry, props))

    return ee.FeatureCollection(features)


def zone_areas_km2(zones_fc, name_field: str | None = None):
    """Add an ``area_km2`` property to every feature, port of the GEE
    script's area-reporting section. Returns the FeatureCollection with
    the extra property; call ``.getInfo()`` or use
    :func:`zones_fc_to_gdf` to inspect it locally.
    """
    import ee

    name_field = name_field or config.DEFAULT_ZONE_NAME_FIELD

    def _add_area(f):
        area_km2 = f.geometry().area(ee.ErrorMargin(100)).divide(1e6).round()
        return f.set("area_km2", area_km2)

    zones_with_area = zones_fc.map(_add_area)
    info = zones_with_area.select([name_field, "area_km2"]).getInfo()
    for f in info["features"]:
        p = f["properties"]
        print(f"  {p.get(name_field)}: {p.get('area_km2'):,.0f} km2")
    return zones_with_area


def export_zones(
    zones_fc,
    asset_id: str | None = None,
    drive_folder: str | None = None,
    drive_description: str = "ecological_zones",
    file_format: str = "GeoJSON",
):
    """Export a built zones FeatureCollection, port of the GEE script's
    three export buttons (asset / GeoJSON / Shapefile), as background
    ``ee.batch`` tasks rather than a UI panel.

    Args:
        zones_fc: from :func:`build_zones_from_bands` (or any
            ``ee.FeatureCollection``).
        asset_id: if given, submits an ``Export.table.toAsset`` task so
            the zones can be reloaded quickly later via
            ``ee.FeatureCollection(asset_id)`` instead of rebuilding
            from base regions every time.
        drive_folder, drive_description, file_format: if
            ``drive_folder`` is given, submits an
            ``Export.table.toDrive`` task (``file_format`` one of
            ``"GeoJSON"``, ``"SHP"``, ``"CSV"``, ...).

    Returns:
        list of submitted ``ee.batch.Task`` objects (already started,
        check ``task.status()`` for progress, same as any other GEE
        batch export).
    """
    import ee

    tasks = []
    if asset_id:
        task = ee.batch.Export.table.toAsset(
            collection=zones_fc, description=drive_description, assetId=asset_id
        )
        task.start()
        tasks.append(task)
        print(f"  Submitted asset export: {asset_id}")

    if drive_folder:
        task = ee.batch.Export.table.toDrive(
            collection=zones_fc,
            description=drive_description,
            folder=drive_folder,
            fileFormat=file_format,
        )
        task.start()
        tasks.append(task)
        print(f"  Submitted Drive export ({file_format}) to folder {drive_folder!r}")

    if not tasks:
        print("  Nothing submitted, pass asset_id and/or drive_folder.")
    return tasks


def default_wa_zones(bounds=None):
    """Build the West Africa 5-zone scheme from the author's own base
    EE assets (:data:`config.DEFAULT_ZONE_BASE_ASSETS_WA`) using
    :data:`config.DEFAULT_ZONE_DEFS_WA`.

    This is just the WA study's *configuration* of
    :func:`build_zones_from_bands`, call that function directly with
    your own ``base_zones``/``zone_defs`` for a different region.

    Requires the 3 base assets to actually exist and be readable by the
    caller's EE account, they're the author's own uploaded shapefiles,
    not a public dataset. If you're not the author, either ask for read
    access, upload your own copies and pass your own
    ``base_zones`` dict, or use a completely different region's data.
    """
    return build_zones_from_bands(
        config.DEFAULT_ZONE_BASE_ASSETS_WA,
        config.DEFAULT_ZONE_DEFS_WA,
        bounds=bounds or config.DEFAULT_ZONE_BOUNDS_WA,
    )


# ════════════════════════════════════════════════════════════
# A single boundary, no zone stratification at all
# ════════════════════════════════════════════════════════════


def single_region_zone(boundary, zone_name: str = "Study Area"):
    """Wrap one boundary as a one-row zones table, for a user who
    wants a specific area of interest but no zone stratification.

    Args:
        boundary: any of, a local vector file path (shapefile,
            GeoJSON, ...), a GeoJSON-like dict, an ``ee.Geometry``, or
            a ``(min_lon, min_lat, max_lon, max_lat)`` bounding box.
        zone_name: the single zone label everything in ``boundary``
            will be assigned.

    Returns:
        A ``geopandas.GeoDataFrame`` with one row (usable with
        :func:`assign_zones`'s ``zones_gdf=``), unless ``boundary`` is
        an ``ee.Geometry``, in which case an ``ee.FeatureCollection`` is
        returned instead (usable with ``zones_fc=``).
    """
    try:
        import ee

        if isinstance(boundary, ee.Geometry):
            props = {config.DEFAULT_ZONE_NAME_FIELD: zone_name}
            return ee.FeatureCollection([ee.Feature(boundary, props)])
    except ImportError:
        pass  # ee not installed -> boundary can't be an ee.Geometry, fall through

    import geopandas as gpd

    if isinstance(boundary, (str,)):
        gdf = gpd.read_file(boundary)
        geom = gdf.geometry.unary_union
    elif isinstance(boundary, dict):
        from shapely.geometry import shape

        geom = shape(boundary)
    elif isinstance(boundary, (tuple, list)) and len(boundary) == 4:
        from shapely.geometry import box

        geom = box(*boundary)
    else:
        raise ValueError(
            f"Unrecognised boundary type: {type(boundary)}. Expected a file "
            f"path, GeoJSON dict, ee.Geometry, or (min_lon, min_lat, max_lon, "
            f"max_lat) bounding box."
        )

    return gpd.GeoDataFrame(
        {config.DEFAULT_ZONE_NAME_FIELD: [zone_name]}, geometry=[geom], crs="EPSG:4326"
    )


def load_zones_from_file(path):
    """Load your own zone boundaries from any vector file geopandas can
    read (shapefile, GeoJSON, GeoPackage, ...). Fully general, for a
    user who already has zone geometry from QGIS or elsewhere and
    doesn't need :func:`build_zones_from_bands` at all.
    """
    import geopandas as gpd

    return gpd.read_file(path)


def zones_fc_to_gdf(zones_fc, name_field: str | None = None):
    """Pull a (typically small, a handful of zone polygons) EE
    FeatureCollection down to a local ``geopandas.GeoDataFrame``, for
    use with :func:`assign_zones`'s local-join path, or for saving to a
    file yourself.
    """
    import geopandas as gpd
    from shapely.geometry import shape

    info = zones_fc.getInfo()
    rows = [f["properties"] for f in info["features"]]
    geoms = [shape(f["geometry"]) for f in info["features"]]
    return gpd.GeoDataFrame(rows, geometry=geoms, crs="EPSG:4326")


# ════════════════════════════════════════════════════════════
# Assigning zones to stations
# ════════════════════════════════════════════════════════════

# Rough latitude bands, used ONLY when no zone geometry is available at
# all (no base regions to build from, no file, no default). Derived
# from the WA zones' own published rainfall thresholds, this ignores
# longitude entirely and will misclassify stations near zone boundaries
# or far from West Africa. Real zone geometry (built, loaded, or
# single-region) is always preferred; this exists so validate-by-zone
# degrades gracefully rather than failing outright.
_LATITUDE_BAND_FALLBACK = [
    (18.0, float("inf"), "Saharian"),
    (7.0, 18.0, "Sahelian_or_Soudanian"),  # ambiguous without real geometry
    (float("-inf"), 7.0, "Guinean_or_GuineoCongolean"),  # ambiguous
]


def _assign_zone_by_latitude(lat: float) -> str:
    for lo, hi, name in _LATITUDE_BAND_FALLBACK:
        if lo <= lat < hi:
            return name
    return "Unclassified"


def assign_zones(
    stations_df,
    zones_gdf=None,
    zones_fc=None,
    name_field: str | None = None,
    use_default_if_none: bool = False,
):
    """Add a ``zone`` column to ``stations_df``.

    Args:
        stations_df: any DataFrame with ``station_id, lon, lat``.
        zones_gdf: a local ``geopandas.GeoDataFrame`` (from
            :func:`load_zones_from_file`, :func:`single_region_zone`, or
            :func:`zones_fc_to_gdf`), joined locally via geopandas.
        zones_fc: a live ``ee.FeatureCollection`` (from
            :func:`build_zones_from_bands` or :func:`default_wa_zones`)
           , joined via Earth Engine (``filterBounds`` per station), no
            geopandas required.
        name_field: property/column holding the zone name. Defaults to
            :data:`config.DEFAULT_ZONE_NAME_FIELD` (``"zone_name"``).
        use_default_if_none: if True and neither ``zones_gdf`` nor
            ``zones_fc`` is given, attempts :func:`default_wa_zones`,
            only useful if you're the author (or have access to the
            same EE assets). False by default, since that default is
            not portable to other users/regions, pass your own
            ``zones_gdf``/``zones_fc`` instead, or accept the coarse
            latitude fallback.

    Returns:
        Copy of ``stations_df`` with a new ``zone`` column. Any station
        that can't be matched to a real zone polygon falls back to the
        latitude-band heuristic, with a printed warning, this always
        returns a usable ``zone`` column, never leaves it null.
    """
    stations_df = stations_df.copy()
    name_field = name_field or config.DEFAULT_ZONE_NAME_FIELD

    if zones_gdf is None and zones_fc is None and use_default_if_none:
        try:
            zones_fc = default_wa_zones()
        except Exception as exc:  # noqa: BLE001
            print(
                f"  \u26a0  Could not build default WA zones "
                f"({type(exc).__name__}: {exc}). Falling back to latitude "
                f"bands for all stations."
            )

    if zones_fc is not None:
        try:
            import ee

            from .stations import stations_to_ee_fc

            station_fc = stations_to_ee_fc(stations_df)

            def _tag(feature):
                pt = feature.geometry()
                match = zones_fc.filterBounds(pt).first()
                return feature.set(
                    "zone",
                    ee.Algorithms.If(match, ee.Feature(match).get(name_field), None),
                )

            tagged = station_fc.map(_tag).getInfo()
            zone_by_id = {
                f["properties"]["station_id"]: f["properties"].get("zone")
                for f in tagged["features"]
            }
            stations_df["zone"] = stations_df["station_id"].map(zone_by_id)
        except Exception as exc:  # noqa: BLE001
            print(
                f"  \u26a0  EE zone join failed ({type(exc).__name__}: {exc}), "
                f"falling back to latitude bands."
            )
            stations_df["zone"] = None

    elif zones_gdf is not None:
        try:
            import geopandas as gpd
            from shapely.geometry import Point

            pts = gpd.GeoDataFrame(
                stations_df,
                geometry=[Point(xy) for xy in zip(stations_df.lon, stations_df.lat)],
                crs=zones_gdf.crs or "EPSG:4326",
            )
            joined = gpd.sjoin(pts, zones_gdf[[name_field, "geometry"]], how="left")
            stations_df["zone"] = joined[name_field].values
        except ImportError:
            print(
                "  \u26a0  geopandas/shapely not installed, using latitude-band "
                'fallback. Install with `pip install "savana[rainfall]"`.'
            )
            stations_df["zone"] = None
    else:
        stations_df["zone"] = None

    unmatched = stations_df["zone"].isna()
    if unmatched.any():
        ids = stations_df.loc[unmatched, "station_id"].tolist()
        if zones_gdf is not None or zones_fc is not None:
            print(
                f"  \u26a0  {len(ids)} station(s) had no real zone match, using "
                f"latitude fallback: {ids}"
            )
        stations_df.loc[unmatched, "zone"] = stations_df.loc[unmatched, "lat"].apply(
            _assign_zone_by_latitude
        )

    return stations_df
