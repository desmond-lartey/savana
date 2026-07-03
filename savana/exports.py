"""Export helpers: Google Drive, Earth Engine Assets, and local CSV/GeoTIFF.

Ports the export logic in ``exports.js``, generalised so the
folder/asset path, CRS, and scale are all parameters instead of
hardcoded to one researcher's Drive folder and asset project.
"""

from __future__ import annotations

from . import config


def export_classified_maps(
    classified_maps: dict,
    epochs: list[int],
    region,
    park_name: str = "AOI",
    drive_folder: str | None = None,
    asset_folder: str | None = None,
    scale: int = config.DEFAULT_EXPORT_SCALE,
    crs: str = config.DEFAULT_CRS,
    start: bool = True,
) -> list:
    """Export each epoch's classified map to Drive and/or an EE Asset folder.

    At least one of ``drive_folder`` / ``asset_folder`` should be given,
    or nothing will be exported. Returns the list of started EE tasks.
    """
    import ee

    tasks = []
    for year in epochs:
        img = classified_maps[year]
        if drive_folder:
            task = ee.batch.Export.image.toDrive(
                image=img,
                description=f"{park_name}_LandSystem_{year}",
                folder=drive_folder,
                fileNamePrefix=f"{park_name}_land_system_{year}",
                region=region,
                scale=scale,
                crs=crs,
                maxPixels=1e10,
            )
            if start:
                task.start()
            tasks.append(task)
        if asset_folder:
            task = ee.batch.Export.image.toAsset(
                image=img,
                description=f"{park_name}_LandSystem_Asset_{year}",
                assetId=f"{asset_folder}/{park_name}/land_system_{year}",
                region=region,
                scale=scale,
                crs=crs,
                maxPixels=1e10,
                pyramidingPolicy={".default": "MODE"},
            )
            if start:
                task.start()
            tasks.append(task)
    return tasks


def export_change_products(
    chg: dict,
    region,
    park_name: str = "AOI",
    drive_folder: str | None = None,
    asset_folder: str | None = None,
    scale: int = config.DEFAULT_EXPORT_SCALE,
    crs: str = config.DEFAULT_CRS,
    start: bool = True,
) -> list:
    """Export change-detection and RUE products to Drive and/or Assets."""
    import ee

    tasks = []

    def _drive(image, name_suffix, sub_scale=None):
        if not drive_folder:
            return
        task = ee.batch.Export.image.toDrive(
            image=image,
            description=f"{park_name}_{name_suffix}",
            folder=drive_folder,
            fileNamePrefix=f"{park_name}_{name_suffix.lower()}",
            region=region,
            scale=sub_scale or scale,
            crs=crs,
            maxPixels=1e10,
        )
        if start:
            task.start()
        tasks.append(task)

    def _asset(image, name_suffix, sub_scale=None):
        if not asset_folder:
            return
        task = ee.batch.Export.image.toAsset(
            image=image,
            description=f"{park_name}_{name_suffix}_Asset",
            assetId=f"{asset_folder}/{park_name}/{name_suffix.lower()}",
            region=region,
            scale=sub_scale or scale,
            crs=crs,
            maxPixels=1e10,
            pyramidingPolicy={".default": "MODE"},
        )
        if start:
            task.start()
        tasks.append(task)

    _drive(chg["conservative_change"].toByte(), "ConservativeChange")
    _drive(chg["conservative_transition"].toByte(), "ConservativeTransition")
    _asset(chg["conservative_change"].toByte(), "ConservativeChange")

    _drive(chg["genuine_change"].toByte(), "GenuineChange")
    _asset(chg["genuine_change"].toByte(), "GenuineChange")

    _drive(chg["rue_cv"].toFloat(), "RUE_CV", sub_scale=100)
    _asset(chg["rue_cv"].toFloat(), "RUE_CV", sub_scale=100)

    return tasks


def class_areas_dataframe(classified_maps: dict, epochs: list[int], region, scale: int):
    """Client-side (getInfo) per-epoch class area table as a pandas DataFrame."""
    import pandas as pd

    from . import change as change_mod

    stats = change_mod.class_area_stats(classified_maps, epochs, region, scale)
    rows = []
    for year, groups_ee in stats.items():
        groups = groups_ee.getInfo().get("groups", [])
        for g in groups:
            rows.append({"year": year, "landSystem": g["landSystem"], "area_km2": g["sum"]})
    return pd.DataFrame(rows)
