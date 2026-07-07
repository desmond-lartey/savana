"""Conservative change detection + Rain-Use-Efficiency inter-annual variability.

Direct port of ``change.js``. Distinguishes genuine structural change
from rainfall-driven apparent change (a common false-positive source in
savanna change detection) using RUE coefficient-of-variation as a filter.
"""

from __future__ import annotations

from . import rue as rue_mod


def _auto_stats_scale(region):
    import ee

    park_area_km2 = region.area().divide(1e6)
    return ee.Number(
        ee.Algorithms.If(
            park_area_km2.lt(500),
            30,
            ee.Algorithms.If(park_area_km2.lt(2000), 100, 500),
        )
    )


def analyse(
    classified_maps: dict,
    epochs: list[int],
    region,
    park_name: str = "AOI",
    rue_cv_threshold: float = 0.15,
) -> dict:
    """Run conservative change detection across all epochs.

    Requires exactly the epochs present as keys in ``classified_maps``;
    the "conservative" and RUE checks specifically use the first and
    last epoch, plus stability through any provided middle epochs.

    Returns a dict with the change stack, conservative/genuine/variable
    change masks, transition codes, RUE-CV image, and per-epoch RUE
    images (keyed ``rue_{year}``).
    """
    import ee

    epochs_sorted = sorted(epochs)
    first_year, last_year = epochs_sorted[0], epochs_sorted[-1]
    stats_scale = _auto_stats_scale(region)

    def band_name(y):
        return f"ls_{y}"

    change_stack = ee.Image.cat(
        [classified_maps[y].rename(band_name(y)) for y in epochs_sorted]
    )

    # Conservative change: stable at both ends of the sequence, but
    # different overall (requires >= 3 epochs to be meaningful; with
    # exactly 2 epochs this reduces to a simple pairwise change mask).
    if len(epochs_sorted) >= 4:
        second_year, second_last_year = epochs_sorted[1], epochs_sorted[-2]
        stable_early = change_stack.select(band_name(first_year)).eq(
            change_stack.select(band_name(second_year))
        )
        stable_late = change_stack.select(band_name(second_last_year)).eq(
            change_stack.select(band_name(last_year))
        )
        conservative_change = (
            stable_early.And(stable_late)
            .And(
                change_stack.select(band_name(first_year)).neq(
                    change_stack.select(band_name(last_year))
                )
            )
            .rename("conservative_change")
        )
        stable_throughout = ee.Image(1).clip(region)
        for a, b in zip(epochs_sorted[:-1], epochs_sorted[1:]):
            stable_throughout = stable_throughout.And(
                change_stack.select(band_name(a)).eq(change_stack.select(band_name(b)))
            )
        stable_throughout = stable_throughout.rename("stable_all_epochs")
    else:
        conservative_change = (
            change_stack.select(band_name(first_year))
            .neq(change_stack.select(band_name(last_year)))
            .rename("conservative_change")
        )
        stable_throughout = conservative_change.Not().rename("stable_all_epochs")

    conservative_transition = (
        change_stack.select(band_name(first_year))
        .multiply(10)
        .add(change_stack.select(band_name(last_year)))
        .updateMask(conservative_change)
        .rename("conservative_transition")
    )

    # RUE inter-annual variability across the same epochs.
    rue_images = {y: rue_mod.epoch_rue(y, region) for y in epochs_sorted}
    rue_stack = ee.Image.cat(list(rue_images.values()))
    rue_cv = (
        rue_stack.reduce(ee.Reducer.stdDev())
        .divide(rue_stack.reduce(ee.Reducer.mean()))
        .rename("RUE_CV")
    )

    genuine_change = conservative_change.And(rue_cv.lt(rue_cv_threshold)).rename(
        f"genuine_change_{first_year}_{last_year}"
    )
    variable_change = conservative_change.And(rue_cv.gte(rue_cv_threshold)).rename(
        f"variable_change_{first_year}_{last_year}"
    )

    result = {
        "change_stack": change_stack,
        "conservative_change": conservative_change,
        "conservative_transition": conservative_transition,
        "stable_throughout": stable_throughout,
        "genuine_change": genuine_change,
        "variable_change": variable_change,
        "rue_cv": rue_cv,
        "stats_scale": stats_scale,
        "first_year": first_year,
        "last_year": last_year,
    }
    for y, img in rue_images.items():
        result[f"rue_{y}"] = img
    return result


def class_area_stats(classified_maps: dict, epochs: list[int], region, scale) -> dict:
    """Per-epoch class area statistics (km2), grouped by class code."""
    import ee

    out = {}
    for year in epochs:
        groups = (
            ee.Image.pixelArea()
            .divide(1e6)
            .addBands(classified_maps[year])
            .reduceRegion(
                reducer=ee.Reducer.sum().group(groupField=1, groupName="landSystem"),
                geometry=region,
                scale=scale,
                maxPixels=1e10,
                tileScale=8,
            )
        )
        out[year] = groups
    return out
