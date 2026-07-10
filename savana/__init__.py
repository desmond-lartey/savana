"""savana: adaptive classification of complex savanna landscapes.

Classifies savanna landscapes into ecologically meaningful land-system
management classes (e.g. Core Woodland, Open Woodland, Shrub-Transition,
Grassland, Riparian, Anthropogenic Disturbance) using Sentinel-2,
AlphaEarth satellite embeddings, and rainfall data on Google Earth
Engine — filling a gap left by conventional LULC products, which
typically lump all savanna structure into one or two undifferentiated
"grass/shrub" classes.

Quick start
-----------
>>> import savana
>>> clf = savana.classify_landscape(
...     aoi="path/to/my_area.geojson",
...     epochs=[2019, 2021, 2024],
...     park_name="My Study Area",
... )
>>> clf.show()                  # interactive map in Jupyter
>>> clf.accuracy_summary()      # pandas.DataFrame

For AI-assisted exploration of your results (grounded Q&A + map control
+ chat UI, all in one place):
>>> from savana.agents import SavanaGeoAgent
>>> agent = SavanaGeoAgent(clf, model="anthropic")
>>> agent.ask("How much core woodland is there in 2024?")
>>> agent.show_ui()             # live map + chat, inline in the notebook

Uses PEP 562 module-level ``__getattr__`` for lazy imports, so
``import savana`` is fast and does not require ``earthengine-api`` /
``geemap`` / ``pandas`` to be importable until a specific symbol is
first used.
"""

from __future__ import annotations

import importlib

__author__ = "Desmond Lartey"
__version__ = "0.1.10"

_LAZY_SYMBOL_MAP = {
    # --- savana.pipeline ---
    "SavanaClassifier": ("pipeline", None),
    "classify_landscape": ("pipeline", None),
    # --- savana.ee_init ---
    "initialize": ("ee_init", None),
    "load_aoi": ("ee_init", None),
    # --- savana.composites ---
    "sentinel2_annual": ("composites", None),
    "seasonal_composite": ("composites", None),
    "percentile_composites": ("composites", None),
    "embedding_image": ("composites", None),
    # --- savana.indices ---
    "compute_indices": ("indices", "compute"),
    "build_pheno_stack": ("indices", None),
    # --- savana.rue ---
    "compute_annual_rue": ("rue", "compute_annual"),
    "epoch_rue": ("rue", None),
    # --- savana.thresholds ---
    "compute_thresholds": ("thresholds", "compute"),
    # --- savana.masks ---
    "compute_masks": ("masks", "compute"),
    "mask_coverage": ("masks", "coverage"),
    # --- savana.sampling ---
    "cluster_embedding": ("sampling", None),
    "sample_candidates": ("sampling", None),
    "assign_labels": ("sampling", None),
    "build_gcps": ("sampling", None),
    # --- savana.classifiers ---
    "train_all_models": ("classifiers", None),
    "classify_all_epochs": ("classifiers", None),
    # --- savana.change ---
    "analyse_change": ("change", "analyse"),
    "class_area_stats": ("change", None),
    # --- savana.accuracy ---
    "confusion_matrix_dataframe": ("accuracy", None),
    "summary_dataframe": ("accuracy", None),
    "print_accuracy_summary": ("accuracy", "print_summary"),
    # --- savana.exports ---
    "export_classified_maps": ("exports", None),
    "export_change_products": ("exports", None),
    "class_areas_dataframe": ("exports", None),
    # --- savana.viz ---
    "show_classified_map": ("viz", None),
    "show_change_map": ("viz", None),
    "add_legend": ("viz", None),
    # --- savana.viz_geolibre (optional: pip install savana[geolibre]) ---
    "show_classified_map_geolibre": ("viz_geolibre", "show_classified_map"),
    "show_multi_year_map_geolibre": ("viz_geolibre", "show_multi_year_map"),
    # --- savana.insights (grounded facts / summaries / Q&A) ---
    "compute_facts": ("insights", None),
    "summarize_facts": ("insights", "summarize"),
    "answer_facts": ("insights", "answer"),
    # --- savana.agents (optional: pip install savana[agents]) ---
    "SavanaGeoAgent": ("agents", None),
    # --- savana.config ---
    "DEFAULT_CLASS_INFO": ("config", None),
    "class_palette": ("config", None),
    "class_vis_params": ("config", None),
}

_LAZY_SUBMODULES = {
    "config",
    "ee_init",
    "composites",
    "indices",
    "rue",
    "thresholds",
    "masks",
    "sampling",
    "classifiers",
    "change",
    "accuracy",
    "exports",
    "viz",
    "viz_geolibre",
    "insights",
    "agents",
    "pipeline",
}


def __getattr__(name):
    if name in _LAZY_SUBMODULES:
        mod = importlib.import_module(f".{name}", __name__)
        globals()[name] = mod
        return mod

    if name in _LAZY_SYMBOL_MAP:
        module_rel, original_name = _LAZY_SYMBOL_MAP[name]
        attr_name = original_name or name
        mod = importlib.import_module(f".{module_rel}", __name__)
        val = getattr(mod, attr_name)
        globals()[name] = val
        return val

    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def __dir__():
    return sorted(
        set(globals().keys()) | set(_LAZY_SYMBOL_MAP.keys()) | _LAZY_SUBMODULES
    )


__all__ = list(_LAZY_SYMBOL_MAP.keys())
