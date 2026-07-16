"""Grounded facts, summary, and Q&A for a rainfall assessment.

Mirrors :mod:`savana.insights`'s pattern exactly: :func:`compute_facts`
computes everything once, with every section independently wrapped so
one failure (e.g. no threshold data was run) doesn't take down the
rest; :func:`summarize` turns facts into readable prose;
:func:`answer` does grounded keyword-based retrieval against the facts
dict. Every number in the output traces back to something actually
computed, never fabricated — the same rule as savana.insights.
"""

from __future__ import annotations

from . import config, decision


def compute_facts(
    scores_df,
    validation_df,
    ranking_df=None,
    threshold_df=None,
    zone_notes: dict | None = None,
) -> dict:
    """Compute every grounded fact available from a rainfall assessment.

    Args:
        scores_df: from :func:`savana.rainfall.decision.score_products`.
        validation_df: from
            :func:`savana.rainfall.validation.validate_by_zone` (or any
            grouped validation output with a ``product`` column).
        ranking_df: optional, from
            :func:`savana.rainfall.validation.rank_products`.
        threshold_df: optional, from
            :func:`savana.rainfall.thresholds.threshold_sensitivity`.
        zone_notes: defaults to :data:`config.DEFAULT_ZONE_NOTES`.

    Returns:
        dict with keys: ``n_products, n_zones, apps, zones, products,
        best_by_app_zone, best_by_app_pooled, top_kge_by_zone,
        threshold_stability, zone_notes, warnings``.
    """
    zone_notes = zone_notes if zone_notes is not None else config.DEFAULT_ZONE_NOTES
    facts: dict = {"warnings": []}

    try:
        facts["products"] = sorted(scores_df["product"].unique())
        facts["apps"] = sorted(scores_df["app"].unique())
        facts["zones"] = (
            sorted(scores_df["zone"].unique()) if "zone" in scores_df.columns else []
        )
        facts["n_products"] = len(facts["products"])
        facts["n_zones"] = len(facts["zones"])
    except Exception as exc:  # noqa: BLE001
        facts["warnings"].append(f"Could not read scores_df structure: {exc}")
        facts["products"], facts["apps"], facts["zones"] = [], [], []
        facts["n_products"], facts["n_zones"] = 0, 0

    try:
        best_by_app_zone = {}
        for app in facts["apps"]:
            best_by_app_zone[app] = {}
            for zone in facts["zones"]:
                prod, score = decision.best_product(scores_df, app, zone)
                if prod is not None:
                    best_by_app_zone[app][zone] = (prod, score)
        facts["best_by_app_zone"] = best_by_app_zone
    except Exception as exc:  # noqa: BLE001
        facts["warnings"].append(f"Could not compute best_by_app_zone: {exc}")
        facts["best_by_app_zone"] = {}

    try:
        best_by_app_pooled = {}
        for app in facts["apps"]:
            prod, score = decision.best_product(scores_df, app, zone=None)
            if prod is not None:
                best_by_app_pooled[app] = (prod, score)
        facts["best_by_app_pooled"] = best_by_app_pooled
    except Exception as exc:  # noqa: BLE001
        facts["warnings"].append(f"Could not compute best_by_app_pooled: {exc}")
        facts["best_by_app_pooled"] = {}

    try:
        top_kge_by_zone = {}
        if "kge" in validation_df.columns and "zone" in validation_df.columns:
            for zone, sub in validation_df.groupby("zone"):
                top = sub.sort_values("kge", ascending=False).iloc[0]
                top_kge_by_zone[zone] = (top["product"], round(float(top["kge"]), 3))
        facts["top_kge_by_zone"] = top_kge_by_zone
    except Exception as exc:  # noqa: BLE001
        facts["warnings"].append(f"Could not compute top_kge_by_zone: {exc}")
        facts["top_kge_by_zone"] = {}

    try:
        worst_bias = {}
        if "pbias" in validation_df.columns and "zone" in validation_df.columns:
            for zone, sub in validation_df.groupby("zone"):
                worst = sub.iloc[sub["pbias"].abs().idxmax() - sub.index[0]]
                worst_bias[zone] = (worst["product"], round(float(worst["pbias"]), 2))
        facts["worst_pbias_by_zone"] = worst_bias
    except Exception as exc:  # noqa: BLE001
        facts["warnings"].append(f"Could not compute worst_pbias_by_zone: {exc}")
        facts["worst_pbias_by_zone"] = {}

    facts["threshold_stability"] = {}
    if threshold_df is not None:
        try:
            from . import thresholds as _thresholds

            stab = _thresholds.stability_summary(threshold_df, metric="csi")
            facts["threshold_stability"] = {
                (row.get("zone", "pooled"), row["product"]): round(float(row["cv"]), 3)
                for row in stab.to_dict("records")
                if row["cv"] == row["cv"]  # drop NaN
            }
        except Exception as exc:  # noqa: BLE001
            facts["warnings"].append(f"Could not compute threshold_stability: {exc}")

    facts["ranking"] = ranking_df
    facts["zone_notes"] = {z: n for z, n in zone_notes.items() if z in facts["zones"]}

    return facts


