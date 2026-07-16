"""Rain-detection threshold sensitivity analysis.

Categorical metrics (POD, FAR, CSI, ETS) depend on the wet/dry
threshold used to classify a record — this matters most in dryland
zones where near-zero rainfall makes categorical detection structurally
unstable (see manuscript sections 2.5 and the Saharian zone note in
:data:`savana.rainfall.config.DEFAULT_ZONE_NOTES`). This module sweeps
:func:`savana.rainfall.validation.compute_categorical` across multiple
thresholds rather than duplicating its logic.
"""

from __future__ import annotations

from . import config, validation


def threshold_sensitivity(
    merged_df,
    thresholds: list[float] | None = None,
    group_cols: list[str] | None = None,
    obs_col: str = "obs_mm_day",
    sim_col: str = "sim_mm_day",
):
    """Categorical metrics at each of several rain-detection thresholds.

    Args:
        merged_df: long-format obs/sim data (see
            :func:`savana.rainfall.extraction.merge_with_observations`).
        thresholds: mm/day values to sweep. Defaults to
            :data:`config.DEFAULT_THRESHOLD_SWEEP_MM_DAY`
            (0.1, 0.5, 1.0, 2.0, 5.0 mm/day).
        group_cols: grouping level, e.g. ``["zone", "product"]``
            (default) or ``["product"]`` for pooled.

    Returns:
        DataFrame with one row per (group, threshold) combination.
    """
    import pandas as pd

    thresholds = (
        thresholds if thresholds is not None else config.DEFAULT_THRESHOLD_SWEEP_MM_DAY
    )
    if group_cols is None:
        group_cols = ["zone", "product"] if "zone" in merged_df.columns else ["product"]

    rows = []
    for threshold in thresholds:
        for key, sub in merged_df.groupby(group_cols, dropna=False):
            key = key if isinstance(key, tuple) else (key,)
            metrics = validation.compute_categorical(
                sub[obs_col], sub[sim_col], threshold
            )
            rows.append(dict(zip(group_cols, key), **metrics))

    df = pd.DataFrame(rows)
    return df.sort_values(group_cols + ["threshold"]).reset_index(drop=True)


def stability_summary(
    threshold_df, metric: str = "csi", group_cols: list[str] | None = None
):
    """Rank product/group robustness across the threshold sweep.

    Returns one row per group with the metric's mean, std, and
    coefficient of variation across all swept thresholds — a low CV
    means the product's performance on that metric is stable regardless
    of exactly where the wet/dry line is drawn; a high CV flags
    threshold-sensitive rankings (per manuscript 2.5's structural
    instability finding in near-zero-rainfall zones).
    """
    if group_cols is None:
        group_cols = [c for c in ("zone", "product") if c in threshold_df.columns]

    agg = threshold_df.groupby(group_cols)[metric].agg(["mean", "std"]).reset_index()
    agg["cv"] = agg["std"] / agg["mean"].replace(0, float("nan"))
    return agg.sort_values(group_cols[:-1] + ["cv"] if len(group_cols) > 1 else "cv")
