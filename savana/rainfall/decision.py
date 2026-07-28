"""Application-weighted product scoring and the interactive decision
support workbook.

:func:`score_products` implements two normalisation modes:

- ``"fixed"`` (default): each metric normalised against a fixed
  plausible range (KGE against -1..1, NSE against -5..1, |PBIAS|
  against 0..60, etc — see
  :data:`savana.rainfall.config.DEFAULT_NORMALIZATION_BOUNDS`). This is
  what the shipped decision workbook and reported figures actually use
  — verified by reproducing ``WA_Precipitation_Decision_Tool_v2.xlsx``'s
  SELECTOR-sheet scores exactly (Fire-risk x Saharian x CHIRPS = 0.7551).
- ``"zone_relative"``: per-zone min-max across whatever products are
  being compared, matching the manuscript's written formula (section
  2.6). Scale-invariant — recommended if you add/remove products from
  the default six, since fixed bounds were tuned for the original
  product set's plausible range.

:func:`build_workbook` writes a live spreadsheet tool (data-validation
dropdowns + INDEX/MATCH formulas that recompute instantly), not a
static report — the same design as the current
``WA_Precipitation_Decision_Tool_v2.xlsx``, generalised to any
products/zones/apps rather than hardcoded to the WA six.
"""

from __future__ import annotations

from . import config


def _normalise_fixed(value: float, bounds: tuple[float, float, bool]) -> float:
    lo, hi, invert = bounds
    v = abs(value) if invert else value
    lo_eff = 0.0 if invert else lo
    hi_eff = hi if invert else hi
    frac = (v - lo_eff) / (hi_eff - lo_eff) if hi_eff != lo_eff else float("nan")
    frac = max(0.0, min(1.0, frac))
    return (1 - frac) if invert else frac


def score_products(
    validation_df,
    weights: dict | None = None,
    normalization: str = "fixed",
    bounds: dict | None = None,
    group_cols: list[str] | None = None,
):
    """Application-weighted composite score for every (zone, product)
    combination, for every application in ``weights``.

    Args:
        validation_df: per-zone (or per-station/pooled) metrics table,
            e.g. from :func:`savana.rainfall.validation.validate_by_zone`.
            Must have a ``product`` column and the metric columns
            referenced by ``weights`` (kge, r, nse, pod, far, csi, pbias
            by default).
        weights: ``{application_name: {metric: weight, ...}}``, weights
            summing to 1.0 per application. Defaults to
            :data:`config.DEFAULT_APP_WEIGHTS` (the 7 conservation/
            water-management applications) — pass your own for
            different applications or priorities.
        normalization: ``"fixed"`` (default, matches shipped results) or
            ``"zone_relative"`` (matches the manuscript's written
            formula — see module docstring).
        bounds: only used when ``normalization="fixed"``. Defaults to
            :data:`config.DEFAULT_NORMALIZATION_BOUNDS`.
        group_cols: columns identifying each row's context (default:
            ``["zone"]`` if present, else none — i.e. pooled).

    Returns:
        Long-format DataFrame: ``group_cols + ["app", "product", "score"]``.
    """
    import pandas as pd

    weights = weights if weights is not None else config.DEFAULT_APP_WEIGHTS
    bounds = bounds if bounds is not None else config.DEFAULT_NORMALIZATION_BOUNDS
    if group_cols is None:
        group_cols = ["zone"] if "zone" in validation_df.columns else []

    metric_cols = sorted({m for w in weights.values() for m in w})
    missing = [m for m in metric_cols if m not in validation_df.columns]
    if missing:
        raise ValueError(
            f"validation_df is missing metric column(s) required by weights: "
            f"{missing}"
        )

    df = validation_df.copy()

    if normalization == "fixed":
        for m in metric_cols:
            if m not in bounds:
                raise ValueError(f"No normalization bounds given for metric {m!r}")
            df[f"_norm_{m}"] = df[m].apply(
                lambda v, mm=m: _normalise_fixed(v, bounds[mm])
            )
    elif normalization == "zone_relative":
        for m in metric_cols:
            invert = bounds.get(m, (None, None, False))[2]
            grp = df.groupby(group_cols)[m] if group_cols else df[m]

            def _rel(s, _invert=invert):
                lo, hi = s.min(), s.max()
                if hi == lo:
                    return s.apply(lambda _: float("nan"))
                frac = (s - lo) / (hi - lo)
                return 1 - frac if _invert else frac

            if group_cols:
                df[f"_norm_{m}"] = grp.transform(_rel)
            else:
                df[f"_norm_{m}"] = _rel(df[m])
    else:
        raise ValueError(
            f"Unknown normalization {normalization!r}: expected "
            f'"fixed" or "zone_relative".'
        )

    rows = []
    for app, app_weights in weights.items():
        score = sum(df[f"_norm_{m}"] * w for m, w in app_weights.items())
        for idx, s in score.items():
            row = {c: df.at[idx, c] for c in group_cols}
            row["app"] = app
            row["product"] = df.at[idx, "product"]
            row["score"] = round(float(s), 4) if s == s else float("nan")  # NaN-safe
            rows.append(row)

    scores_df = pd.DataFrame(rows)
    sort_cols = group_cols + ["app", "score"]
    return scores_df.sort_values(
        sort_cols, ascending=[True] * len(group_cols) + [True, False]
    ).reset_index(drop=True)


