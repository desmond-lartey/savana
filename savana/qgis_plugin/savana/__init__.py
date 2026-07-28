"""Savana Plugin for QGIS.

Brings the savana Python package (land-system classification and
precipitation product assessment) into QGIS as dockable analysis panels
under one hub, backed by a managed Python environment and a shared
Google Earth Engine connection.
"""


def classFactory(iface):  # noqa: N802 (QGIS-mandated name)
    """Load the SavanaPlugin class.

    Args:
        iface: A QGIS interface instance provided by QGIS at load time.

    Returns:
        SavanaPlugin: The plugin instance.
    """
    from .savana_plugin import SavanaPlugin

    return SavanaPlugin(iface)
