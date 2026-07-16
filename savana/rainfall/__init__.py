"""savana.rainfall: comparative evaluation and selection of global
precipitation datasets for natural resource management applications.

Zone-stratified validation of global precipitation products (CHIRPS,
ERA5-Land, GPM IMERG, MERRA-2, PERSIANN-CDR, TerraClimate by default)
against gauge observations, producing an application-weighted decision
matrix for conservation/water-management product selection.

Ships with the West Africa study configuration (16 GPCC FDD v2022
stations, 5 ecological zones, 7 applications) as the default, but every
stage accepts overrides — a different product set, a different gauge
network, a different zone scheme, or different application weights.

Typical use, via the chainable orchestrator::

    from savana.rainfall import RainfallAssessment

    ra = RainfallAssessment().run(start="2001-01-01", end="2020-12-31")
    print(ra.summarize())
    ra.export_workbook("decision_tool.xlsx")

Or call each stage module directly for finer control — see
:mod:`.config`, :mod:`.stations`, :mod:`.zones`, :mod:`.ingestion`,
:mod:`.extraction`, :mod:`.validation`, :mod:`.thresholds`,
:mod:`.spatial`, :mod:`.decision`, :mod:`.insights`, :mod:`.viz`.

Uses the same PEP 562 module-level ``__getattr__`` lazy-loading pattern
as top-level ``savana``: ``import savana.rainfall`` is fast and does
not require ``earthengine-api`` / ``xarray`` / ``openpyxl`` /
``geopandas`` to be importable until a specific symbol is first used.
"""

from __future__ import annotations

import importlib

_LAZY_SYMBOL_MAP: dict[str, tuple[str, str | None]] = {
    # --- config ---
    "DEFAULT_PRODUCTS": ("config", None),
    "DEFAULT_METRICS": ("config", None),
    "DEFAULT_APP_WEIGHTS": ("config", None),
    "DEFAULT_ZONE_NOTES": ("config", None),
    "default_stations_wa": ("config", None),
    # --- pipeline ---
    "RainfallAssessment": ("pipeline", None),
    "validate_against_gpcc": ("pipeline", None),
}

_LAZY_SUBMODULES = {
    "config",
    "stations",
    "zones",
    "ingestion",
    "extraction",
    "validation",
    "thresholds",
    "spatial",
    "decision",
    "insights",
    "viz",
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


__all__ = list(_LAZY_SYMBOL_MAP.keys()) + sorted(_LAZY_SUBMODULES)
