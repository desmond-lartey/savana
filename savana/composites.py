"""Sentinel-2, seasonal, percentile, and AlphaEarth embedding composites.

Ported from ``kogyae.js`` Phase 2 (Sentinel-2 reference imagery) and
Phase 3 (AlphaEarth embeddings), and from the year-loop composite logic
in Phase 8 — the standalone ``composites.js`` module you use in
``mainrun.js`` was empty, so this reconstructs it from the working
monolithic script with the exact same signatures ``mainrun.js`` expects
(``getSentinel2Annual``, ``getSeasonalComposite``, ``getPercentileComposites``,
``getEmbeddingImage``), plus a graceful fallback for seasons/years with
sparse Cloud Score+ coverage.
"""

from __future__ import annotations

from . import config


def sentinel2_annual(year: int, region, cloud_score_threshold: float = 0.65):
    """Cloud-masked median Sentinel-2 SR composite for a calendar year.

    Equivalent to ``getSentinel2Composite`` / ``C.getSentinel2Annual``.
    """
    import ee

    start = ee.Date.fromYMD(year, 1, 1)
    end = start.advance(1, "year")
    s2 = (
        ee.ImageCollection(config.S2_COLLECTION)
        .filter(ee.Filter.date(start, end))
        .filter(ee.Filter.bounds(region))
    )
    cs_plus = ee.ImageCollection(config.CLOUD_SCORE_COLLECTION)
    return (
        s2.linkCollection(cs_plus, cs_plus.first().bandNames())
        .map(lambda img: img.updateMask(img.select("cs").gte(cloud_score_threshold)))
        .select("B.*")
        .median()
        .clip(region)
    )


def seasonal_composite(
    start_date: str,
    end_date: str,
    region,
    cloud_score_threshold: float = 0.55,
    cloud_pct_fallback: float = 50,
):
    """Cloud-masked median Sentinel-2 composite for an arbitrary date range.

    Falls back to a simple ``CLOUDY_PIXEL_PERCENTAGE`` filter if Cloud
    Score+ has no coverage for the window, and to a zero-filled image
    if there are no scenes at all (keeps downstream band math from
    failing on sparse early-record years). Equivalent to
    ``getSeasonalComposite`` / ``C.getSeasonalComposite``.
    """
    import ee

    cs_plus = (
        ee.ImageCollection(config.CLOUD_SCORE_COLLECTION)
        .filter(ee.Filter.date(start_date, end_date))
        .filter(ee.Filter.bounds(region))
    )
    s2 = (
        ee.ImageCollection(config.S2_COLLECTION)
        .filter(ee.Filter.date(start_date, end_date))
        .filter(ee.Filter.bounds(region))
    )
    has_scenes = s2.size().gt(0)
    has_cs = cs_plus.size().gt(0)

    with_cs = (
        s2.linkCollection(cs_plus, cs_plus.first().bandNames())
        .map(lambda img: img.updateMask(img.select("cs").gte(cloud_score_threshold)))
        .select("B.*")
        .median()
        .clip(region)
    )
    with_cloud_pct = (
        s2.filter(ee.Filter.lt("CLOUDY_PIXEL_PERCENTAGE", cloud_pct_fallback))
        .select("B.*")
        .median()
        .clip(region)
    )
    empty = (
        ee.Image.constant(0)
        .rename("B8")
        .addBands(ee.Image.constant(0).rename("B4"))
        .addBands(ee.Image.constant(0).rename("B11"))
        .addBands(ee.Image.constant(0).rename("B3"))
        .clip(region)
    )
    return ee.Image(
        ee.Algorithms.If(
            has_scenes,
            ee.Image(ee.Algorithms.If(has_cs, with_cs, with_cloud_pct)),
            empty,
        )
    )


def percentile_composites(
    year: int,
    region,
    percentiles: tuple[int, int] = (10, 90),
    cloud_score_threshold: float = 0.65,
):
    """Per-band percentile composites (default p10/p90) for a calendar year.

    Used to build the seasonal-amplitude / stability indices.
    Equivalent to ``C.getPercentileComposites`` — returns a dict keyed
    ``"p{percentile}"`` (e.g. ``{"p10": image, "p90": image}``).
    """
    import ee

    start = ee.Date.fromYMD(year, 1, 1)
    end = start.advance(1, "year")
    cs_plus = (
        ee.ImageCollection(config.CLOUD_SCORE_COLLECTION)
        .filter(ee.Filter.date(start, end))
        .filter(ee.Filter.bounds(region))
    )
    s2_masked = (
        ee.ImageCollection(config.S2_COLLECTION)
        .filter(ee.Filter.date(start, end))
        .filter(ee.Filter.bounds(region))
        .linkCollection(cs_plus, cs_plus.first().bandNames())
        .map(lambda img: img.updateMask(img.select("cs").gte(cloud_score_threshold)))
        .select("B.*")
    )
    band_names = s2_masked.first().bandNames()
    out = {}
    for p in percentiles:
        img = (
            s2_masked.reduce(ee.Reducer.percentile([p])).rename(band_names).clip(region)
        )
        out[f"p{p}"] = img
    return out


def embedding_image(year: int, region):
    """Annual AlphaEarth satellite embedding image (64 bands: A01..A64).

    Equivalent to ``getEmbeddingImage`` / ``C.getEmbeddingImage``.
    """
    import ee

    start = ee.Date.fromYMD(year, 1, 1)
    end = start.advance(1, "year")
    return (
        ee.ImageCollection(config.EMBEDDING_COLLECTION)
        .filter(ee.Filter.date(start, end))
        .filter(ee.Filter.bounds(region))
        .mosaic()
        .clip(region)
    )
