"""Grounded analytical insights: knowledge derived only from real results.

The design principle here is deliberate: every number in ``summarize()``
and ``answer()`` traces back to something actually computed by the
pipeline (``class_areas()``, ``accuracy_summary()``, the change-detection
stats), never invented, interpolated, or guessed. ``compute_facts()``
is the single source of truth; both text-producing functions only ever
read from it. This keeps savana's reporting honest even as it grows,
if a future version adds LLM-phrased summaries, that layer should sit
*on top* of these same facts, never replace them.
"""

from __future__ import annotations


def compute_facts(clf) -> dict:
    """Extract a structured dict of real, computed facts from a fitted classifier.

    Requires ``clf.run()`` (or at least ``.classify()``) to have completed.
    This is the "knowledge base", everything else in this module reads
    from its output, never from the raw ee.Image objects directly.

    Each section (area, accuracy, change) is computed independently and
    guarded against Earth Engine timeouts, a slow/large AOI causing one
    section to time out will not prevent the others from returning. Any
    section that fails is set to ``None`` and noted in ``facts["warnings"]``
    rather than raising, since a partial, honest answer is better than a
    hard crash on results that mostly did compute successfully.
    """
    info = clf.class_info
    class_names = {code: v["name"] for code, v in info.items()}
    epochs = sorted(clf.epochs)

    facts: dict = {
        "park_name": clf.park_name,
        "epochs": epochs,
        "class_names": class_names,
        "area_by_epoch": {},  # {year: {class_name: km2}}
        "pct_by_epoch": {},  # {year: {class_name: pct_of_total}}
        "total_area_km2": {},  # {year: total_km2}
        "dominant_class": {},  # {year: class_name}
        "accuracy": None,
        "change": None,
        "warnings": [],
    }

    # --- Area stats (per-epoch class areas) ---
    try:
        areas_df = clf.class_areas()
        for year in epochs:
            year_rows = areas_df[areas_df["year"] == year]
            by_class = {}
            for _, row in year_rows.iterrows():
                code = int(row["landSystem"])
                name = class_names.get(code, f"class_{code}")
                by_class[name] = float(row["area_km2"])
            total = sum(by_class.values())
            facts["area_by_epoch"][year] = by_class
            facts["total_area_km2"][year] = total
            pct = {}
            if total > 0:
                for name, area in by_class.items():
                    pct[name] = round(100 * area / total, 1)
            facts["pct_by_epoch"][year] = pct
            facts["dominant_class"][year] = (
                max(by_class, key=by_class.get) if by_class else None
            )
    except (
        Exception
    ) as exc:  # noqa: BLE001 - deliberately broad: any EE failure here is non-fatal
        facts["warnings"].append(
            f"Area statistics unavailable ({type(exc).__name__}: {exc})."
        )

    # --- Accuracy, best model by overall accuracy, plus the primary model (D) specifically ---
    try:
        acc_df = clf.accuracy_summary()
        if acc_df is not None and len(acc_df) > 0:
            best_row = acc_df.loc[acc_df["overall_accuracy"].idxmax()]
            primary_row = acc_df[acc_df["model_code"] == "D"]
            primary_oa = None
            primary_kappa = None
            if len(primary_row):
                primary_oa = round(float(primary_row.iloc[0]["overall_accuracy"]), 4)
                primary_kappa = round(float(primary_row.iloc[0]["kappa"]), 4)
            facts["accuracy"] = {
                "best_model_code": best_row["model_code"],
                "best_model_description": best_row["model_description"],
                "best_overall_accuracy": round(float(best_row["overall_accuracy"]), 4),
                "best_kappa": round(float(best_row["kappa"]), 4),
                "primary_model_accuracy": primary_oa,
                "primary_model_kappa": primary_kappa,
            }
    except Exception as exc:  # noqa: BLE001
        facts["warnings"].append(
            f"Accuracy statistics unavailable ({type(exc).__name__}: {exc})."
        )

    # --- Change detection, only attempted if >= 2 epochs were run ---
    if clf.change is not None:
        try:
            chg = clf.change
            first_year, last_year = chg["first_year"], chg["last_year"]
            # Single combined image + single reduceRegion call instead of two
            # separate ones, halves the round trips to Earth Engine for this section.
            combined = (
                chg["conservative_change"]
                .unmask(0)
                .rename("conservative")
                .addBands(chg["genuine_change"].unmask(0).rename("genuine"))
            )
            stats = combined.reduceRegion(
                reducer=_mean_reducer(),
                geometry=clf.region,
                scale=chg["stats_scale"],
                maxPixels=1e10,
                tileScale=8,
                bestEffort=True,
            ).getInfo()
            conservative_frac = stats.get("conservative", 0) or 0
            genuine_frac = stats.get("genuine", 0) or 0
            facts["change"] = {
                "first_year": first_year,
                "last_year": last_year,
                "conservative_change_pct_of_area": round(100 * conservative_frac, 2),
                "genuine_change_pct_of_area": round(100 * genuine_frac, 2),
                "variable_change_pct_of_area": round(
                    100 * (conservative_frac - genuine_frac), 2
                ),
            }
        except Exception as exc:  # noqa: BLE001
            facts["warnings"].append(
                f"Change statistics unavailable ({type(exc).__name__}: {exc})."
            )

    return facts


