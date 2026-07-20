"""Pixel-wise spatial diagnostics, the scripted counterpart to the
interactive GEE app's on-demand map layers (bias/correlation/trend/
agreement), so those ~20 exploratory analyses produce real exportable
outputs instead of only living as live map interaction.

Every function takes an explicit ``reference`` ImageCollection rather
than assuming GPCC gridded data is available, the manuscript's GPCC
reference is point-station only (see :mod:`.stations`), so by default
these functions compare products *against each other* (inter-product
agreement) or use whichever gridded product you designate as the
reference for a given call.
"""

from __future__ import annotations

from . import config


def _bin_color(value: float, vis: dict) -> str:
    """Pick a palette color for ``value`` using the same min/max/palette
    as a raster's vis params, so a station marker's fill color lands on
    the same visual scale as the raster underneath it. Simple linear
    binning, not a true continuous ramp, but enough to eyeball agreement
    at a glance.
    """
    lo, hi, palette = vis["min"], vis["max"], vis["palette"]
    if hi == lo:
        return palette[0]
    frac = max(0.0, min(1.0, (value - lo) / (hi - lo)))
    idx = min(len(palette) - 1, int(frac * len(palette)))
    return palette[idx].lstrip("#")


def preview_mean_map(
    product_ic,
    product_name: str = "",
    region=None,
    kind: str = "daily",
    m=None,
    obs_df=None,
    stations_df=None,
):
    """A quick look at one product's long-term mean rainfall on an
    interactive map, before running any validation, just "does this
    product's spatial pattern look sane over my area?"

    Direct port of the GEE app's Annual Total / Mean Daily Rate map
    buttons.

    Args:
        product_ic: a monthly mm/day ``ee.ImageCollection`` (from
            :func:`savana.rainfall.ingestion.load_product`).
        product_name: label for the map layer.
        region: clip to this ``ee.Geometry`` if given.
        kind: ``"daily"`` (mm/day, default) or ``"annual"`` (mm/yr,
            mean daily rate x 365.25), selects which
            :data:`config.DEFAULT_VIS_PARAMS` entry is used.
        m: an existing ``geemap.Map`` to add to, or a new one is created.
        obs_df, stations_df: if BOTH given, overlays real GPCC station
            values as colored markers on top of the raster, NOT a
            rasterized/interpolated GPCC surface (GPCC stays point data
            throughout this package), just each gauge's true mean
            observed value, plotted at its real location, colored on the
            same scale as the raster underneath it, so you can eyeball
            whether the raster's color at a station roughly matches that
            station's actual marker color. Click a marker (with geemap's
            Inspector tool active) to see both the exact GPCC value and
            the raster's pixel value at that same point side by side.

    Returns:
        The ``geemap.Map`` with the mean layer added (and the GPCC
        overlay, if requested).
    """
    import geemap

    if kind not in ("daily", "annual"):
        raise ValueError(f"kind must be 'daily' or 'annual', got {kind!r}")

    mean_img = product_ic.select("precip_mm_day").mean()
    if kind == "annual":
        mean_img = mean_img.multiply(365.25)
    if region is not None:
        mean_img = mean_img.clip(region)

    if m is None:
        m = geemap.Map()
        if region is not None:
            m.centerObject(region, 6)

    vis = config.DEFAULT_VIS_PARAMS[kind]
    label = f"{'Annual Total' if kind == 'annual' else 'Mean Daily'}, {product_name}"
    m.add_layer(mean_img, vis, label)

    if obs_df is not None and stations_df is not None:
        _add_gpcc_overlay(m, obs_df, stations_df, vis, kind)

    return m


def _add_gpcc_overlay(m, obs_df, stations_df, vis, kind):
    import ee

    mean_obs = obs_df.groupby("station_id")["obs_mm_day"].mean().reset_index()
    pts = stations_df.merge(mean_obs, on="station_id", how="inner")
    if pts.empty:
        print(
            "  \u26a0  No stations in stations_df have matching obs_df rows, "
            "no GPCC overlay added."
        )
        return

    scale = 365.25 if kind == "annual" else 1.0
    unit = "mm/yr" if kind == "annual" else "mm/day"

    for r in pts.itertuples():
        value = float(r.obs_mm_day) * scale
        color = _bin_color(value, vis)
        feat = ee.FeatureCollection(
            [
                ee.Feature(
                    ee.Geometry.Point([float(r.lon), float(r.lat)]),
                    {"station_id": r.station_id, f"gpcc_{kind}": round(value, 2)},
                )
            ]
        )
        m.add_layer(
            feat.style(
                **{"color": "000000", "fillColor": color, "pointSize": 9, "width": 2}
            ),
            {},
            f"GPCC: {r.station_id} ({value:.1f} {unit})",
        )


