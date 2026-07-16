"""Gauge station metadata and precipitation observation loading.

Every function here works on an arbitrary ``stations_df`` — a
``pandas.DataFrame`` with at minimum ``station_id, lon, lat`` columns
(``station_name``, ``elevation_m``, ``source`` are recommended but not
required). ``savana.rainfall.config.default_stations_wa()`` supplies the
16-station West Africa GPCC network as a convenient default so the
package works out of the box, but nothing here assumes those specific
stations. Point this module at your own gauge network by building a
DataFrame in that shape and passing it as ``stations_df=`` throughout.

Four ways to get observations, in increasing order of "how much can
this handle a station set that isn't the WA 16":

1. :func:`load_stations_from_csv` — you already have your own
   station metadata + observation CSVs. Fully general.
2. :func:`download_gpcc` — downloads the public GPCC Full Data Daily
   v2022 archive and extracts at whatever station coordinates you
   give it. Fully general, works for any station anywhere GPCC has
   coverage, but downloads ~440 MB and is slow the first time.
3. :func:`load_gpcc_obs_from_asset` — fast, but only returns rows for
   station_ids that exist in the given EE table asset. The packaged
   default asset (:data:`config.DEFAULT_GPCC_ASSET_WA`) covers only the
   16 WA stations; point ``asset_id`` at your own pre-extracted table
   for a different network, or use option 1/2 instead.
4. :func:`generate_demo_observations` — synthetic placeholder data for
   quick testing/tutorials only. Never used silently; you have to ask
   for it explicitly via ``source="demo"`` in :func:`get_observations`.
"""

from __future__ import annotations

from pathlib import Path

from . import config

REQUIRED_STATION_COLUMNS = {"station_id", "lon", "lat"}
REQUIRED_OBS_COLUMNS = {"station_id", "year", "month", "obs_mm_day"}


def load_stations_any(stations=None):
    """Turn almost anything describing station locations into a proper
    ``stations_df`` — the single entry point every high-level function
    (:func:`savana.rainfall.pipeline.validate_against_gpcc`) uses so a
    user never has to hand-build a DataFrame just to try one station.

    Accepts:
        - ``None`` -> :func:`savana.rainfall.config.default_stations_wa`
          (the 16 WA GPCC stations).
        - an existing ``stations_df`` (DataFrame with
          ``station_id, lon, lat``) -> validated and returned as-is.
        - a path to a ``.geojson``/``.json`` file of Point features ->
          one station per feature; ``station_id``/``station_name`` are
          read from feature properties if present, else auto-generated.
        - a path to a ``.csv`` file -> loaded via
          :func:`load_stations_from_csv`'s station-table shape.
        - a list of ``(lon, lat)`` or ``(station_id, lon, lat)`` tuples,
          or a list of dicts with at least ``lon``/``lat`` keys.
        - a single ``(lon, lat)`` tuple -> one station.

    Returns:
        A validated ``stations_df``.
    """
    import pandas as pd

    if stations is None:
        return config.default_stations_wa()

    if hasattr(stations, "columns"):  # already a DataFrame
        _validate_stations_df(stations)
        return stations

    if isinstance(stations, (str, Path)):
        path = Path(stations)
        if path.suffix.lower() in (".geojson", ".json"):
            return _stations_from_geojson(path)
        if path.suffix.lower() == ".csv":
            df, _ = load_stations_from_csv(path)
            return df
        raise ValueError(
            f"Don't know how to load stations from {path.suffix!r} files. "
            f"Expected .geojson, .json, or .csv."
        )

    if isinstance(stations, tuple) and len(stations) == 2:
        stations = [stations]

    if isinstance(stations, (list, tuple)):
        rows = []
        for i, item in enumerate(stations):
            if isinstance(item, dict):
                row = dict(item)
                row.setdefault("station_id", f"S{i + 1:03d}")
            elif len(item) == 2:
                row = {"station_id": f"S{i + 1:03d}", "lon": item[0], "lat": item[1]}
            elif len(item) == 3:
                row = {"station_id": item[0], "lon": item[1], "lat": item[2]}
            else:
                raise ValueError(f"Can't parse station entry: {item!r}")
            rows.append(row)
        df = pd.DataFrame(rows)
        _validate_stations_df(df)
        return df

    raise ValueError(
        f"Don't know how to interpret stations={stations!r} (type "
        f"{type(stations).__name__}). See load_stations_any() docstring "
        f"for accepted formats."
    )