def best_product(scores_df, app: str, zone: str | None = None):
    """The top-scoring product for a given application (and optionally
    zone). Returns ``(product, score)`` or ``(None, None)`` if no match.
    """
    sub = scores_df[scores_df["app"] == app]
    if zone is not None and "zone" in sub.columns:
        sub = sub[sub["zone"] == zone]
    if sub.empty:
        return None, None
    top = sub.sort_values("score", ascending=False).iloc[0]
    return top["product"], float(top["score"])


# ════════════════════════════════════════════════════════════
# Interactive Excel workbook
# ════════════════════════════════════════════════════════════


def build_workbook(
    out_path,
    validation_by_zone_df,
    validation_overall_df=None,
    ranking_df=None,
    threshold_df=None,
    scores_df=None,
    app_weights: dict | None = None,
    zone_notes: dict | None = None,
):
    """Write the interactive decision-support workbook.

    Sheet layout matches the current (v2) design: flat ``DATA_*`` sheets
    holding the real numbers, ``APP_WEIGHTS`` as a visible reference
    table, ``SCORES`` (flat app/zone/product/score — restores
    compatibility with ``fig_application_rankings_v4.py``, which reads
    this exact sheet name/shape), and two live sheets driven by
    data-validation dropdowns + ``INDEX``/``MATCH`` formulas:
    ``SELECTOR`` (pick an application + zone, see every product ranked)
    and ``SCORECARD`` (pick a zone + product, see its raw metrics).

    Args:
        out_path: destination .xlsx path.
        validation_by_zone_df: from
            :func:`savana.rainfall.validation.validate_by_zone`.
        validation_overall_df, ranking_df, threshold_df: optional
            companion tables (validate_overall, rank_products,
            threshold_sensitivity outputs) — written as-is if given.
        scores_df: from :func:`score_products`. Computed automatically
            from ``validation_by_zone_df`` + ``app_weights`` if not
            given.
        app_weights, zone_notes: default to
            :data:`config.DEFAULT_APP_WEIGHTS` /
            :data:`config.DEFAULT_ZONE_NOTES`.
    """
    import openpyxl
    from openpyxl.styles import Font, PatternFill
    from openpyxl.utils import get_column_letter
    from openpyxl.worksheet.datavalidation import DataValidation

    app_weights = app_weights if app_weights is not None else config.DEFAULT_APP_WEIGHTS
    zone_notes = zone_notes if zone_notes is not None else config.DEFAULT_ZONE_NOTES

    # Pooled-only runs (no zones assigned) have validation_by_zone_df =
    # None. The workbook still works fine in that case -- we synthesize
    # a single "pooled" zone from the overall table so every sheet
    # (DATA_by_zone, SCORES, and the SELECTOR/SCORECARD dropdowns) has
    # one consistent zone to key on, instead of crashing on None.
    if validation_by_zone_df is None:
        if validation_overall_df is None:
            raise ValueError(
                "build_workbook needs validation_by_zone_df or "
                "validation_overall_df (run validation first)."
            )
        validation_by_zone_df = validation_overall_df.copy()
        if "zone" not in validation_by_zone_df.columns:
            validation_by_zone_df.insert(0, "zone", "pooled")

    if scores_df is None:
        scores_df = score_products(validation_by_zone_df, weights=app_weights)
    elif "zone" not in scores_df.columns:
        scores_df = scores_df.copy()
        scores_df.insert(scores_df.columns.get_loc("product"), "zone", "pooled")

    wb = openpyxl.Workbook()
    wb.remove(wb.active)

    header_fill = PatternFill("solid", fgColor="1A6B1A")
    header_font = Font(color="FFFFFF", bold=True)

    def _write_df(ws, df):
        ws.append(list(df.columns))
        for cell in ws[1]:
            cell.fill = header_fill
            cell.font = header_font
        for row in df.itertuples(index=False):
            ws.append(list(row))
        for i, col in enumerate(df.columns, start=1):
            width = max(10, min(28, int(df[col].astype(str).str.len().max() or 10) + 2))
            ws.column_dimensions[get_column_letter(i)].width = width

    ws_zone = wb.create_sheet("DATA_by_zone")
    _write_df(ws_zone, validation_by_zone_df)

    if validation_overall_df is not None:
        _write_df(wb.create_sheet("DATA_overall"), validation_overall_df)
    if ranking_df is not None:
        _write_df(wb.create_sheet("DATA_ranking"), ranking_df)
    if threshold_df is not None:
        _write_df(wb.create_sheet("DATA_threshold"), threshold_df)

    ws_weights = wb.create_sheet("APP_WEIGHTS")
    metric_cols = sorted({m for w in app_weights.values() for m in w})
    ws_weights.append(["Application"] + metric_cols + ["Primary focus"])
    for cell in ws_weights[1]:
        cell.fill = header_fill
        cell.font = header_font
    focus = config.DEFAULT_APP_FOCUS
    for app, w in app_weights.items():
        ws_weights.append(
            [app] + [w.get(m, 0.0) for m in metric_cols] + [focus.get(app, "")]
        )

    ws_scores = wb.create_sheet("SCORES")
    _write_df(
        ws_scores,
        (
            scores_df[["app", "zone", "product", "score"]]
            if "zone" in scores_df.columns
            else scores_df[["app", "product", "score"]]
        ),
    )

    # ── SELECTOR: dropdown App + Zone -> ranked product table ──
    ws_sel = wb.create_sheet("SELECTOR")
    ws_sel["B2"] = "Select Application:"
    ws_sel["B2"].font = Font(bold=True)
    ws_sel["C2"] = list(app_weights.keys())[0]
    ws_sel["E2"] = "Select Zone:"
    ws_sel["E2"].font = Font(bold=True)
    zones_available = (
        sorted(scores_df["zone"].unique()) if "zone" in scores_df.columns else []
    )
    ws_sel["F2"] = zones_available[0] if zones_available else ""

    dv_app = DataValidation(type="list", formula1=f'"{",".join(app_weights.keys())}"')
    ws_sel.add_data_validation(dv_app)
    dv_app.add(ws_sel["C2"])
    if zones_available:
        dv_zone = DataValidation(type="list", formula1=f'"{",".join(zones_available)}"')
        ws_sel.add_data_validation(dv_zone)
        dv_zone.add(ws_sel["F2"])

    ws_sel["B4"] = "Zone note:"
    ws_sel["B4"].font = Font(bold=True)
    ws_sel["C4"] = (
        "=IFERROR(VLOOKUP(F2, {"
        + ",".join(f'"{z}","{n}"' for z, n in zone_notes.items())
        + '}, 2, FALSE), "")'
    )

    header_row = 6
    ws_sel.cell(header_row, 2, "Rank").font = header_font
    ws_sel.cell(header_row, 3, "Product").font = header_font
    ws_sel.cell(header_row, 4, "Score").font = header_font
    for c in (2, 3, 4):
        ws_sel.cell(header_row, c).fill = header_fill

    # Helper lookup table (hidden columns J:M): app, zone, product, score,
    # plus a concatenated key — same shape as the SCORES sheet, written
    # again here so SELECTOR's formulas don't depend on sheet order.
    key_col, app_col, zone_col, prod_col, score_col = "J", "K", "L", "M", "N"
    ws_sel[f"{app_col}1"], ws_sel[f"{zone_col}1"] = "app", "zone"
    ws_sel[f"{prod_col}1"], ws_sel[f"{score_col}1"] = "product", "score"
    ws_sel[f"{key_col}1"] = "key"
    for i, r in enumerate(scores_df.itertuples(index=False), start=2):
        zone_val = getattr(r, "zone", "")
        ws_sel[f"{app_col}{i}"] = r.app
        ws_sel[f"{zone_col}{i}"] = zone_val
        ws_sel[f"{prod_col}{i}"] = r.product
        ws_sel[f"{score_col}{i}"] = r.score
        ws_sel[f"{key_col}{i}"] = f'={app_col}{i}&"|"&{zone_col}{i}&"|"&{prod_col}{i}'
    last_row = len(scores_df) + 1

    products = sorted(scores_df["product"].unique())
    for i, prod in enumerate(products, start=1):
        r = header_row + i
        ws_sel.cell(r, 2, i)
        ws_sel.cell(r, 3, prod)
        formula = (
            f"=IFERROR(INDEX(${score_col}$2:${score_col}${last_row},"
            f'MATCH($C$2&"|"&$F$2&"|"&"{prod}",'
            f'${key_col}$2:${key_col}${last_row},0)),"")'
        )
        ws_sel.cell(r, 4, formula)

    for col, width in zip("BCDEF", (8, 22, 10, 16, 20)):
        ws_sel.column_dimensions[col].width = width
    for col in (key_col, app_col, zone_col, prod_col, score_col):
        ws_sel.column_dimensions[col].width = 14

    # ── SCORECARD: dropdown Zone + Product -> raw metrics ──
    ws_card = wb.create_sheet("SCORECARD")
    ws_card["B2"] = "Zone:"
    ws_card["B2"].font = Font(bold=True)
    ws_card["C2"] = zones_available[0] if zones_available else ""
    ws_card["D2"] = "Product:"
    ws_card["D2"].font = Font(bold=True)
    ws_card["E2"] = products[0] if products else ""

    if zones_available:
        dv_zone2 = DataValidation(
            type="list", formula1=f'"{",".join(zones_available)}"'
        )
        ws_card.add_data_validation(dv_zone2)
        dv_zone2.add(ws_card["C2"])
    dv_prod = DataValidation(type="list", formula1=f'"{",".join(products)}"')
    ws_card.add_data_validation(dv_prod)
    dv_prod.add(ws_card["E2"])

    metric_report_cols = [
        c for c in validation_by_zone_df.columns if c in config.DEFAULT_METRICS_FLAT
    ]
    n_data_rows = len(validation_by_zone_df) + 1
    for i, m in enumerate(metric_report_cols, start=4):
        ws_card.cell(i, 2, m)
        col_letter = get_column_letter(validation_by_zone_df.columns.get_loc(m) + 1)
        formula = (
            f"=IFERROR(INDEX(DATA_by_zone!${col_letter}$2:${col_letter}${n_data_rows},"
            f"MATCH(1,(DATA_by_zone!$A$2:$A${n_data_rows}=$C$2)*"
            f"(DATA_by_zone!$B$2:$B${n_data_rows}=$E$2),0)))"
        )
        ws_card.cell(i, 3, formula)
    ws_card.column_dimensions["B"].width = 14
    ws_card.column_dimensions["C"].width = 14

    wb.save(out_path)
    print(f"  Decision workbook written: {out_path}")
    return out_path
