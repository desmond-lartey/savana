"""Point-sample precipitation products at gauge stations, and merge with
observations into the long-format table :mod:`.validation` consumes.

Works for any ``stations_df``, not just the WA 16, extraction is
purely a function of whatever station coordinates you give it.
"""

from __future__ import annotations

from pathlib import Path

from . import config


def extract_product_at_stations(product_ic, stations_df, product_name: str):
    """Point-sample one monthly mm/day ``ee.ImageCollection`` at every
    station in ``stations_df``.

    Returns a long-format ``pandas.DataFrame``:
    ``station_id, year, month, product, sim_mm_day``.
    """
    import ee
    import pandas as pd

    from .stations import stations_to_ee_fc

    fc = stations_to_ee_fc(stations_df)

    def _sample_image(img):
        date = ee.Date(img.get("system:time_start"))
        sampled = img.reduceRegions(
            collection=fc,
            reducer=ee.Reducer.first(),
            scale=config.DEFAULT_TARGET_RESOLUTION_M,
        )
        return sampled.map(
            lambda f: f.set(
                {
                    "year": date.get("year"),
                    "month": date.get("month"),
                }
            )
        )

    sampled_fc = product_ic.map(_sample_image).flatten()
    info = sampled_fc.getInfo()

    rows = []
    for f in info["features"]:
        p = f["properties"]
        rows.append(
            {
                "station_id": p.get("station_id"),
                "year": int(p["year"]),
                "month": int(p["month"]),
                "product": product_name,
                "sim_mm_day": p.get("first"),
            }
        )
    df = pd.DataFrame(rows)
    print(f"  Extracted {product_name}: {len(df):,} station-months")
    return df


def extract_all_products(products_ic: dict, stations_df, cache_dir=None):
    """Extract every product in ``products_ic`` (from
    :func:`savana.rainfall.ingestion.load_all_products`) at every
    station, and stack into one long-format DataFrame.

    Args:
        products_ic: ``{name: ee.ImageCollection}``.
        stations_df: any stations DataFrame.
        cache_dir: if given, each product's extraction is cached to
            ``cache_dir/precip_extraction_<NAME>.csv`` (matching the
            original per-product CSV workflow), a re-run with the same
            ``cache_dir`` reuses whatever's already there instead of
            re-extracting from Earth Engine, and any product missing
            from the cache is extracted and added to it. Delete the
            relevant CSV (or the whole folder) to force a fresh pull.

    Returns:
        Long-format DataFrame: ``station_id, year, month, product,
        sim_mm_day``.
    """
    import pandas as pd

    frames = []
    for name, ic in products_ic.items():
        cache_path = (
            Path(cache_dir) / f"precip_extraction_{name}.csv" if cache_dir else None
        )
        if cache_path is not None and cache_path.exists():
            print(f"  Using cached extraction: {cache_path}")
            frames.append(pd.read_csv(cache_path))
            continue

        df = extract_product_at_stations(ic, stations_df, name)
        if cache_path is not None:
            cache_path.parent.mkdir(parents=True, exist_ok=True)
            df.to_csv(cache_path, index=False)
            print(f"  Cached: {cache_path}")
        frames.append(df)

    return pd.concat(frames, ignore_index=True)


def merge_with_observations(sim_long_df, obs_df, stations_df=None):
    """Merge long-format simulated values with observations, optionally
    attaching station metadata (including ``zone`` if already assigned).

    Args:
        sim_long_df: from :func:`extract_all_products`, columns
            ``station_id, year, month, product, sim_mm_day``.
        obs_df: from :mod:`.stations`, columns
            ``station_id, year, month, obs_mm_day``.
        stations_df: optional, to bring along ``zone`` (from
            :func:`savana.rainfall.zones.assign_zones`) or any other
            station attribute, joined on ``station_id``.

    Returns:
        Long-format DataFrame ready for :mod:`.validation`:
        ``station_id, year, month, product, sim_mm_day, obs_mm_day``
        (+ any joined station columns).
    """
    merged = sim_long_df.merge(obs_df, on=["station_id", "year", "month"], how="inner")

    if stations_df is not None:
        extra_cols = [c for c in stations_df.columns if c != "station_id"]
        merged = merged.merge(
            stations_df[["station_id"] + extra_cols], on="station_id", how="left"
        )

    n_before = len(sim_long_df)
    n_after = len(merged)
    if n_after < n_before:
        print(
            f"  Merge: {n_after:,}/{n_before:,} simulated station-months matched "
            f"an observation ({n_before - n_after:,} unmatched, check obs "
            f"coverage for those station-months)."
        )
    return merged