def _stations_from_geojson(path: Path):
    """One station per Point feature in a GeoJSON file. No geopandas
    required — this only needs to read plain Point coordinates."""
    import json

    import pandas as pd

    with open(path) as f:
        gj = json.load(f)

    rows = []
    for i, feat in enumerate(gj.get("features", [])):
        geom = feat.get("geometry", {})
        if geom.get("type") != "Point":
            continue
        lon, lat = geom["coordinates"][:2]
        props = feat.get("properties") or {}
        rows.append(
            {
                "station_id": props.get("station_id", f"S{i + 1:03d}"),
                "station_name": props.get("station_name", props.get("name", "")),
                "lon": lon,
                "lat": lat,
                "elevation_m": props.get("elevation_m", None),
                "source": props.get("source", str(path.name)),
            }
        )
    if not rows:
        raise ValueError(f"No Point features found in {path}")
    df = pd.DataFrame(rows)
    _validate_stations_df(df)
    return df


def _validate_stations_df(stations_df) -> None:
    """Raise a clear error if ``stations_df`` is missing required columns.

    Deliberately strict about the minimum shape (fail fast with a
    useful message) but otherwise imposes nothing on the caller — extra
    columns are fine, and only ``station_id``/``lon``/``lat`` are
    actually required for extraction to work.
    """
    missing = REQUIRED_STATION_COLUMNS - set(stations_df.columns)
    if missing:
        raise ValueError(
            f"stations_df is missing required column(s): {sorted(missing)}. "
            f"A stations DataFrame needs at least "
            f"{sorted(REQUIRED_STATION_COLUMNS)}; "
            f"see config.default_stations_wa() for the expected shape."
        )
    if stations_df["station_id"].duplicated().any():
        dupes = stations_df.loc[
            stations_df["station_id"].duplicated(), "station_id"
        ].tolist()
        raise ValueError(f"stations_df has duplicate station_id values: {dupes}")


# ════════════════════════════════════════════════════════════
# Earth Engine helpers
# ════════════════════════════════════════════════════════════


def preview_map(stations_df=None, m=None, zoom: int = 5):
    """A quick interactive map of station locations — the first thing to
    check before extracting or validating anything: "are these actually
    where I think they are?"

    Args:
        stations_df: defaults to :func:`config.default_stations_wa`.
        m: an existing ``geemap.Map`` to add to, or a new one is created.
        zoom: zoom level when centering on the stations.

    Returns:
        A ``geemap.Map`` with one styled point layer for the stations.
        Click a point on the map to see its properties
        (``station_id``, ``station_name``, ``lon``, ``lat``) in
        geemap's built-in inspector panel.
    """
    import geemap

    stations_df = (
        stations_df if stations_df is not None else config.default_stations_wa()
    )
    _validate_stations_df(stations_df)

    if m is None:
        m = geemap.Map()

    fc = stations_to_ee_fc(stations_df)
    center_lon = float(stations_df.lon.mean())
    center_lat = float(stations_df.lat.mean())
    m.set_center(center_lon, center_lat, zoom)
    m.add_layer(fc.style(**{"color": "FFEB3B", "pointSize": 6}), {}, "Gauge Stations")
    return m


def stations_to_ee_fc(stations_df):
    """Convert any stations DataFrame to an ``ee.FeatureCollection`` of points.

    Works for any ``stations_df`` meeting :data:`REQUIRED_STATION_COLUMNS`
    — not specific to the WA network. Extra columns are copied through
    as feature properties.
    """
    import ee

    _validate_stations_df(stations_df)

    features = []
    extra_cols = [c for c in stations_df.columns if c not in ("lon", "lat")]
    for _, row in stations_df.iterrows():
        props = {c: row[c] for c in extra_cols}
        features.append(
            ee.Feature(ee.Geometry.Point([float(row.lon), float(row.lat)]), props)
        )
    return ee.FeatureCollection(features)


