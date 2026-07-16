"""Static matplotlib figures for a rainfall assessment.

Reads directly from the DataFrames produced by :mod:`.validation` and
:mod:`.decision` — no Excel round-trip required, though
:func:`recommendation_heatmap` also happily reads a ``SCORES`` sheet
exported by :func:`savana.rainfall.decision.build_workbook` if that's
more convenient (same shape either way: app, zone, product, score).
"""

from __future__ import annotations


def _get_fig_ax(figsize=(8, 6)):
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots(figsize=figsize)
    return fig, ax


def preview_observations(obs_df, station_id: str | None = None):
    """A quick time-series look at raw GPCC observations — before
    extracting or validating any product, "does the reference data
    itself look sane?" One line per station, or a single station if
    ``station_id`` is given.
    """
    import pandas as pd

    df = obs_df if station_id is None else obs_df[obs_df["station_id"] == station_id]
    if df.empty:
        raise ValueError(f"No observations found for station_id={station_id!r}")

    fig, ax = _get_fig_ax(figsize=(10, 4))
    for sid, sub in df.groupby("station_id"):
        sub = sub.sort_values(["year", "month"])
        t = pd.to_datetime(
            sub["year"].astype(str) + "-" + sub["month"].astype(str) + "-01"
        )
        ax.plot(t, sub["obs_mm_day"], label=sid, linewidth=1)
    ax.set_ylabel("Observed (mm/day)")
    ax.set_title(
        "GPCC observations" + (f" — {station_id}" if station_id else " — all stations")
    )
    if df["station_id"].nunique() > 1:
        ax.legend(fontsize=7, ncol=4)
    fig.tight_layout()
    return fig


def preview_comparison(
    merged_df, station_id: str | None = None, product: str | None = None
):
    """A quick "does this look right?" comparison of observed vs
    simulated values — before computing formal validation metrics.
    Scatter with a 1:1 reference line, one color per product (or
    filtered to one product/station if given). Mirrors the GEE app's
    per-station validation scatter chart.
    """
    df = merged_df
    if station_id is not None:
        df = df[df["station_id"] == station_id]
    if product is not None:
        df = df[df["product"] == product]
    if df.empty:
        raise ValueError("No rows match the given station_id/product filter.")

    fig, ax = _get_fig_ax(figsize=(6, 6))
    for prod, sub in df.groupby("product"):
        ax.scatter(sub["obs_mm_day"], sub["sim_mm_day"], s=10, alpha=0.5, label=prod)

    lim = max(df["obs_mm_day"].max(), df["sim_mm_day"].max()) * 1.05
    ax.plot([0, lim], [0, lim], "k--", linewidth=1, label="1:1")
    ax.set_xlim(0, lim)
    ax.set_ylim(0, lim)
    ax.set_xlabel("Observed (mm/day)")
    ax.set_ylabel("Simulated (mm/day)")
    title = "Obs vs Sim"
    if station_id:
        title += f" — {station_id}"
    if product:
        title += f" — {product}"
    ax.set_title(title)
    ax.legend(fontsize=8)
    fig.tight_layout()
    return fig


def metric_heatmap(validation_df, metric: str = "kge", group_col: str = "zone"):
    """Zone x product heatmap of one metric."""
    pivot = validation_df.pivot_table(index=group_col, columns="product", values=metric)
    fig, ax = _get_fig_ax(
        figsize=(1.2 * len(pivot.columns) + 2, 0.6 * len(pivot.index) + 2)
    )
    im = ax.imshow(pivot.values, cmap="RdYlGn", aspect="auto")
    ax.set_xticks(range(len(pivot.columns)))
    ax.set_xticklabels(pivot.columns, rotation=45, ha="right")
    ax.set_yticks(range(len(pivot.index)))
    ax.set_yticklabels(pivot.index)
    for i in range(len(pivot.index)):
        for j in range(len(pivot.columns)):
            v = pivot.values[i, j]
            if v == v:  # not NaN
                ax.text(j, i, f"{v:.2f}", ha="center", va="center", fontsize=8)
    ax.set_title(f"{metric.upper()} by {group_col} x product")
    fig.colorbar(im, ax=ax, shrink=0.8, label=metric.upper())
    fig.tight_layout()
    return fig


