"""Land-System Classification dock panel.

Wraps ``savana.classify_landscape`` behind a QGIS form: pick an AOI
(a loaded QGIS vector layer, or an Earth Engine asset id), choose the
epoch years, and run. The classification runs in the managed venv on a
worker thread; the per-epoch class-area table and a plain-English
summary come back into the panel, and (optionally) results are exported
to the user's Google Drive via Earth Engine, matching how savana's own
``.export()`` works.

Because savana classification produces Earth Engine images (not local
rasters), those aren't auto-loaded into the QGIS canvas in this first
version - the panel reports the computed statistics and offers Drive
export. Rendering EE result layers directly on the QGIS canvas is a
planned enhancement (see the plugin roadmap).
"""

from __future__ import annotations

import json
import os
import tempfile

from qgis.PyQt.QtWidgets import (
    QComboBox,
    QDockWidget,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ..core import ee_connection, venv_manager
from ..workers.subprocess_worker import run_script_in_thread
from .ui_helpers import PanelScaffold, make_status_label, set_status

# Mirrors savana.config.DEFAULT_CLASS_INFO. Duplicated here because this
# module runs in QGIS's Python, where savana isn't importable (it lives
# in the managed venv), so the values can't be read from the package.
CLASS_COLORS = [
    "1a6b1a",  # 1 Core Woodland
    "74c476",  # 2 Open Woodland / Tree Savanna
    "c7e9c0",  # 3 Shrub-Transition Savanna
    "ffff99",  # 4 Grassland Systems
    "4292c6",  # 5 Riparian / Wetland Vegetation
    "d73027",  # 6 Anthropogenic Disturbance
]
CLASS_VIS = {"min": 1, "max": 6, "palette": CLASS_COLORS}
CHANGE_VIS = {"min": 0, "max": 1, "palette": ["#FFFFFF", "#d73027"]}


class ClassificationDockWidget(QDockWidget):
    """Dockable Land-System Classification panel."""

    def __init__(self, iface, parent=None):
        super().__init__("Savana - Land-System Classification", parent)
        self.iface = iface
        self.setObjectName("SavanaClassificationDock")
        self._thread = None
        self._worker = None
        self._last_params = None
        self._tiles_path = None
        self._pending_layer_name = ""

        scaffold = PanelScaffold(
            title="Land-System Classification",
            subtitle=(
                "Adaptive classification of a savanna landscape into "
                "structural classes, with change detection across epochs."
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

        self.run_status = make_status_label("Ready.")
        v.addWidget(self.run_status)

        self.run_btn = QPushButton("Run classification")
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

    def _build_map_group(self) -> QGroupBox:
        """Map layers are shown on demand, not auto-loaded.

        A multi-epoch run would otherwise dump one layer per epoch plus
        change layers onto the canvas unannounced, and each layer costs
        an Earth Engine getMapId call -- so the user picks what to see.
        """
        group = QGroupBox("Map layers (after a run)")
        v = QVBoxLayout(group)

        self.map_status = make_status_label("Run a classification first.")
        v.addWidget(self.map_status)

        row = QHBoxLayout()
        row.addWidget(QLabel("Epoch:"))
        self.map_epoch = QComboBox()
        row.addWidget(self.map_epoch)
        v.addLayout(row)

        self.class_map_btn = QPushButton("Show classified map")
        self.class_map_btn.clicked.connect(self._on_show_class_map)
        self.class_map_btn.setEnabled(False)
        v.addWidget(self.class_map_btn)

        self.change_map_btn = QPushButton("Show change map")
        self.change_map_btn.clicked.connect(self._on_show_change_map)
        self.change_map_btn.setEnabled(False)
        v.addWidget(self.change_map_btn)

        note = QLabel(
            "Layers are Earth Engine preview tiles: viewable and "
            "stackable, but not downloadable rasters. Use Drive export "
            "for analysis-ready data."
        )
        note.setWordWrap(True)
        v.addWidget(note)

        return group

    def _on_show_class_map(self):
        epoch = self.map_epoch.currentText()
        if not epoch:
            self._log("No epoch selected.")
            return
        self._show_map_layer(
            image_expr=f"_clf.maps[{int(epoch)}]",
            vis=CLASS_VIS,
            layer_name=f"Land systems {epoch} - {self._last_params['park_name']}",
        )

    def _on_show_change_map(self):
        self._show_map_layer(
            image_expr='_clf.change["genuine_change"]',
            vis=CHANGE_VIS,
            layer_name=f"Genuine change - {self._last_params['park_name']}",
        )

    def _show_map_layer(self, image_expr: str, vis: dict, layer_name: str):
        """Re-run the classification in the venv and resolve to tiles.

        Classification results are Earth Engine objects that can't be
        serialised between processes, so the analysis is rebuilt from
        the same parameters. Earth Engine caches aggressively, so this
        is far quicker than the original run.
        """
        if not self._last_params:
            self._log("Run a classification first, then show map layers.")
            return

        import tempfile

        from ..core import ee_layers

        p = self._last_params
        tiles_path = os.path.join(
            tempfile.mkdtemp(prefix="savana_tiles_"), "tiles.json"
        )
        self._tiles_path = tiles_path
        self._pending_layer_name = layer_name

        setup = (
            "import savana\n"
            "_clf = savana.classify_landscape(\n"
            f"    aoi={p['aoi']!r},\n"
            f"    epochs={p['epochs']!r},\n"
            f"    park_name={p['park_name']!r},\n"
            f"    name_filter={p['name_filter']!r},\n"
            f"    ee_project={p['ee_project']!r},\n"
            ")\n"
        )
        script = ee_layers.build_tile_script(image_expr, vis, tiles_path, setup=setup)

        self._log(f"Building map layer: {layer_name} (rebuilding analysis) ...")
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

    def _build_inputs_group(self) -> QGroupBox:
        group = QGroupBox("Area of interest & epochs")
        form = QFormLayout(group)

        self.aoi_edit = QLineEdit()
        self.aoi_edit.setPlaceholderText(
            "EE asset id, or path to a .geojson/.shp AOI file"
        )
        form.addRow("AOI:", self.aoi_edit)

        self.name_filter_edit = QLineEdit()
        self.name_filter_edit.setPlaceholderText(
            "optional: filter a parks asset by name"
        )
        form.addRow("Name filter:", self.name_filter_edit)

        self.park_name_edit = QLineEdit()
        self.park_name_edit.setText("AOI")
        form.addRow("Label:", self.park_name_edit)

        self.epochs_edit = QLineEdit()
        self.epochs_edit.setText("2019, 2024")
        self.epochs_edit.setPlaceholderText(
            "comma-separated years, e.g. 2019, 2021, 2024"
        )
        form.addRow("Epochs:", self.epochs_edit)

        self.drive_folder_edit = QLineEdit()
        self.drive_folder_edit.setPlaceholderText(
            "optional: Google Drive folder to export to"
        )
        form.addRow("Export to Drive:", self.drive_folder_edit)

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

    def _parse_epochs(self):
        raw = self.epochs_edit.text().replace(";", ",")
        years = []
        for tok in raw.split(","):
            tok = tok.strip()
            if tok:
                try:
                    years.append(int(tok))
                except ValueError:
                    pass
        return years

    def _on_run(self):
        if not self._prerequisites_ok():
            return

        epochs = self._parse_epochs()
        if not epochs:
            self._log("Enter at least one epoch year.")
            return
        aoi = self.aoi_edit.text().strip()
        if not aoi:
            self._log("Enter an AOI (EE asset id or a vector file path).")
            return

        params = {
            "aoi": aoi,
            "name_filter": self.name_filter_edit.text().strip() or None,
            "park_name": self.park_name_edit.text().strip() or "AOI",
            "epochs": epochs,
            "drive_folder": self.drive_folder_edit.text().strip() or None,
            "ee_project": ee_connection.get_project(),
            "out_dir": tempfile.mkdtemp(prefix="savana_classify_"),
        }
        self._last_params = params
        params_path = os.path.join(params["out_dir"], "params.json")
        with open(params_path, "w", encoding="utf-8") as f:
            json.dump(params, f)

        self._results_path = os.path.join(params["out_dir"], "results.json")
        script = _build_script(params_path, self._results_path)

        self._log("Running classification (this can take a while) ...")
        set_status(self.run_status, "Running classification...", "busy")
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
            set_status(self.run_status, "Classification failed - see log.", "error")
            self._log("FAILED:\n" + msg)
            return
        set_status(self.run_status, "Classification complete.", "ok")
        try:
            with open(self._results_path, encoding="utf-8") as f:
                results = json.load(f)
        except (OSError, json.JSONDecodeError) as exc:
            self._log(f"Could not read results: {exc}")
            return

        areas_csv = results.get("class_areas_csv")
        if areas_csv and os.path.exists(areas_csv):
            from qgis.core import QgsProject, QgsVectorLayer

            uri = f"file:///{areas_csv}?delimiter=,"
            layer = QgsVectorLayer(uri, "Class areas (km2)", "delimitedtext")
            if layer.isValid():
                QgsProject.instance().addMapLayer(layer)
                self._log("Loaded class-areas table.")

        self.map_epoch.clear()
        self.map_epoch.addItems([str(e) for e in self._last_params["epochs"]])
        self.class_map_btn.setEnabled(True)
        self.change_map_btn.setEnabled(len(self._last_params["epochs"]) >= 2)
        set_status(self.map_status, "Ready - pick an epoch and show a map.", "ok")

        if results.get("summary"):
            self._log("\n--- Summary ---\n" + results["summary"])
        if results.get("export_note"):
            self._log(results["export_note"])

    # -- helpers --------------------------------------------------------

    def _log(self, line: str):
        self.log.appendPlainText(line)

    def _set_busy(self, busy: bool):
        self.progress.setVisible(busy)
        self.run_btn.setEnabled(not busy)
        has_run = self._last_params is not None
        self.class_map_btn.setEnabled(not busy and has_run)
        self.change_map_btn.setEnabled(
            not busy and has_run and len(self._last_params["epochs"]) >= 2
        )


def _build_script(params_path: str, results_path: str) -> str:
    """Build the self-contained script run inside the managed venv."""
    return f"""
import json, os

with open(r"{params_path}", encoding="utf-8") as f:
    p = json.load(f)

import savana

clf = savana.classify_landscape(
    aoi=p["aoi"],
    epochs=p["epochs"],
    park_name=p["park_name"],
    name_filter=p["name_filter"],
    ee_project=p["ee_project"],
)

results = {{}}

try:
    areas = clf.class_areas()
    path = os.path.join(p["out_dir"], "class_areas.csv")
    areas.to_csv(path, index=False)
    results["class_areas_csv"] = path
except Exception as exc:
    print("class_areas skipped:", exc)

try:
    results["summary"] = clf.summarize()
except Exception as exc:
    print("summary skipped:", exc)

if p["drive_folder"]:
    try:
        tasks = clf.export(drive_folder=p["drive_folder"])
        results["export_note"] = (
            "Started " + str(len(tasks)) + " Earth Engine export task(s) to Drive "
            "folder '" + p["drive_folder"] + "'. Check the EE Tasks tab for progress."
        )
    except Exception as exc:
        results["export_note"] = "Drive export failed: " + str(exc)

with open(r"{results_path}", "w", encoding="utf-8") as f:
    json.dump(results, f)

print("DONE")
"""
