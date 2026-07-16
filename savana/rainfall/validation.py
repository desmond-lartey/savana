"""Continuous and categorical validation metrics.

Two metric classes, matching the manuscript's dual-class framework:

- **Continuous** (:func:`compute_continuous`): bias, pbias, mae, rmse,
  r, r2, nse, kge — how well magnitude and pattern agree.
- **Categorical** (:func:`compute_categorical`): pod, far, csi, ets,
  freq_bias — how well wet/dry events are detected above a threshold.

Both take plain ``obs``/``sim`` array-likes, so they work regardless of
which stations, products, or zones produced them. The four levels of
spatial/temporal aggregation used in the manuscript (per-station,
per-zone, per-season, pooled) are all just different ``group_cols`` to
the single :func:`validate_grouped` function — there's no separate
per-station/per-zone/per-season implementation to keep in sync.
"""

from __future__ import annotations

from . import config

# ════════════════════════════════════════════════════════════
# Continuous metrics
# ════════════════════════════════════════════════════════════


def compute_continuous(obs, sim) -> dict:
    """Continuous performance metrics for one obs/sim pair.

    Rows where either ``obs`` or ``sim`` is missing are dropped before
    computation, matching the manuscript's paired-record approach.
    Returns ``{"n": 0, ...all-NaN}`` if fewer than 2 valid pairs remain
    (metrics like r/NSE/KGE are undefined below that).
    """
    import numpy as np
    import pandas as pd

    o = pd.Series(obs).astype(float)
    s = pd.Series(sim).astype(float)
    mask = o.notna() & s.notna()
    o, s = o[mask].to_numpy(), s[mask].to_numpy()
    n = len(o)

    keys = ["bias", "pbias", "mae", "rmse", "r", "r2", "nse", "kge"]
    if n < 2:
        return {"n": n, **{k: float("nan") for k in keys}}

    obar, sbar = o.mean(), s.mean()
    diff = s - o

    bias = float(diff.mean())
    pbias = float(100.0 * diff.sum() / o.sum()) if o.sum() != 0 else float("nan")
    mae = float(np.abs(diff).mean())
    rmse = float(np.sqrt((diff**2).mean()))

    o_std, s_std = o.std(), s.std()
    if o_std == 0 or s_std == 0:
        r = float("nan")
    else:
        r = float(np.corrcoef(o, s)[0, 1])
    r2 = float(r**2) if not np.isnan(r) else float("nan")

    denom_nse = ((o - obar) ** 2).sum()
    nse = (
        float(1 - ((s - o) ** 2).sum() / denom_nse) if denom_nse != 0 else float("nan")
    )

    if np.isnan(r) or obar == 0 or o_std == 0:
        kge = float("nan")
    else:
        alpha = s_std / o_std
        beta = sbar / obar
        kge = float(1 - np.sqrt((r - 1) ** 2 + (alpha - 1) ** 2 + (beta - 1) ** 2))

    return {
        "n": n,
        "bias": bias,
        "pbias": pbias,
        "mae": mae,
        "rmse": rmse,
        "r": r,
        "r2": r2,
        "nse": nse,
        "kge": kge,
    }


# ════════════════════════════════════════════════════════════
# Categorical metrics
# ════════════════════════════════════════════════════════════


def compute_categorical(obs, sim, threshold: float | None = None) -> dict:
    """Categorical wet/dry detection metrics from a 2x2 contingency table.

    A record is "wet" if the value >= ``threshold`` (default
    :data:`config.DEFAULT_RAIN_THRESHOLD_MM_DAY`, the WMO standard of
    1.0 mm/day), else "dry".
    """
    import numpy as np
    import pandas as pd

    threshold = (
        threshold if threshold is not None else config.DEFAULT_RAIN_THRESHOLD_MM_DAY
    )

    o = pd.Series(obs).astype(float)
    s = pd.Series(sim).astype(float)
    mask = o.notna() & s.notna()
    o, s = o[mask].to_numpy(), s[mask].to_numpy()
    n = len(o)

    keys = ["pod", "far", "csi", "ets", "freq_bias"]
    count_keys = ["hits", "misses", "false_alarms", "correct_negatives"]
    if n < 1:
        return {"n": 0, **{k: float("nan") for k in keys + count_keys}}

    obs_wet, sim_wet = o >= threshold, s >= threshold
    hits = int(np.sum(obs_wet & sim_wet))
    misses = int(np.sum(obs_wet & ~sim_wet))
    false_alarms = int(np.sum(~obs_wet & sim_wet))
    correct_negatives = int(np.sum(~obs_wet & ~sim_wet))

    pod = hits / (hits + misses) if (hits + misses) > 0 else float("nan")
    far = (
        false_alarms / (hits + false_alarms)
        if (hits + false_alarms) > 0
        else float("nan")
    )
    csi_denom = hits + misses + false_alarms
    csi = hits / csi_denom if csi_denom > 0 else float("nan")

    total = hits + misses + false_alarms + correct_negatives
    hits_random = (
        (hits + misses) * (hits + false_alarms) / total if total > 0 else float("nan")
    )
    ets_denom = hits + misses + false_alarms - hits_random
    ets = (
        (hits - hits_random) / ets_denom
        if ets_denom not in (0, float("nan")) and not np.isnan(ets_denom)
        else float("nan")
    )

    freq_bias = (
        (hits + false_alarms) / (hits + misses) if (hits + misses) > 0 else float("nan")
    )

    return {
        "n": n,
        "threshold": threshold,
        "pod": pod,
        "far": far,
        "csi": csi,
        "ets": ets,
        "freq_bias": freq_bias,
        "hits": hits,
        "misses": misses,
        "false_alarms": false_alarms,
        "correct_negatives": correct_negatives,
    }


