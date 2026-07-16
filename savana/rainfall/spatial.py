"""Pixel-wise spatial diagnostics — the scripted counterpart to the
interactive GEE app's on-demand map layers (bias/correlation/trend/
agreement), so those ~20 exploratory analyses produce real exportable
outputs instead of only living as live map interaction.

Every function takes an explicit ``reference`` ImageCollection rather
than assuming GPCC gridded data is available — the manuscript's GPCC
reference is point-station only (see :mod:`.stations`), so by default
these functions compare products *against each other* (inter-product
agreement) or use whichever gridded product you designate as the
reference for a given call.
"""

from __future__ import annotations

from . import config


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
    """Zone-mean bias/trend per product, as a flat table — the scripted
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
    """Pixel-wise CSI at each of several thresholds — spatial counterpart
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