def summarize(facts: dict) -> str:
    """Turn ``compute_facts()`` output into a readable text summary."""
    lines = []
    lines.append(
        f"Assessed {facts.get('n_products', 0)} precipitation product(s) "
        f"across {facts.get('n_zones', 0)} zone(s): "
        f"{', '.join(facts.get('zones', [])) or 'pooled only'}."
    )

    best_pooled = facts.get("best_by_app_pooled", {})
    if best_pooled:
        lines.append("\nBest product per application (pooled across zones):")
        for app, (prod, score) in best_pooled.items():
            lines.append(f"  - {app}: {prod} (score {score:.3f})")

    top_kge = facts.get("top_kge_by_zone", {})
    if top_kge:
        lines.append("\nBest KGE (primary ranking metric) per zone:")
        for zone, (prod, kge) in top_kge.items():
            lines.append(f"  - {zone}: {prod} (KGE {kge:.3f})")

    worst_bias = facts.get("worst_pbias_by_zone", {})
    if worst_bias:
        lines.append("\nLargest |PBIAS| per zone (worth a closer look before use):")
        for zone, (prod, pbias) in worst_bias.items():
            lines.append(f"  - {zone}: {prod} ({pbias:+.1f}%)")

    zone_notes = facts.get("zone_notes", {})
    if zone_notes:
        lines.append("\nZone notes:")
        for zone, note in zone_notes.items():
            lines.append(f"  - {zone}: {note}")

    if facts.get("warnings"):
        lines.append("\nWarnings (some facts could not be computed):")
        for w in facts["warnings"]:
            lines.append(f"  - {w}")

    return "\n".join(lines)


def answer(facts: dict, question: str) -> str:
    """Grounded keyword-based answer to a question about the assessment.

    Matches application names and zone names appearing (case-insensitive,
    substring) in ``question`` against ``facts``, and reports only what
    was actually computed. Falls back to :func:`summarize` if nothing
    specific matches.
    """
    q = question.lower()

    matched_apps = [a for a in facts.get("apps", []) if a.lower() in q]
    matched_zones = [z for z in facts.get("zones", []) if z.lower() in q]

    if matched_apps and matched_zones:
        lines = []
        for app in matched_apps:
            for zone in matched_zones:
                pair = facts.get("best_by_app_zone", {}).get(app, {}).get(zone)
                if pair:
                    prod, score = pair
                    note = facts.get("zone_notes", {}).get(zone, "")
                    lines.append(
                        f"For {app} in the {zone} zone, {prod} scores highest "
                        f"({score:.3f})." + (f" Note: {note}" if note else "")
                    )
        if lines:
            return "\n".join(lines)

    if matched_apps:
        lines = []
        for app in matched_apps:
            pair = facts.get("best_by_app_pooled", {}).get(app)
            if pair:
                prod, score = pair
                lines.append(
                    f"For {app} (pooled across all zones), {prod} scores highest "
                    f"({score:.3f}). Zone-specific selection is usually preferred "
                    f"— ask about a specific zone for a more precise answer."
                )
        if lines:
            return "\n".join(lines)

    if matched_zones:
        lines = []
        for zone in matched_zones:
            pair = facts.get("top_kge_by_zone", {}).get(zone)
            note = facts.get("zone_notes", {}).get(zone, "")
            if pair:
                prod, kge = pair
                lines.append(
                    f"In the {zone} zone, {prod} has the best overall KGE "
                    f"({kge:.3f})." + (f" Note: {note}" if note else "")
                )
        if lines:
            return "\n".join(lines)

    if "bias" in q or "overestimat" in q or "underestimat" in q:
        worst = facts.get("worst_pbias_by_zone", {})
        if worst:
            lines = [f"  - {z}: {p} ({b:+.1f}%)" for z, (p, b) in worst.items()]
            return "Largest zone-level biases (PBIAS):\n" + "\n".join(lines)

    return (
        "I couldn't match that to a specific application or zone in this "
        "assessment. Here's the full summary instead:\n\n" + summarize(facts)
    )