def load_gpcc_obs_from_asset(stations_df=None, asset_id: str | None = None):
    """Load pre-extracted GPCC observations from an Earth Engine table asset.

    Fast (no download, no NetCDF processing) but only returns rows for
    ``station_id`` values that already exist in the asset. Any station in
    ``stations_df`` not found in the asset is reported via a printed
    warning, not silently dropped without explanation — use
    :func:`download_gpcc` for those instead, or build your own asset with
    ``station_id, year, month, obs_mm_day`` columns and pass its ID here.

    Args:
        stations_df: defaults to :func:`config.default_stations_wa`.
        asset_id: EE table asset ID. Defaults to
            :data:`config.DEFAULT_GPCC_ASSET_WA`, which only covers the
            16 default WA stations — pass your own asset_id for any
            other station set.

    Returns:
        pandas.DataFrame with columns station_id, year, month, obs_mm_day.
    """
    import ee
    import pandas as pd

    stations_df = (
        stations_df if stations_df is not None else config.default_stations_wa()
    )
    asset_id = asset_id or config.DEFAULT_GPCC_ASSET_WA
    _validate_stations_df(stations_df)

    fc = ee.FeatureCollection(asset_id)
    info = fc.getInfo()
    rows = [f["properties"] for f in info["features"]]
    obs_df = pd.DataFrame(rows)
    if obs_df.empty:
        raise ValueError(f"EE asset {asset_id!r} returned no features.")

    missing_cols = REQUIRED_OBS_COLUMNS - set(obs_df.columns)
    if missing_cols:
        raise ValueError(
            f"EE asset {asset_id!r} is missing expected column(s) "
            f"{sorted(missing_cols)}. Expected {sorted(REQUIRED_OBS_COLUMNS)}."
        )

    obs_df["year"] = obs_df["year"].astype(int)
    obs_df["month"] = obs_df["month"].astype(int)
    obs_df["obs_mm_day"] = obs_df["obs_mm_day"].astype(float)

    wanted_ids = set(stations_df["station_id"])
    found_ids = set(obs_df["station_id"].unique())
    obs_df = obs_df[obs_df["station_id"].isin(wanted_ids)].reset_index(drop=True)

    not_found = wanted_ids - found_ids
    if not_found:
        print(
            f"  \u26a0  {len(not_found)} station(s) in stations_df have no data "
            f"in asset {asset_id!r}: {sorted(not_found)}\n"
            f"     Use download_gpcc() for these, or point asset_id at an "
            f"asset that includes them."
        )

    print(
        f"  GPCC observations loaded from asset: {len(obs_df):,} rows "
        f"({obs_df['station_id'].nunique()} station(s))"
    )
    return obs_df


# ════════════════════════════════════════════════════════════
# Public GPCC NetCDF archive — works for any station, anywhere
# ════════════════════════════════════════════════════════════


def _download_gpcc_year(year: int, raw_dir: Path) -> Path:
    """Download + decompress one yearly GPCC Full Data Daily v2022 file.

    Skips download/decompression if the file already exists locally.
    """
    import gzip
    import shutil

    import requests

    fname_gz = f"full_data_daily_v2022_10_{year}.nc.gz"
    fname_nc = fname_gz.replace(".gz", "")
    gz_path = raw_dir / fname_gz
    nc_path = raw_dir / fname_nc

    if nc_path.exists():
        return nc_path

    if not gz_path.exists():
        url = config.GPCC_FDD_BASE_URL + fname_gz
        print(f"  \u2193 Downloading {fname_gz} ...", end=" ", flush=True)
        resp = requests.get(url, stream=True, timeout=120)
        resp.raise_for_status()
        with open(gz_path, "wb") as f:
            shutil.copyfileobj(resp.raw, f)
        print(f"done ({gz_path.stat().st_size / 1e6:.1f} MB)")

    print(f"  \U0001f4e6 Decompressing {fname_gz} ...", end=" ", flush=True)
    with gzip.open(gz_path, "rb") as f_in, open(nc_path, "wb") as f_out:
        shutil.copyfileobj(f_in, f_out)
    gz_path.unlink()
    print("done")
    return nc_path


def _extract_monthly_means(nc_path: Path, stations_df):
    """Extract monthly mean mm/day at arbitrary station coordinates from
    one GPCC daily NetCDF file, via nearest-neighbour lookup.

    Generalised from the original station-specific extractor — takes
    ``stations_df`` instead of a hardcoded station dict, so it works for
    any station set falling within the GPCC grid's coverage.
    """
    import pandas as pd
    import xarray as xr

    ds = xr.open_dataset(nc_path)

    precip_var = next(
        (v for v in ("p", "precip", "precipitation", "rain") if v in ds), None
    )
    if precip_var is None:
        raise ValueError(
            f"Cannot find a precipitation variable in {nc_path.name}. "
            f"Variables present: {list(ds.data_vars)}"
        )

    da_monthly = ds[precip_var].resample(time="ME").mean(dim="time")

    rows = []
    for _, s in stations_df.iterrows():
        val = da_monthly.sel(lon=float(s.lon), lat=float(s.lat), method="nearest")
        for t in val.time.values:
            ts = pd.Timestamp(t)
            v = float(val.sel(time=t).values)
            rows.append(
                {
                    "station_id": s.station_id,
                    "year": ts.year,
                    "month": ts.month,
                    "obs_mm_day": round(max(0.0, v), 4),
                }
            )
    ds.close()
    return pd.DataFrame(rows)


