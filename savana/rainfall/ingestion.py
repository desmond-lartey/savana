"""Precipitation product ingestion, harmonise any product catalogue to
a common monthly mean mm/day ImageCollection.

Every function accepts a ``products`` dict (see
:data:`savana.rainfall.config.DEFAULT_PRODUCTS` for the required shape)
and a ``roi``, so this works for a different product catalogue or a
different region, not just the WA six-product/study-area default.

Nothing here calls ``ee.Initialize()``, that's the caller's
responsibility (see :mod:`savana.ee_init`, reused as-is), consistent
with the rest of ``savana`` never initialising EE as a side effect of
import.
"""

from __future__ import annotations

from . import config


def build_roi(stations_df=None, bounds=None, buffer_deg: float = 2.0):
    """Build an ``ee.Geometry`` region of interest.

    Args:
        stations_df: if given (and ``bounds`` is None), the ROI is the
            bounding box of the stations plus ``buffer_deg`` on each
            side, works for any station set, anywhere.
        bounds: explicit ``(min_lon, min_lat, max_lon, max_lat)``, takes
            priority over ``stations_df`` if given.
        buffer_deg: degrees of padding added around the station bbox.

    If neither is given, falls back to the West Africa study bounds
    used in the manuscript (5-25N, 20W-15E).
    """
    import ee

    if bounds is not None:
        min_lon, min_lat, max_lon, max_lat = bounds
    elif stations_df is not None and len(stations_df) > 0:
        min_lon = float(stations_df.lon.min()) - buffer_deg
        max_lon = float(stations_df.lon.max()) + buffer_deg
        min_lat = float(stations_df.lat.min()) - buffer_deg
        max_lat = float(stations_df.lat.max()) + buffer_deg
    else:
        min_lon, min_lat, max_lon, max_lat = (-20.0, 5.0, 15.0, 25.0)

    return ee.Geometry.Rectangle([min_lon, min_lat, max_lon, max_lat])


def _days_in_month(date_str: str) -> int:
    import calendar
    from datetime import datetime

    d = datetime.strptime(date_str, "%Y-%m-%d")
    return calendar.monthrange(d.year, d.month)[1]


def _clip_dates(name: str, start: str, end: str, products: dict) -> tuple[str, str]:
    avail_start, avail_end = config.DEFAULT_PRODUCT_DATE_RANGES.get(name, (start, end))
    clipped_start = max(start, avail_start)
    clipped_end = min(end, avail_end)
    if clipped_start > clipped_end:
        raise ValueError(
            f"{name}: requested window [{start}, {end}] does not overlap "
            f"its availability [{avail_start}, {avail_end}]."
        )
    return clipped_start, clipped_end


def _monthly_from_daily(ic, band, roi, start, end):
    import ee

    months = ee.List.sequence(
        0, ee.Date(end).difference(ee.Date(start), "month").subtract(1)
    )

    def _month_mean(m):
        d0 = ee.Date(start).advance(m, "month")
        d1 = d0.advance(1, "month")
        img = ic.filterDate(d0, d1).select(band).mean().rename("precip_mm_day")
        return img.set("system:time_start", d0.millis())

    return ee.ImageCollection(months.map(_month_mean)).filterBounds(roi)


def _load_scale(name, spec, roi, start, end):
    import ee

    ic = ee.ImageCollection(spec["collection"]).filterDate(start, end).filterBounds(roi)
    if spec["native_temporal"] == "monthly":
        return ic.select(spec["band"]).map(
            lambda img: img.multiply(spec["scale_factor"])
            .rename("precip_mm_day")
            .copyProperties(img, ["system:time_start"])
        )
    # daily -> monthly mean
    ic_scaled = ic.select(spec["band"]).map(
        lambda img: img.multiply(spec["scale_factor"])
        .rename("precip_mm_day")
        .copyProperties(img, ["system:time_start"])
    )
    return _monthly_from_daily(ic_scaled, "precip_mm_day", roi, start, end)