def _mean_reducer():
    import ee

    return ee.Reducer.mean()


def summarize(facts: dict) -> str:
    """Turn a facts dict into a plain-English narrative report."""
    lines = []
    park = facts["park_name"]
    epochs = facts["epochs"]

    lines.append(
        f"Land-system classification summary for {park} ({', '.join(map(str, epochs))}):"
    )
    lines.append("")

    for year in epochs:
        total = facts["total_area_km2"].get(year, 0)
        dominant = facts["dominant_class"].get(year)
        pct = facts["pct_by_epoch"].get(year, {})
        lines.append(f"{year}: total classified area {total:.1f} km2.")
        if dominant:
            lines.append(
                f"  Dominant class: {dominant} ({pct.get(dominant, 0)}% of the area)."
            )
        for name, p in sorted(pct.items(), key=lambda kv: -kv[1]):
            area = facts["area_by_epoch"][year].get(name, 0)
            lines.append(f"  - {name}: {area:.1f} km2 ({p}%)")
        lines.append("")

    if facts.get("accuracy"):
        acc = facts["accuracy"]
        if acc["primary_model_accuracy"] is not None:
            lines.append(
                f"Model accuracy: the primary model (embeddings + phenology) reached "
                f"{acc['primary_model_accuracy']:.1%} overall accuracy "
                f"(kappa {acc['primary_model_kappa']:.3f})."
            )
        else:
            lines.append("Model accuracy: primary model results unavailable.")
        lines.append(
            f"Best-performing model overall: {acc['best_model_description']} "
            f"({acc['best_overall_accuracy']:.1%} accuracy, kappa {acc['best_kappa']:.3f})."
        )
        lines.append("")

    if facts.get("change"):
        chg = facts["change"]
        lines.append(
            f"Change {chg['first_year']} to {chg['last_year']}: "
            f"{chg['conservative_change_pct_of_area']}% of the area shows conservative "
            f"(stable-to-stable) land-system change."
        )
        lines.append(
            f"  Of that, {chg['genuine_change_pct_of_area']}% of the total area is genuine "
            f"structural change (validated against rainfall variability), while "
            f"{chg['variable_change_pct_of_area']}% appears to be rainfall-driven apparent "
            f"change rather than true land-system conversion."
        )

    if facts.get("warnings"):
        lines.append("")
        lines.append("Note: some sections could not be computed and are omitted above:")
        for w in facts["warnings"]:
            lines.append(f"  - {w}")

    return "\n".join(lines)


def answer(facts: dict, question: str) -> str:
    """Answer a natural-language question using only precomputed facts.

    This is deliberately simple keyword matching, not an LLM, it can
    only ever report numbers that are actually in ``facts``, so it
    cannot hallucinate a result the pipeline didn't produce. Questions
    it doesn't recognise get an honest "don't know" rather than a guess.
    """
    q = question.lower()
    epochs = facts["epochs"]
    class_names = list(facts["class_names"].values())

    # Which epoch is being asked about? Default to the most recent.
    year = next((y for y in epochs if str(y) in q), epochs[-1])

    # Does the question mention a specific class?
    matched_class = next((name for name in class_names if name.lower() in q), None)

    if any(w in q for w in ["change", "lost", "gained", "convert"]) and facts.get(
        "change"
    ):
        chg = facts["change"]
        return (
            f"Between {chg['first_year']} and {chg['last_year']}, "
            f"{chg['genuine_change_pct_of_area']}% of {facts['park_name']}'s area shows genuine "
            f"structural land-system change; a further {chg['variable_change_pct_of_area']}% shows "
            f"apparent change that's more likely rainfall-driven variability than real conversion."
        )

    if any(w in q for w in ["accura", "model", "reliab", "confidence"]) and facts.get(
        "accuracy"
    ):
        acc = facts["accuracy"]
        return (
            f"The primary classification model (AlphaEarth embeddings + phenology) achieved "
            f"{acc['primary_model_accuracy']:.1%} overall accuracy "
            f"(kappa {acc['primary_model_kappa']:.3f}) for {facts['park_name']}."
        )

    if matched_class:
        area = facts["area_by_epoch"].get(year, {}).get(matched_class)
        pct = facts["pct_by_epoch"].get(year, {}).get(matched_class)
        if area is not None:
            return (
                f"In {year}, {matched_class} covered {area:.1f} km2 "
                f"({pct}% of {facts['park_name']})."
            )
        return f"No {matched_class} area was found for {year} in the computed results."

    if any(w in q for w in ["dominant", "most", "largest", "majority"]):
        dominant = facts["dominant_class"].get(year)
        pct = facts["pct_by_epoch"].get(year, {}).get(dominant)
        return (
            f"The dominant land-system class in {year} was {dominant} "
            f"({pct}% of {facts['park_name']})."
        )

    if any(w in q for w in ["total", "area", "size", "how big"]):
        total = facts["total_area_km2"].get(year)
        return f"The total classified area of {facts['park_name']} in {year} was {total:.1f} km2."

    return (
        "I can only answer from what the pipeline actually computed, try asking about "
        "a specific class's area, the dominant class, overall accuracy, or change between years."
    )