def zonal_boxplot(validation_df, metric: str = "kge"):
    """Distribution of one metric across zones, one box per product."""
    products = sorted(validation_df["product"].unique())
    fig, ax = _get_fig_ax(figsize=(1.3 * len(products) + 2, 5))
    data = [
        validation_df.loc[validation_df["product"] == p, metric].dropna()
        for p in products
    ]
    ax.boxplot(data, labels=products)
    ax.set_ylabel(metric.upper())
    ax.set_title(f"{metric.upper()} distribution across zones, by product")
    ax.tick_params(axis="x", rotation=45)
    fig.tight_layout()
    return fig


def taylor_diagram(validation_df, zone: str | None = None, ref_std: float = 1.0):
    """Simplified Taylor diagram (correlation vs normalised std dev)
    for every product, optionally filtered to one zone.
    """
    import matplotlib.pyplot as plt
    import numpy as np

    df = validation_df if zone is None else validation_df[validation_df["zone"] == zone]

    fig = plt.figure(figsize=(7, 7))
    ax = fig.add_subplot(111, polar=True)
    ax.set_thetalim(0, np.pi / 2)
    ax.set_xticks(np.arccos([1, 0.9, 0.7, 0.5, 0.3, 0])[::-1])
    ax.set_xticklabels(["1.0", "0.9", "0.7", "0.5", "0.3", "0"][::-1])

    for _, row in df.iterrows():
        r = row.get("r", float("nan"))
        if r != r:
            continue
        theta = np.arccos(max(-1, min(1, r)))
        # r2 as a stand-in radial "spread" proxy when true sim/obs std ratio
        # isn't in the table; callers with std ratios can pass their own.
        radius = row.get("std_ratio", 1.0)
        ax.plot(theta, radius, "o", label=row["product"], markersize=8)

    ax.set_title(f"Taylor diagram{f' — {zone}' if zone else ''}")
    ax.legend(loc="upper left", bbox_to_anchor=(1.05, 1.0), fontsize=8)
    fig.tight_layout()
    return fig


def application_ranking_bars(scores_df, app: str):
    """Bar chart of every product's score for one application, one bar
    group per zone.
    """
    import numpy as np

    sub = scores_df[scores_df["app"] == app]
    zones = sorted(sub["zone"].unique()) if "zone" in sub.columns else ["pooled"]
    products = sorted(sub["product"].unique())

    fig, ax = _get_fig_ax(figsize=(1.5 * len(zones) + 2, 5))
    width = 0.8 / len(products)
    x = np.arange(len(zones))
    for i, prod in enumerate(products):
        vals = [
            sub[(sub.get("zone", "pooled") == z) & (sub["product"] == prod)][
                "score"
            ].mean()
            for z in zones
        ]
        ax.bar(x + i * width, vals, width, label=prod)
    ax.set_xticks(x + width * (len(products) - 1) / 2)
    ax.set_xticklabels(zones, rotation=30, ha="right")
    ax.set_ylabel("Application-weighted score")
    ax.set_title(f"Product ranking — {app}")
    ax.legend(fontsize=8, ncol=2)
    fig.tight_layout()
    return fig


def recommendation_heatmap(scores_df):
    """App x zone grid, each cell showing the single best product +
    its score — the "decision matrix" view, folding in
    fig_application_rankings_v4.py's recommendation-heatmap figure.
    """
    from . import decision

    apps = sorted(scores_df["app"].unique())
    zones = (
        sorted(scores_df["zone"].unique())
        if "zone" in scores_df.columns
        else ["pooled"]
    )

    best_scores = [[float("nan")] * len(zones) for _ in apps]
    labels = [[""] * len(zones) for _ in apps]
    for i, app in enumerate(apps):
        for j, zone in enumerate(zones):
            prod, score = decision.best_product(
                scores_df, app, zone if zone != "pooled" else None
            )
            if prod is not None:
                best_scores[i][j] = score
                labels[i][j] = f"{prod}\n{score:.2f}"

    fig, ax = _get_fig_ax(figsize=(1.5 * len(zones) + 3, 0.6 * len(apps) + 2))
    im = ax.imshow(best_scores, cmap="RdYlGn", vmin=0, vmax=1, aspect="auto")
    ax.set_xticks(range(len(zones)))
    ax.set_xticklabels(zones, rotation=30, ha="right")
    ax.set_yticks(range(len(apps)))
    ax.set_yticklabels(apps)
    for i in range(len(apps)):
        for j in range(len(zones)):
            if labels[i][j]:
                ax.text(j, i, labels[i][j], ha="center", va="center", fontsize=7)
    ax.set_title("Recommended product by application x zone")
    fig.colorbar(im, ax=ax, shrink=0.8, label="Application-weighted score")
    fig.tight_layout()
    return fig