def _load_hourly_to_monthly(name, spec, roi, start, end):
    """MERRA-2: pre-aggregate hourly -> daily before the monthly mean, to
    keep the intermediate collection size manageable (~7,300 vs ~175,000
    images over 20 years). This is the workaround for GEE's per-request
    compute/timeout limits, kept as the permanent code path (not a
    one-off historical fix), per confirmed direction.
    """
    import ee

    ic = ee.ImageCollection(spec["collection"]).filterDate(start, end).filterBounds(roi)
    days = ee.List.sequence(
        0, ee.Date(end).difference(ee.Date(start), "day").subtract(1)
    )

    def _day_mean(d):
        d0 = ee.Date(start).advance(d, "day")
        d1 = d0.advance(1, "day")
        img = (
            ic.filterDate(d0, d1)
            .select(spec["band"])
            .mean()
            .multiply(spec["scale_factor"])
            .rename("precip_mm_day")
        )
        return img.set("system:time_start", d0.millis())

    daily_ic = ee.ImageCollection(days.map(_day_mean))
    return _monthly_from_daily(daily_ic, "precip_mm_day", roi, start, end)


def _load_era5_monthly(name, spec, roi, start, end):
    import ee

    ic = ee.ImageCollection(spec["collection"]).filterDate(start, end).filterBounds(roi)

    def _convert(img):
        date = ee.Date(img.get("system:time_start"))
        days = date.advance(1, "month").difference(date, "day")
        mm_day = (
            img.select(spec["band"]).multiply(1000).divide(days).rename("precip_mm_day")
        )
        return mm_day.copyProperties(img, ["system:time_start"])

    return ic.map(_convert)


def _load_terra_monthly(name, spec, roi, start, end):
    import ee

    ic = ee.ImageCollection(spec["collection"]).filterDate(start, end).filterBounds(roi)

    def _convert(img):
        date = ee.Date(img.get("system:time_start"))
        days = date.advance(1, "month").difference(date, "day")
        mm_day = img.select(spec["band"]).divide(days).rename("precip_mm_day")
        return mm_day.copyProperties(img, ["system:time_start"])

    return ic.map(_convert)


_LOADERS = {
    "none": _load_scale,
    "scale": _load_scale,
    "era5_monthly": _load_era5_monthly,
    "terra_monthly": _load_terra_monthly,
}


def load_product(name: str, start: str, end: str, roi, products: dict | None = None):
    """Load one precipitation product as a monthly mean mm/day
    ``ee.ImageCollection``, dispatched by its ``conversion`` type.

    Args:
        name: key into ``products`` (default
            :data:`config.DEFAULT_PRODUCTS`).
        start, end: 'YYYY-MM-DD', clipped to the product's real
            availability window (see
            :data:`config.DEFAULT_PRODUCT_DATE_RANGES`).
        roi: ``ee.Geometry`` (see :func:`build_roi`).
        products: catalogue dict. Bring your own for a different
            product set, must have the shape of
            :data:`config.DEFAULT_PRODUCTS`.
    """
    products = products if products is not None else config.DEFAULT_PRODUCTS
    if name not in products:
        raise ValueError(f"Unknown product {name!r}. Known: {sorted(products)}")

    spec = products[name]
    clipped_start, clipped_end = _clip_dates(name, start, end, products)

    if spec["native_temporal"] == "hourly":
        return _load_hourly_to_monthly(name, spec, roi, clipped_start, clipped_end)

    loader = _LOADERS.get(spec["conversion"])
    if loader is None:
        raise ValueError(f"{name}: unknown conversion type {spec['conversion']!r}")
    return loader(name, spec, roi, clipped_start, clipped_end)