def compute_all_metrics(obs, sim, threshold: float | None = None) -> dict:
    """Continuous + categorical metrics for one obs/sim pair, merged."""
    out = compute_continuous(obs, sim)
    out.update(compute_categorical(obs, sim, threshold))
    return out


# ════════════════════════════════════════════════════════════
# Grouped validation — one function, any aggregation level
# ════════════════════════════════════════════════════════════


def validate_grouped(
    merged_df,
    group_cols: list[str],
    obs_col: str = "obs_mm_day",
    sim_col: str = "sim_mm_day",
    threshold: float | None = None,
):
    """Compute continuous + categorical metrics for each group in ``merged_df``.

    ``merged_df`` must be long-format with one row per
    (station, year, month, product) and columns ``obs_col``/``sim_col``
    (see :func:`savana.rainfall.extraction.merge_with_observations`).

    This single function implements all four aggregation levels used in
    the manuscript — pass the ``group_cols`` that define the level:

    - per-station:  ``["station_id", "product"]``
    - per-zone:     ``["zone", "product"]``
    - per-season:   ``["zone", "season", "product"]``
    - pooled/overall: ``["product"]``

    Returns a DataFrame with one row per group, group_cols + all metrics.
    """
    import pandas as pd

    rows = []
    for key, sub in merged_df.groupby(group_cols, dropna=False):
        key = key if isinstance(key, tuple) else (key,)
        metrics = compute_all_metrics(sub[obs_col], sub[sim_col], threshold)
        rows.append(dict(zip(group_cols, key), **metrics))
    return pd.DataFrame(rows)


_SEASON_MONTHS = {
    12: "DJF",
    1: "DJF",
    2: "DJF",
    3: "MAM",
    4: "MAM",
    5: "MAM",
    6: "JJA",
    7: "JJA",
    8: "JJA",
    9: "SON",
    10: "SON",
    11: "SON",
}


def add_season_column(merged_df, month_col: str = "month"):
    """Add a ``season`` column (DJF/MAM/JJA/SON) derived from ``month_col``."""
    merged_df = merged_df.copy()
    merged_df["season"] = merged_df[month_col].map(_SEASON_MONTHS)
    return merged_df


def validate_by_station(merged_df, threshold=None):
    """Metrics per (station_id, product) — manuscript's finest level."""
    return validate_grouped(merged_df, ["station_id", "product"], threshold=threshold)


def validate_by_zone(merged_df, threshold=None):
    """Metrics per (zone, product) — the manuscript's primary analytical lens.

    ``merged_df`` must already have a ``zone`` column
    (see :func:`savana.rainfall.zones.assign_zones`).
    """
    if "zone" not in merged_df.columns:
        raise ValueError(
            "merged_df has no 'zone' column — run zones.assign_zones() on your "
            "stations_df and merge it in before calling validate_by_zone()."
        )
    return validate_grouped(merged_df, ["zone", "product"], threshold=threshold)


def validate_by_season(merged_df, threshold=None):
    """Metrics per (zone, season, product)."""
    if "season" not in merged_df.columns:
        merged_df = add_season_column(merged_df)
    return validate_grouped(
        merged_df, ["zone", "season", "product"], threshold=threshold
    )


def validate_overall(merged_df, threshold=None):
    """Metrics per product, pooled across all stations/zones."""
    return validate_grouped(merged_df, ["product"], threshold=threshold)


# ════════════════════════════════════════════════════════════
# Ranking
# ════════════════════════════════════════════════════════════


def rank_products(
    validation_df, metric: str = "kge", group_cols: list[str] | None = None
):
    """Rank products within each group by a single metric (default KGE,
    the manuscript's primary ranking metric — see methods 2.4.1).

    ``group_cols`` defaults to every column in ``validation_df`` except
    ``"product"`` and the metric columns — i.e. whatever grouping level
    the input DataFrame already represents (zone, station, season...).
    """
    df = validation_df.copy()
    if group_cols is None:
        non_metric = set(config.DEFAULT_METRICS_FLAT) | {
            "n",
            "threshold",
            "hits",
            "misses",
            "false_alarms",
            "correct_negatives",
            "product",
        }
        group_cols = [c for c in df.columns if c not in non_metric]

    ascending = metric in ("far", "rmse", "mae", "bias")
    df["rank"] = (
        df.groupby(group_cols)[metric]
        .rank(ascending=ascending, method="min")
        .astype(int)
    )
    sort_cols = group_cols + ["rank"]
    return df.sort_values(sort_cols).reset_index(drop=True)
