"""Precipitation Product Assessment dock panel.

Wraps ``savana.rainfall.validate_against_gpcc`` behind a QGIS form:
pick stations, products, and a year range; the assessment runs in the
managed venv on a worker thread; results come back as CSV files that are
loaded into QGIS (the per-station results as a point layer, the
validation tables as attribute-table layers) plus the decision workbook
saved to disk.

The savana call is emitted as a small self-contained script that reads a
JSON params file and writes a JSON results file (listing output paths),
so nothing savana-related needs to be importable in QGIS's own Python.
"""

from __future__ import annotations

import json
import os
import tempfile

from qgis.core import QgsProject, QgsVectorLayer
from qgis.PyQt.QtWidgets import (
    QComboBox,
    QDockWidget,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPlainTextEdit,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from ..core import ee_connection, venv_manager
from ..workers.subprocess_worker import run_script_in_thread
from .ui_helpers import PanelScaffold, make_status_label, set_status

PRODUCTS = [
    "CHIRPS",
    "PERSIANN_CDR",
    "GPM_IMERG",
    "ERA5_LAND",
    "MERRA2",
    "TERRACLIMATE",
]

# Mirrors savana.rainfall.config.DEFAULT_VIS_PARAMS. Duplicated here
# deliberately: this module runs in QGIS's Python, where savana isn't
# importable (it lives in the managed venv), so the values can't be read
# from the package at runtime.
_VIS_PARAMS = {
    "daily": {
        "min": 0,
        "max": 12,
        "palette": ["#E3F2FD", "#90CAF9", "#1565C0", "#0D47A1", "#01002E"],
    },
    "annual": {
        "min": 0,
        "max": 2500,
        "palette": ["#FFFDE7", "#FFF59D", "#FFCC02", "#FF8F00", "#E65100"],
    },
    "bias": {
        "min": -5,
        "max": 5,
        "palette": ["#B71C1C", "#EF9A9A", "#FFFFFF", "#90CAF9", "#0D47A1"],
    },
}


class RainfallDockWidget(QDockWidget):
    """Dockable Precipitation Product Assessment panel."""

    def __init__(self, iface, parent=None):
        super().__init__("Savana - Precipitation Assessment", parent)
        self.iface = iface
        self.setObjectName("SavanaRainfallDock")
        self._thread = None
        self._worker = None
        # Params of the last successful run, reused to rebuild the
        # assessment when the user asks for a map layer.
        self._last_params = None
        self._tiles_path = None
        self._pending_layer_name = ""

        scaffold = PanelScaffold(
            title="Precipitation Product Assessment",
            subtitle=(
                "Validate global rainfall products against GPCC gauge "
                "observations, then rank them for your application."
            ),
            link="https://github.com/desmond-lartey/savana",
        )
        scaffold.add_tab(self._build_run_tab(), "Run")
        scaffold.add_tab(self._build_maps_tab(), "Maps")
        self.progress = scaffold.progress
        self.setWidget(scaffold.finish())

    # -- tabs -----------------------------------------------------------

    def _build_run_tab(self) -> QWidget:
        tab = QWidget()
        v = QVBoxLayout(tab)
        v.addWidget(self._build_inputs_group())
        v.addWidget(self._build_products_group())

        self.run_status = make_status_label("Ready.")
        v.addWidget(self.run_status)

        self.run_btn = QPushButton("Run assessment")
        self.run_btn.clicked.connect(self._on_run)
        v.addWidget(self.run_btn)

        v.addWidget(QLabel("Log:"))
        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setMaximumBlockCount(2000)
        v.addWidget(self.log)
        return tab

    def _build_maps_tab(self) -> QWidget:
        tab = QWidget()
        v = QVBoxLayout(tab)
        v.addWidget(self._build_map_group())
        v.addStretch(1)
        return tab

    # -- UI -------------------------------------------------------------

    def _build_inputs_group(self) -> QGroupBox:
        group = QGroupBox("Stations & period")
        form = QFormLayout(group)

        self.stations_edit = QLineEdit()
        self.stations_edit.setPlaceholderText(
            "blank = 16 default WA stations, or lon,lat  or  path to .geojson/.csv"
        )
        form.addRow("Stations:", self.stations_edit)

        self.obs_source = QComboBox()
        self.obs_source.addItems(["download", "ee_asset"])
        form.addRow("GPCC source:", self.obs_source)

        yr = QHBoxLayout()
        self.start_year = QSpinBox()
        self.start_year.setRange(1981, 2024)
        self.start_year.setValue(2020)
        self.end_year = QSpinBox()
        self.end_year.setRange(1981, 2024)
        self.end_year.setValue(2020)
        yr.addWidget(QLabel("from"))
        yr.addWidget(self.start_year)
        yr.addWidget(QLabel("to"))
        yr.addWidget(self.end_year)
        wrap = QWidget()
        wrap.setLayout(yr)
        form.addRow("Years:", wrap)

        return group

    def _build_map_group(self) -> QGroupBox:
        """Map layers are shown on demand, not auto-loaded.

        Each button costs an Earth Engine getMapId call and adds a layer
        to the canvas, so the user asks for exactly the ones they want
        rather than having every product dumped on them after a run.
        """
        group = QGroupBox("Map layers (after a run)")
        v = QVBoxLayout(group)

        self.map_status = make_status_label("Run an assessment first.")
        v.addWidget(self.map_status)

        row = QHBoxLayout()
        row.addWidget(QLabel("Product:"))
        self.map_product = QComboBox()
        self.map_product.addItems(PRODUCTS)
        row.addWidget(self.map_product)
        v.addLayout(row)

        self.mean_map_btn = QPushButton("Show mean rainfall map")
        self.mean_map_btn.clicked.connect(self._on_show_mean_map)
        self.mean_map_btn.setEnabled(False)
        v.addWidget(self.mean_map_btn)

        ref_row = QHBoxLayout()
        ref_row.addWidget(QLabel("vs:"))
        self.map_reference = QComboBox()
        self.map_reference.addItems(PRODUCTS)
        if self.map_reference.count() > 1:
            self.map_reference.setCurrentIndex(1)
        ref_row.addWidget(self.map_reference)
        v.addLayout(ref_row)

        self.bias_map_btn = QPushButton("Show inter-product bias map")
        self.bias_map_btn.clicked.connect(self._on_show_bias_map)
        self.bias_map_btn.setEnabled(False)
        v.addWidget(self.bias_map_btn)

        note = QLabel(
            "Bias compares two gridded products, never GPCC (GPCC is "
            "point gauge data). Station points load with the results."
        )
        note.setWordWrap(True)
        v.addWidget(note)

        return group

    def _on_show_mean_map(self):
        product = self.map_product.currentText()
        self._show_map_layer(
            image_expr=(f'_ra.products_ic["{product}"].select("precip_mm_day").mean()'),
            vis_key="daily",
            layer_name=f"Mean daily rainfall - {product}",
        )

    def _on_show_bias_map(self):
        product = self.map_product.currentText()
        reference = self.map_reference.currentText()
        if product == reference:
            self._log("Pick two different products to compare.")
            return
        self._show_map_layer(
            image_expr=(
                f'_ra.products_ic["{product}"].select("precip_mm_day").mean()'
                f".subtract("
                f'_ra.products_ic["{reference}"].select("precip_mm_day").mean())'
            ),
            vis_key="bias",
            layer_name=f"Bias (mm/d) - {product} vs {reference}",
        )

    def _show_map_layer(self, image_expr: str, vis_key: str, layer_name: str):
        """Resolve an EE image to tiles in the venv, then add to canvas."""
        if not self._last_params:
            self._log("Run an assessment first, then show map layers.")
            return

        import tempfile

        from ..core import ee_layers

        p = self._last_params
        tiles_path = os.path.join(
            tempfile.mkdtemp(prefix="savana_tiles_"), "tiles.json"
        )
        self._tiles_path = tiles_path
        self._pending_layer_name = layer_name

        products_arg = "None" if not p["products"] else repr(p["products"])
        setup = (
            "from savana.rainfall import RainfallAssessment\n"
            "from savana.rainfall import config as _cfg\n"
            f"_prods = {products_arg}\n"
            "_sel = None if _prods is None else "
            "{k: _cfg.DEFAULT_PRODUCTS[k] for k in _prods}\n"
            "_ra = RainfallAssessment(\n"
            f"    stations={p['stations']!r},\n"
            "    products=_sel,\n"
            f"    ee_project={p['ee_project']!r},\n"
            ")\n"
            f"_ra.ingest(start='{p['start_year']}-01-01', "
            f"end='{p['end_year']}-12-31')\n"
        )
        vis = _VIS_PARAMS[vis_key]
        script = ee_layers.build_tile_script(image_expr, vis, tiles_path, setup=setup)

        self._log(f"Building map layer: {layer_name} ...")
        set_status(self.map_status, f"Building {layer_name}...", "busy")
        self._set_busy(True)
        python = venv_manager.get_venv_python_path()
        self._thread, self._worker = run_script_in_thread(
            python,
            script,
            on_progress=self._log,
            on_finished=self._on_tiles_ready,
        )

    def _on_tiles_ready(self, ok: bool, msg: str):
        self._set_busy(False)
        if not ok:
            set_status(self.map_status, "Map layer failed - see log.", "error")
            self._log("Map layer failed:\n" + msg)
            return
        set_status(self.map_status, "Map layer added.", "ok")

        from ..core import ee_layers

        url = ee_layers.read_tile_url(self._tiles_path)
        if not url:
            self._log("No tile URL was produced.")
            return
        layer = ee_layers.add_xyz_layer(url, self._pending_layer_name, group="Savana")
        if layer is None:
            self._log("QGIS could not create the tile layer.")
        else:
            self._log(f"Added map layer: {self._pending_layer_name}")

    def _build_products_group(self) -> QGroupBox:
        group = QGroupBox("Products (none selected = all 6)")
        v = QVBoxLayout(group)
        self.product_list = QListWidget()
        self.product_list.setSelectionMode(QListWidget.MultiSelection)
        for p in PRODUCTS:
            self.product_list.addItem(QListWidgetItem(p))
        self.product_list.setMaximumHeight(120)
        v.addWidget(self.product_list)
        return group

    # -- run ------------------------------------------------------------

    def _prerequisites_ok(self) -> bool:
        ready, msg = venv_manager.get_venv_status()
        if not ready:
            self._log(f"Environment not ready: {msg}\nOpen the Setup panel first.")
            return False
        if not ee_connection.is_configured():
            self._log("No Earth Engine project set. Open the Setup panel first.")
            return False
        return True

    def _on_run(self):
        if not self._prerequisites_ok():
            return

        selected = [i.text() for i in self.product_list.selectedItems()]
        params = {
            "stations": self.stations_edit.text().strip() or None,
            "products": selected or None,
            "start_year": self.start_year.value(),
            "end_year": self.end_year.value(),
            "obs_source": self.obs_source.currentText(),
            "ee_project": ee_connection.get_project(),
            "out_dir": tempfile.mkdtemp(prefix="savana_rainfall_"),
        }

        self._last_params = params
        params_path = os.path.join(params["out_dir"], "params.json")
        with open(params_path, "w", encoding="utf-8") as f:
            json.dump(params, f)

        self._results_path = os.path.join(params["out_dir"], "results.json")
        script = _build_script(params_path, self._results_path)

        self._log(f"Running assessment (outputs -> {params['out_dir']}) ...")
        set_status(self.run_status, "Running assessment...", "busy")
        self._set_busy(True)
        python = venv_manager.get_venv_python_path()
        self._thread, self._worker = run_script_in_thread(
            python,
            script,
            on_progress=self._log,
            on_finished=self._on_finished,
        )

    def _on_finished(self, ok: bool, msg: str):
        self._set_busy(False)
        if not ok:
            set_status(self.run_status, "Assessment failed - see log.", "error")
            self._log("FAILED:\n" + msg)
            return
        set_status(self.run_status, "Assessment complete.", "ok")
        self._log("Assessment finished. Loading results...")
        self._load_results()
        # Map layers need an ingested assessment, so they only become
        # available once a run has actually completed.
        self.mean_map_btn.setEnabled(True)
        self.bias_map_btn.setEnabled(True)
        set_status(self.map_status, "Ready - pick a product and show a map.", "ok")

    def _load_results(self):
        try:
            with open(self._results_path, encoding="utf-8") as f:
                results = json.load(f)
        except (OSError, json.JSONDecodeError) as exc:
            self._log(f"Could not read results file: {exc}")
            return

        # Per-station point layer (from a GeoJSON the script wrote).
        stations_geojson = results.get("stations_geojson")
        if stations_geojson and os.path.exists(stations_geojson):
            layer = QgsVectorLayer(stations_geojson, "Rainfall stations", "ogr")
            if layer.isValid():
                QgsProject.instance().addMapLayer(layer)
                self._log("Loaded station layer.")

        # Validation tables as (geometry-less) CSV layers.
        for label, key in [
            ("Validation (overall)", "validation_overall_csv"),
            ("Validation (by zone)", "validation_by_zone_csv"),
            ("Product ranking", "product_ranking_csv"),
        ]:
            path = results.get(key)
            if path and os.path.exists(path):
                uri = f"file:///{path}?delimiter=,"
                layer = QgsVectorLayer(uri, label, "delimitedtext")
                if layer.isValid():
                    QgsProject.instance().addMapLayer(layer)
                    self._log(f"Loaded: {label}")

        workbook = results.get("workbook")
        if workbook and os.path.exists(workbook):
            self._log(f"Decision workbook: {workbook}")

        summary = results.get("summary")
        if summary:
            self._log("\n--- Summary ---\n" + summary)

    # -- helpers --------------------------------------------------------

    def _log(self, line: str):
        self.log.appendPlainText(line)

    def _set_busy(self, busy: bool):
        self.progress.setVisible(busy)
        self.run_btn.setEnabled(not busy)
        has_run = self._last_params is not None
        self.mean_map_btn.setEnabled(not busy and has_run)
        self.bias_map_btn.setEnabled(not busy and has_run)


def _build_script(params_path: str, results_path: str) -> str:
    """Build the self-contained script run inside the managed venv."""
    return f"""
import json, os

with open(r"{params_path}", encoding="utf-8") as f:
    p = json.load(f)

from savana.rainfall import validate_against_gpcc

out_dir = p["out_dir"]
ra = validate_against_gpcc(
    stations=p["stations"],
    products=p["products"],
    start_year=p["start_year"],
    end_year=p["end_year"],
    obs_source=p["obs_source"],
    ee_project=p["ee_project"],
    cache_dir=out_dir,
)

results = {{}}

# validation CSVs are already written by validate_against_gpcc into out_dir
for key, fname in [
    ("validation_overall_csv", "validation_overall.csv"),
    ("validation_by_zone_csv", "validation_by_zone.csv"),
    ("product_ranking_csv", "product_ranking.csv"),
]:
    path = os.path.join(out_dir, fname)
    if os.path.exists(path):
        results[key] = path

# station point layer as GeoJSON
try:
    import json as _json
    feats = []
    for _, s in ra.stations_df.iterrows():
        feats.append({{
            "type": "Feature",
            "geometry": {{"type": "Point", "coordinates": [float(s["lon"]), float(s["lat"])]}},
            "properties": {{k: (None if v != v else v) for k, v in s.items()}},
        }})
    gj_path = os.path.join(out_dir, "stations.geojson")
    with open(gj_path, "w", encoding="utf-8") as f:
        _json.dump({{"type": "FeatureCollection", "features": feats}}, f)
    results["stations_geojson"] = gj_path
except Exception as exc:
    print("station geojson export skipped:", exc)

# decision workbook
try:
    wb = os.path.join(out_dir, "decision_tool.xlsx")
    ra.export_workbook(wb)
    results["workbook"] = wb
except Exception as exc:
    print("workbook export skipped:", exc)

try:
    results["summary"] = ra.summarize()
except Exception as exc:
    print("summary skipped:", exc)

with open(r"{results_path}", "w", encoding="utf-8") as f:
    json.dump(results, f)

print("DONE")
"""