def preview_bias_map(
    product_ic, reference_ic, product_name="", reference_name="", region=None, m=None
):
    """A quick INTER-PRODUCT bias map (product minus another gridded
    product), before running formal validation, "roughly where do
    these two products disagree spatially?" Direct port of the GEE
    app's Bias Map button.

    IMPORTANT: this is product vs. product, never product vs. GPCC.
    GPCC exists in this package only as point gauge observations (see
    :mod:`.stations`), there's no gridded GPCC raster to difference a
    product against pixel-by-pixel. For the actual "does this product
    agree with real GPCC ground truth" spatial check, use
    :func:`preview_station_bias_map` instead, which plots true bias at
    each gauge location. This function is for a different, valid
    question, "how much do CHIRPS and GPM-IMERG disagree with each
    other spatially", not a validation check.

    Args:
        product_ic, reference_ic: monthly mm/day ImageCollections (both
            gridded products, neither is GPCC).
        product_name, reference_name: labels for the map layers.
        region: clip to this ``ee.Geometry`` if given.
        m: an existing ``geemap.Map`` to add to, or a new one is created.

    Returns:
        The ``geemap.Map`` with bias and percent-bias layers added.
    """
    import geemap

    prod_mean = product_ic.select("precip_mm_day").mean()
    ref_mean = reference_ic.select("precip_mm_day").mean()
    bias = prod_mean.subtract(ref_mean).rename("bias_mm_day")
    pbias = (
        prod_mean.subtract(ref_mean)
        .divide(ref_mean.add(1e-6))
        .multiply(100)
        .clamp(-80, 80)
        .rename("pbias_pct")
    )
    if region is not None:
        bias, pbias = bias.clip(region), pbias.clip(region)

    if m is None:
        m = geemap.Map()
        if region is not None:
            m.centerObject(region, 6)

    suffix = f"{product_name} vs {reference_name}" if product_name else "Bias"
    m.add_layer(bias, config.DEFAULT_VIS_PARAMS["bias"], f"Bias (mm/d), {suffix}")
    m.add_layer(pbias, config.DEFAULT_VIS_PARAMS["pbias"], f"% Bias, {suffix}")
    return m


def preview_station_bias_map(merged_df, product: str, m=None, zoom: int = 5):
    """Per-station mean bias against REAL GPCC observations, plotted as
    colored markers, the spatial check that's actually anchored to
    ground truth, unlike :func:`preview_bias_map` (which can only ever
    compare two gridded products against each other, since GPCC has no
    gridded form in this package).

    Args:
        merged_df: long-format obs/sim table with station coordinates
            already joined in, i.e. from
            :func:`savana.rainfall.extraction.merge_with_observations`
            called with ``stations_df=`` (which
            :meth:`savana.rainfall.pipeline.RainfallAssessment.merge`
            always does), so ``lon``/``lat`` columns are present.
        product: which product's bias to show.
        m: an existing ``geemap.Map`` to add to, or a new one is created.

    Returns:
        A ``geemap.Map`` with one marker per station, blue if that
        product overestimates GPCC there, red if it underestimates.
        Click a marker to see the exact bias value.
    """
    import ee
    import geemap

    sub = merged_df[merged_df["product"] == product]
    if sub.empty:
        raise ValueError(f"No rows for product={product!r} in merged_df.")
    missing = {"lon", "lat"} - set(sub.columns)
    if missing:
        raise ValueError(
            f"merged_df is missing {sorted(missing)}, station coordinates "
            f"weren't joined in. Call merge_with_observations(..., "
            f"stations_df=your_stations_df), or just use "
            f"RainfallAssessment.merge(), which does this automatically."
        )

    per_station = (
        sub.assign(_bias=sub["sim_mm_day"] - sub["obs_mm_day"])
        .groupby(["station_id", "lon", "lat"], as_index=False)["_bias"]
        .mean()
        .rename(columns={"_bias": "bias_mm_day"})
    )

    if m is None:
        m = geemap.Map()
        m.set_center(float(per_station.lon.mean()), float(per_station.lat.mean()), zoom)

    features = [
        ee.Feature(
            ee.Geometry.Point([float(r.lon), float(r.lat)]),
            {"station_id": r.station_id, "bias_mm_day": round(float(r.bias_mm_day), 3)},
        )
        for r in per_station.itertuples()
    ]
    fc = ee.FeatureCollection(features)
    over = fc.filter(ee.Filter.gte("bias_mm_day", 0))
    under = fc.filter(ee.Filter.lt("bias_mm_day", 0))
    m.add_layer(
        over.style(**{"color": "0D47A1", "pointSize": 8}),
        {},
        f"{product} overestimates GPCC",
    )
    m.add_layer(
        under.style(**{"color": "B71C1C", "pointSize": 8}),
        {},
        f"{product} underestimates GPCC",
    )
    return m


def bias_map(product_ic, reference_ic):
    """Mean pixel-wise bias (product - reference) over the full period,
    in mm/day.
    """
    p_mean = product_ic.select("precip_mm_day").mean().rename("product_mean")
    r_mean = reference_ic.select("precip_mm_day").mean().rename("reference_mean")
    return p_mean.subtract(r_mean).rename("bias_mm_day")


