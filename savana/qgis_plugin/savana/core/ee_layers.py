"""Render Earth Engine imagery on the QGIS canvas.

``geemap.Map`` is a Jupyter widget and cannot render inside QGIS, so the
notebook's ``preview_*`` functions have no direct equivalent here.
Instead we use Earth Engine's own tile server: ``ee.Image.getMapId()``
returns a template URL serving rendered XYZ tiles, which QGIS loads as a
normal raster layer via its built-in ``wms``/XYZ provider.

Practical consequence worth knowing: these are *server-rendered preview
tiles*, not downloaded rasters. They display, zoom, and stack with your
own layers, but QGIS raster analysis can't run on them — for that, use
the module's Drive/Asset export instead.

The functions here run in two different places, so they're split:

- :func:`build_tile_script` produces Python source to run **in the
  managed venv** (where ``ee`` is installed), which resolves an image to
  a tile URL and prints it as JSON.
- :func:`add_xyz_layer` runs **in QGIS**, turning that URL into a layer.

Panels therefore call ``build_tile_script`` in a worker, then
``add_xyz_layer`` when the result comes back.
"""

from __future__ import annotations

import json
from typing import Optional

from qgis.core import QgsProject, QgsRasterLayer


def add_xyz_layer(tile_url: str, name: str, group: Optional[str] = None):
    """Add an EE XYZ tile URL to the QGIS project as a raster layer.

    Args:
        tile_url: an XYZ template url ending in ``/{z}/{x}/{y}``.
        name: layer name shown in the Layers panel.
        group: optional layer-group name to file it under.

    Returns:
        The created ``QgsRasterLayer``, or None if it wasn't valid.
    """
    # QGIS's XYZ tile support is exposed through the "wms" provider with
    # a type=xyz uri; the url must be percent-encoded within the uri.
    encoded = tile_url.replace("=", "%3D").replace("&", "%26")
    uri = f"type=xyz&url={encoded}&zmin=0&zmax=16"
    layer = QgsRasterLayer(uri, name, "wms")
    if not layer.isValid():
        return None

    project = QgsProject.instance()
    if group:
        root = project.layerTreeRoot()
        node = root.findGroup(group) or root.insertGroup(0, group)
        project.addMapLayer(layer, False)
        node.insertLayer(0, layer)
    else:
        project.addMapLayer(layer)
    return layer


def build_tile_script(
    image_expr: str, vis_params: dict, results_path: str, setup: str = ""
) -> str:
    """Build venv-side Python that resolves an EE image to a tile URL.

    Args:
        image_expr: a Python expression evaluating to an ``ee.Image``,
            evaluated after ``setup`` has run.
        vis_params: EE visualisation parameters (min/max/palette/bands).
        results_path: file to write ``{"tile_url": ...}`` JSON into.
        setup: extra source run before ``image_expr`` — typically the
            code that rebuilds the analysis object the image comes from.

    Returns:
        Python source suitable for :func:`run_script_in_thread`.
    """
    return f'''
import json

{setup}

_img = {image_expr}
_vis = json.loads(r"""{json.dumps(vis_params)}""")
_mapid = _img.getMapId(_vis)

# earthengine-api returns either a ready tile_fetcher (newer versions)
# or a raw mapid/token pair (older) -- support both so the plugin isn't
# pinned to one earthengine-api release.
_fetcher = _mapid.get("tile_fetcher") if isinstance(_mapid, dict) else None
if _fetcher is not None:
    _url = _fetcher.url_format
else:
    _url = (
        "https://earthengine.googleapis.com/v1alpha/"
        + str(_mapid["mapid"])
        + "/tiles/{{z}}/{{x}}/{{y}}"
    )

with open(r"{results_path}", "w", encoding="utf-8") as _f:
    json.dump({{"tile_url": _url}}, _f)

print("TILE_URL_READY")
'''


def read_tile_url(results_path: str) -> Optional[str]:
    """Read the tile url written by a build_tile_script run."""
    try:
        with open(results_path, encoding="utf-8") as f:
            return json.load(f).get("tile_url")
    except (OSError, json.JSONDecodeError):
        return None