def download_gpcc(
    stations_df=None,
    start_year: int = 2001,
    end_year: int = 2020,
    data_dir: str | Path | None = None,
    keep_raw: bool = False,
):
    """Download the public GPCC archive and extract at any station set.

    Works for any ``stations_df`` (defaults to the WA 16), anywhere the
    GPCC 1.0-degree grid has coverage — this is the fully general path,
    unlike :func:`load_gpcc_obs_from_asset` which only covers whatever
    stations happen to already be in an EE asset.

    Downloads are cached: files already present in ``data_dir`` are
    skipped, so re-running after a partial failure only fetches what's
    missing. Requires ``requests``, ``xarray``, ``netCDF4`` (installed
    with ``pip install "savana[rainfall]"``).

    Args:
        stations_df: defaults to :func:`config.default_stations_wa`.
        start_year, end_year: inclusive year range.
        data_dir: local cache directory. Defaults to
            ``./savana_rainfall_data`` in the current working directory.
        keep_raw: if False (default), deletes the raw yearly NetCDF
            files after extraction to save disk space (~20 MB/year).

    Returns:
        pandas.DataFrame with columns station_id, year, month, obs_mm_day.
    """
    import pandas as pd

    stations_df = (
        stations_df if stations_df is not None else config.default_stations_wa()
    )
    _validate_stations_df(stations_df)

    data_dir = Path(data_dir) if data_dir else Path.cwd() / "savana_rainfall_data"
    raw_dir = data_dir / "gpcc_raw"
    raw_dir.mkdir(parents=True, exist_ok=True)

    print(
        f"  GPCC download: {len(stations_df)} station(s), "
        f"{start_year}-{end_year}, cache: {raw_dir}"
    )

    all_rows = []
    for year in range(start_year, end_year + 1):
        try:
            nc_path = _download_gpcc_year(year, raw_dir)
        except Exception as exc:  # noqa: BLE001
            print(f"  \u26a0  {year}: download failed ({type(exc).__name__}: {exc})")
            continue

        try:
            df_yr = _extract_monthly_means(nc_path, stations_df)
            df_yr = df_yr[df_yr["year"] == year]
            all_rows.append(df_yr)
            expected = len(stations_df) * 12
            flag = "" if len(df_yr) >= expected * 0.9 else " \u26a0"
            print(f"  {year}: {len(df_yr)} rows (expected {expected}){flag}")
        except Exception as exc:  # noqa: BLE001
            print(f"  \u26a0  {year}: extraction failed ({type(exc).__name__}: {exc})")
            continue
        finally:
            if not keep_raw:
                nc_path.unlink(missing_ok=True)

    if not all_rows:
        raise RuntimeError("No GPCC data could be extracted for any year.")

    combined = pd.concat(all_rows, ignore_index=True)
    combined = combined.sort_values(["station_id", "year", "month"]).reset_index(
        drop=True
    )

    out_path = data_dir / f"gpcc_obs_{start_year}_{end_year}.csv"
    combined.to_csv(out_path, index=False)
    print(f"  Done: {len(combined):,} rows -> {out_path}")
    return combined


# ════════════════════════════════════════════════════════════
# User-supplied CSVs — fully general, no assumptions at all
# ════════════════════════════════════════════════════════════


