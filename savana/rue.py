"""Rain Use Efficiency (RUE): integrated NDVI normalised by rainfall.

Tile-boundary bias is removed by normalising integrated NDVI by the
count of valid (cloud-free) months before dividing by annual rainfall.
Direct port of ``rue.js``.
"""

from __future__ import annotations

from . import config


def epoch_rue(year: int, region, cloud_score_threshold: float = 0.65):
    """RUE for a specific epoch year. Returns a single band named ``RUE_{year}``."""
    import ee

    yr = str(year)
    rainfall = (
        ee.ImageCollection(config.CHIRPS_COLLECTION)
        .filter(ee.Filter.date(f"{yr}-01-01", f"{yr}-12-31"))
        .filter(ee.Filter.bounds(region))
        .sum()
        .rename("rainfall")
        .clip(region)
    )
    cs_plus = (
        ee.ImageCollection(config.CLOUD_SCORE_COLLECTION)
        .filter(ee.Filter.date(f"{yr}-01-01", f"{yr}-12-31"))
        .filter(ee.Filter.bounds(region))
    )
    s2 = (
        ee.ImageCollection(config.S2_COLLECTION)
        .filter(ee.Filter.date(f"{yr}-01-01", f"{yr}-12-31"))
        .filter(ee.Filter.bounds(region))
    )
    annual_ndvi = ee.Image(
        ee.Algorithms.If(
            s2.size().gt(0),
            s2.linkCollection(cs_plus, cs_plus.first().bandNames())
            .map(
                lambda img: img.normalizedDifference(["B8", "B4"])
                .rename("NDVI")
                .updateMask(img.select("cs").gte(cloud_score_threshold))
            )
            .mean()
            .rename("NDVI")
            .clip(region),
            ee.Image.constant(0).rename("NDVI").clip(region),
        )
    )
    return (
        annual_ndvi.multiply(1000)
        .divide(rainfall.add(ee.Image.constant(1)))
        .rename(f"RUE_{yr}")
        .clip(region)
    )


def compute_annual(year: int, region, cloud_score_threshold: float = 0.65) -> dict:
    """Full integrated-NDVI / CHIRPS RUE for a training year.

    Returns ``{"chirps": image, "indvi": image, "rue": image}`` where
    ``rue`` is a single band named ``'RUE'`` (used as training feature #14).
    """
    import ee

    yr = str(year)
    chirps = (
        ee.ImageCollection(config.CHIRPS_COLLECTION)
        .filter(ee.Filter.date(f"{yr}-01-01", f"{yr}-12-31"))
        .filter(ee.Filter.bounds(region))
        .sum()
        .clip(region)
        .rename("annual_rainfall_mm")
    )

    months = ee.List.sequence(1, 12)

    def _monthly(m):
        start = ee.Date.fromYMD(year, m, 1)
        end = start.advance(1, "month")
        cs_plus_m = (
            ee.ImageCollection(config.CLOUD_SCORE_COLLECTION)
            .filter(ee.Filter.date(start, end))
            .filter(ee.Filter.bounds(region))
        )
        s2_m = (
            ee.ImageCollection(config.S2_COLLECTION)
            .filter(ee.Filter.date(start, end))
            .filter(ee.Filter.bounds(region))
            .linkCollection(cs_plus_m, cs_plus_m.first().bandNames())
            .map(lambda img: img.updateMask(img.select("cs").gte(cloud_score_threshold)))
        )
        monthly_img = ee.Image(
            ee.Algorithms.If(
                s2_m.size().gt(0),
                s2_m.select(["B8", "B4"])
                .median()
                .normalizedDifference()
                .rename("NDVI")
                .multiply(30),
                ee.Image.constant(0).rename("NDVI").selfMask(),
            )
        )
        return monthly_img.clip(region)

    monthly_ndvi = ee.ImageCollection(months.map(_monthly))
    valid_month_count = monthly_ndvi.count().rename("valid_months")
    indvi = (
        monthly_ndvi.sum().divide(valid_month_count).multiply(12).rename("iNDVI")
    )
    rue = indvi.divide(chirps.add(ee.Image.constant(1))).rename("RUE").clip(region)

    return {"chirps": chirps, "indvi": indvi, "rue": rue}