def correlation_map(product_ic, reference_ic):
    """Pixel-wise Pearson correlation between two monthly ImageCollections
    over the full period, via ``ee.Reducer.pearsonsCorrelation`` on a
    time-matched image pair stack.
    """
    import ee

    def _pair(img):
        date = img.get("system:time_start")
        match = reference_ic.filter(ee.Filter.eq("system:time_start", date)).first()
        return (
            img.select("precip_mm_day")
            .rename("product")
            .addBands(ee.Image(match).select("precip_mm_day").rename("reference"))
            .set("system:time_start", date)
        )

    paired = product_ic.map(_pair)
    corr = paired.select(["product", "reference"]).reduce(
        ee.Reducer.pearsonsCorrelation()
    )
    return corr.select("correlation").rename("r")


def trend_map(product_ic, unit: str = "mm/day/year"):
    """Pixel-wise linear trend over time via
    ``ee.Reducer.linearFit`` (time in years since first image).
    """
    import ee

    first_date = ee.Date(product_ic.first().get("system:time_start"))

    def _add_time_band(img):
        t = ee.Date(img.get("system:time_start")).difference(first_date, "year")
        return img.addBands(ee.Image.constant(t).rename("t").float())

    stacked = product_ic.map(_add_time_band).select(["t", "precip_mm_day"])
    fit = stacked.reduce(ee.Reducer.linearFit())
    slope = fit.select("scale").rename(f"trend_{unit.replace('/', '_')}")
    return slope


def agreement_map(products_ic: dict):
    """Inter-product agreement: pixel-wise standard deviation across all
    products' mean-period image, normalised by the ensemble mean
    (coefficient of variation). Low CV = products agree spatially.
    """
    import ee

    means = [ic.select("precip_mm_day").mean() for ic in products_ic.values()]
    stack = ee.ImageCollection(means)
    mean_img = stack.mean().rename("ensemble_mean")
    std_img = stack.reduce(ee.Reducer.stdDev()).rename("ensemble_std")
    cv = std_img.divide(mean_img.max(0.01)).rename("agreement_cv")
    return mean_img, std_img, cv


def zonal_rank_table(
    products_ic: dict, zones_gdf, reference_ic=None, name_field: str | None = None
):
    """Zone-mean bias/trend per product, as a flat table, the scripted
    counterpart to the GEE app's zonal-ranking map layer.

    Requires ``zones_gdf`` (see
    :func:`savana.rainfall.zones.default_zones_wa`). If ``reference_ic``
    is given, also includes zone-mean bias against it.
    """
    import ee
    import pandas as pd

    name_field = name_field or config.DEFAULT_ZONE_NAME_FIELD
    zones_fc = ee.FeatureCollection(
        [
            ee.Feature(ee.Geometry(g.__geo_interface__), {name_field: n})
            for g, n in zip(zones_gdf.geometry, zones_gdf[name_field])
        ]
    )

    rows = []
    for name, ic in products_ic.items():
        mean_img = ic.select("precip_mm_day").mean().rename("mean_mm_day")
        trend_img = trend_map(ic)
        bands = mean_img.addBands(trend_img)
        if reference_ic is not None:
            bands = bands.addBands(bias_map(ic, reference_ic))

        stats = bands.reduceRegions(
            collection=zones_fc,
            reducer=ee.Reducer.mean(),
            scale=config.DEFAULT_TARGET_RESOLUTION_M,
        ).getInfo()

        for f in stats["features"]:
            p = f["properties"]
            row = {"product": name, "zone": p.get(name_field)}
            row.update({k: v for k, v in p.items() if k not in (name_field,)})
            rows.append(row)

    return pd.DataFrame(rows)


def threshold_sensitivity_map(
    product_ic, reference_ic, thresholds: list[float] | None = None
):
    """Pixel-wise CSI at each of several thresholds, spatial counterpart
    to :func:`savana.rainfall.thresholds.threshold_sensitivity`.

    Returns ``{threshold: ee.Image}`` of pixel-wise CSI.
    """
    import ee

    thresholds = (
        thresholds if thresholds is not None else config.DEFAULT_THRESHOLD_SWEEP_MM_DAY
    )
    out = {}
    for tau in thresholds:

        def _pair(img, _tau=tau):
            date = img.get("system:time_start")
            match = ee.Image(
                reference_ic.filter(ee.Filter.eq("system:time_start", date)).first()
            )
            obs_wet = match.select("precip_mm_day").gte(_tau)
            sim_wet = img.select("precip_mm_day").gte(_tau)
            hit = obs_wet.And(sim_wet).rename("hit")
            miss = obs_wet.And(sim_wet.Not()).rename("miss")
            fa = obs_wet.Not().And(sim_wet).rename("fa")
            return hit.addBands([miss, fa]).set("system:time_start", date)

        counts = product_ic.map(_pair).select(["hit", "miss", "fa"]).sum()
        csi = (
            counts.select("hit")
            .divide(
                counts.select("hit")
                .add(counts.select("miss"))
                .add(counts.select("fa"))
                .max(1)
            )
            .rename("csi")
        )
        out[tau] = csi
    return out