def load_all_products(
    start: str, end: str, roi=None, products: dict | None = None, stations_df=None
):
    """Load every product in ``products`` (default: all 6) as monthly
    mm/day ImageCollections.

    Returns ``{product_name: ee.ImageCollection}``. ``roi`` defaults to
    :func:`build_roi` from ``stations_df`` if not given.
    """
    products = products if products is not None else config.DEFAULT_PRODUCTS
    if roi is None:
        roi = build_roi(stations_df)

    out = {}
    for name in products:
        print(f"  Loading {name} ...")
        out[name] = load_product(name, start, end, roi, products)
    return out


# ════════════════════════════════════════════════════════════
# MERRA-2 yearly-asset export/reload, permanent workaround for GEE
# per-request timeouts on the full hourly->daily->monthly chain.
# ════════════════════════════════════════════════════════════


def export_merra2_yearly_assets(
    years: list[int], roi, asset_folder: str, products: dict | None = None
):
    """Export one daily-aggregated MERRA-2 asset per year to
    ``asset_folder``, as a background EE batch task per year.

    Splitting the export by year keeps each task well under GEE's
    per-request compute/timeout limits. Returns the list of submitted
    ``ee.batch.Task`` objects, check ``task.status()`` for progress;
    this can take hours for a full 20-year run and is meant to be
    fire-and-forget, not awaited synchronously.
    """
    import ee

    products = products if products is not None else config.DEFAULT_PRODUCTS
    spec = products["MERRA2"]
    tasks = []
    for year in years:
        start, end = f"{year}-01-01", f"{year + 1}-01-01"
        ic = (
            ee.ImageCollection(spec["collection"])
            .filterDate(start, end)
            .filterBounds(roi)
        )
        days = ee.List.sequence(
            0, ee.Date(end).difference(ee.Date(start), "day").subtract(1)
        )

        def _day_mean(d, _ic=ic, _spec=spec, _start=start):
            d0 = ee.Date(_start).advance(d, "day")
            d1 = d0.advance(1, "day")
            img = (
                _ic.filterDate(d0, d1)
                .select(_spec["band"])
                .mean()
                .multiply(_spec["scale_factor"])
                .rename("precip_mm_day")
            )
            return img.set("system:time_start", d0.millis())

        daily_stack = ee.ImageCollection(days.map(_day_mean)).toBands()
        asset_id = f"{asset_folder}/merra2_daily_{year}"
        task = ee.batch.Export.image.toAsset(
            image=daily_stack,
            description=f"merra2_daily_{year}",
            assetId=asset_id,
            region=roi,
            scale=config.DEFAULT_TARGET_RESOLUTION_M,
            maxPixels=1e10,
        )
        task.start()
        tasks.append(task)
        print(f"  Submitted export task: {asset_id}")
    return tasks


def load_merra2_from_assets(asset_folder: str, start: str, end: str, roi):
    """Rebuild the monthly mm/day MERRA-2 ImageCollection from
    pre-exported yearly daily-aggregate assets (see
    :func:`export_merra2_yearly_assets`).
    """
    import ee

    start_year = int(start[:4])
    end_year = int(end[:4])
    daily_images = []
    for year in range(start_year, end_year + 1):
        asset_id = f"{asset_folder}/merra2_daily_{year}"
        try:
            stack = ee.Image(asset_id)
        except Exception as exc:  # noqa: BLE001
            print(f"  \u26a0  Missing MERRA-2 asset for {year}: {exc}")
            continue
        band_names = stack.bandNames()
        n_bands = band_names.size().getInfo()
        for i in range(n_bands):
            band = ee.String(band_names.get(i))
            day_offset = ee.Number.parse(band.slice(0, band.index("_")))
            date = ee.Date(f"{year}-01-01").advance(day_offset, "day")
            img = (
                stack.select([band])
                .rename("precip_mm_day")
                .set("system:time_start", date.millis())
            )
            daily_images.append(img)

    daily_ic = ee.ImageCollection(daily_images)
    return _monthly_from_daily(daily_ic, "precip_mm_day", roi, start, end)