def load_stations_from_csv(stations_csv: str | Path, obs_csv: str | Path | None = None):
    """Load your own station metadata (and optionally observations) from CSV.

    ``stations_csv`` must have columns
    ``station_id, station_name, lon, lat, elevation_m, source``
    (matching :data:`config.DEFAULT_STATION_COLUMNS`).
    ``obs_csv``, if given, must have columns
    ``station_id, year, month, obs_mm_day``.

    This is the fully general entry point for a station network that
    isn't West Africa's 16 GPCC stations at all — bring your own gauge
    metadata and (optionally) your own already-extracted observations.
    """
    import pandas as pd

    stations_df = pd.read_csv(stations_csv)
    missing_stn = set(config.DEFAULT_STATION_COLUMNS) - set(stations_df.columns)
    if missing_stn:
        raise ValueError(f"stations_csv is missing column(s): {sorted(missing_stn)}")
    _validate_stations_df(stations_df)
    print(f"  Stations loaded: {len(stations_df)} from {stations_csv}")

    if obs_csv is None:
        return stations_df, None

    obs_df = pd.read_csv(obs_csv)
    missing_obs = REQUIRED_OBS_COLUMNS - set(obs_df.columns)
    if missing_obs:
        raise ValueError(f"obs_csv is missing column(s): {sorted(missing_obs)}")
    obs_df["year"] = obs_df["year"].astype(int)
    obs_df["month"] = obs_df["month"].astype(int)
    obs_df["obs_mm_day"] = obs_df["obs_mm_day"].astype(float)
    print(f"  Observations loaded: {len(obs_df):,} rows from {obs_csv}")

    return stations_df, obs_df


# ════════════════════════════════════════════════════════════
# Synthetic demo data — testing/tutorials only, never silent
# ════════════════════════════════════════════════════════════


def generate_demo_observations(
    stations_df=None,
    start_year: int = 2001,
    end_year: int = 2020,
    seed: int = 42,
):
    """Synthetic monthly precipitation observations for quick testing only.

    NOT real data — a plausible seasonal-cycle-plus-noise placeholder so
    the rest of the pipeline can be exercised without waiting on a real
    GPCC download or an EE asset. Only used when explicitly requested
    (``source="demo"`` in :func:`get_observations`); never a silent
    fallback elsewhere in this package.
    """
    import numpy as np
    import pandas as pd

    stations_df = (
        stations_df if stations_df is not None else config.default_stations_wa()
    )
    _validate_stations_df(stations_df)

    rng = np.random.default_rng(seed=seed)
    rows = []
    for _, s in stations_df.iterrows():
        for yr in range(start_year, end_year + 1):
            for mo in range(1, 13):
                phase = (mo - 8) if s.lat > 10 else (mo - 6)
                amp = 4.0 if s.lat > 10 else 7.0
                obs = max(
                    0.0,
                    0.5
                    + amp * max(0.0, np.cos(phase * np.pi / 3))
                    + rng.normal(0, 1.25),
                )
                rows.append(
                    {
                        "station_id": s.station_id,
                        "year": yr,
                        "month": mo,
                        "obs_mm_day": round(float(obs), 2),
                    }
                )
    print(
        f"  \u26a0  SYNTHETIC demo observations generated "
        f"({len(stations_df)} stations, {start_year}-{end_year}) — "
        f"not real data, testing/tutorial use only."
    )
    return pd.DataFrame(rows)


# ════════════════════════════════════════════════════════════
# Orchestrator
# ════════════════════════════════════════════════════════════


def get_observations(stations_df=None, source: str = "download", **kwargs):
    """Single entry point for getting gauge observations, any station set.

    Args:
        stations_df: defaults to :func:`config.default_stations_wa`.
        source: one of
            - ``"download"`` (default): :func:`download_gpcc` — fully
              general, works for any station, slow on first run.
            - ``"ee_asset"``: :func:`load_gpcc_obs_from_asset` — fast,
              limited to whatever stations are already in the asset.
            - ``"csv"``: :func:`load_stations_from_csv`'s obs half —
              requires ``obs_csv=`` in ``kwargs``.
            - ``"demo"``: :func:`generate_demo_observations` — synthetic,
              testing only.
        **kwargs: forwarded to the selected loader.

    Returns:
        pandas.DataFrame with columns station_id, year, month, obs_mm_day.
    """
    stations_df = (
        stations_df if stations_df is not None else config.default_stations_wa()
    )

    if source == "download":
        return download_gpcc(stations_df, **kwargs)
    if source == "ee_asset":
        return load_gpcc_obs_from_asset(stations_df, **kwargs)
    if source == "csv":
        obs_csv = kwargs.pop("obs_csv", None)
        if obs_csv is None:
            raise ValueError('source="csv" requires obs_csv=<path> in kwargs.')
        import pandas as pd

        obs_df = pd.read_csv(obs_csv)
        missing = REQUIRED_OBS_COLUMNS - set(obs_df.columns)
        if missing:
            raise ValueError(f"obs_csv is missing column(s): {sorted(missing)}")
        return obs_df
    if source == "demo":
        return generate_demo_observations(stations_df, **kwargs)

    raise ValueError(
        f"Unknown source {source!r}. Expected one of: "
        f'"download", "ee_asset", "csv", "demo".'
    )
