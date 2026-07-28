"""Setup panel: managed environment installer + Earth Engine connection.

This is the shared prerequisite panel. Everything the analysis panels
need is configured here, once:

1. **Environment** - a one-click button that creates the managed venv
   and installs ``savana[rainfall]`` into it (see
   :mod:`..core.venv_manager`), running on a worker thread with live log
   output so QGIS stays responsive during the multi-minute install.
2. **Earth Engine** - enter a Cloud project id (saved via QSettings,
   shared with every panel), authenticate once, and test the connection.

The analysis panels check :func:`..core.venv_manager.get_venv_status`
and :func:`..core.ee_connection.is_configured` before running, and point
the user back here if either isn't ready.
"""

from __future__ import annotations

from qgis.PyQt.QtWidgets import (
    QDockWidget,
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


class SetupDockWidget(QDockWidget):
    """Dockable Setup panel."""

    def __init__(self, iface, parent=None):
        super().__init__("Savana - Setup", parent)
        self.iface = iface
        self.setObjectName("SavanaSetupDock")

        self._thread = None
        self._worker = None

        scaffold = PanelScaffold(
            title="Savana Setup",
            subtitle=(
                "Install the managed Python environment and connect to "
                "Google Earth Engine. Do this once before running a module."
            ),
            link="https://github.com/desmond-lartey/savana",
        )

        env_tab = QWidget()
        env_v = QVBoxLayout(env_tab)
        env_v.addWidget(self._build_env_group())
        env_v.addStretch(1)
        scaffold.add_tab(env_tab, "Environment")

        ee_tab = QWidget()
        ee_v = QVBoxLayout(ee_tab)
        ee_v.addWidget(self._build_ee_group())
        ee_v.addStretch(1)
        scaffold.add_tab(ee_tab, "Earth Engine")

        log_tab = QWidget()
        log_v = QVBoxLayout(log_tab)
        log_v.addWidget(QLabel("Log:"))
        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setMaximumBlockCount(2000)
        log_v.addWidget(self.log)
        scaffold.add_tab(log_tab, "Log")

        self.progress = scaffold.progress
        self.setWidget(scaffold.finish())

        self._refresh_status()

    # -- UI construction ------------------------------------------------

    def _build_env_group(self) -> QGroupBox:
        group = QGroupBox("1. Python environment")
        v = QVBoxLayout(group)

        self.env_status = make_status_label()
        v.addWidget(self.env_status)

        row = QHBoxLayout()
        self.install_btn = QPushButton("Install / Repair environment")
        self.install_btn.clicked.connect(self._on_install_clicked)
        row.addWidget(self.install_btn)

        self.remove_btn = QPushButton("Remove")
        self.remove_btn.clicked.connect(self._on_remove_clicked)
        row.addWidget(self.remove_btn)
        v.addLayout(row)

        # Developer option: install savana from a local source tree
        # (editable) instead of from PyPI, so repo edits reach the
        # plugin with no reinstall. Leave blank for a normal install.
        dev_row = QHBoxLayout()
        dev_row.addWidget(QLabel("Local source (dev):"))
        self.local_path_edit = QLineEdit()
        detected = venv_manager.detect_local_source()
        self.local_path_edit.setPlaceholderText(
            "blank = install from PyPI; or path to your savana repo"
        )
        self.local_path_edit.setText(venv_manager.get_local_source_path())
        if detected:
            self.local_path_edit.setToolTip(
                f"Auto-detected from the plugin's location: {detected}\n"
                "Clear this field and click Save to force a PyPI install instead."
            )
        dev_row.addWidget(self.local_path_edit)

        self.save_path_btn = QPushButton("Save")
        self.save_path_btn.clicked.connect(self._on_save_local_path)
        dev_row.addWidget(self.save_path_btn)
        v.addLayout(dev_row)

        return group

    def _on_save_local_path(self):
        path = self.local_path_edit.text().strip()
        venv_manager.set_local_source_path(path)
        if path:
            self._append_log(
                f"Local source set: {path}\n"
                "Click 'Install / Repair environment' to install it (editable)."
            )
        else:
            self._append_log("Local source cleared - installs will use PyPI.")

    def _build_ee_group(self) -> QGroupBox:
        group = QGroupBox("2. Google Earth Engine")
        v = QVBoxLayout(group)

        self.ee_status = make_status_label()
        v.addWidget(self.ee_status)

        row = QHBoxLayout()
        row.addWidget(QLabel("Project id:"))
        self.project_edit = QLineEdit()
        self.project_edit.setPlaceholderText("your-gcp-project-id")
        self.project_edit.setText(ee_connection.get_project())
        row.addWidget(self.project_edit)
        v.addLayout(row)

        btn_row = QHBoxLayout()
        self.save_btn = QPushButton("Save project")
        self.save_btn.clicked.connect(self._on_save_project)
        btn_row.addWidget(self.save_btn)

        self.auth_btn = QPushButton("Authenticate")
        self.auth_btn.clicked.connect(self._on_authenticate)
        btn_row.addWidget(self.auth_btn)

        self.test_btn = QPushButton("Test connection")
        self.test_btn.clicked.connect(self._on_test_connection)
        btn_row.addWidget(self.test_btn)
        v.addLayout(btn_row)

        return group

    # -- status ---------------------------------------------------------

    def _refresh_status(self):
        ready, msg = venv_manager.get_venv_status()
        set_status(self.env_status, msg, "ok" if ready else "idle")
        set_status(
            self.ee_status,
            ee_connection.status_line(),
            "ok" if ee_connection.is_configured() else "idle",
        )
        # EE actions only make sense once the env is installed.
        for b in (self.auth_btn, self.test_btn):
            b.setEnabled(ready)

    def _append_log(self, line: str):
        self.log.appendPlainText(line)

    def _set_busy(self, busy: bool):
        self.progress.setVisible(busy)
        for b in (
            self.install_btn,
            self.remove_btn,
            self.save_btn,
            self.save_path_btn,
            self.auth_btn,
            self.test_btn,
        ):
            b.setEnabled(not busy)
        if not busy:
            self._refresh_status()

    # -- environment actions -------------------------------------------

    def _on_install_clicked(self):
        self._append_log("Starting environment install...")
        self._set_busy(True)
        # venv_manager runs its own subprocesses internally; run the whole
        # create+install+verify on a worker thread so the UI stays live.
        from qgis.PyQt.QtCore import QObject, QThread, pyqtSignal

        class _InstallWorker(QObject):
            progress = pyqtSignal(str)
            finished = pyqtSignal(bool, str)

            def run(self):
                ok, msg = venv_manager.create_venv_and_install(
                    log_callback=lambda line: self.progress.emit(line)
                )
                self.finished.emit(ok, msg)

        self._thread = QThread()
        self._worker = _InstallWorker()
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._worker.progress.connect(self._append_log)
        self._worker.finished.connect(self._on_install_finished)
        self._worker.finished.connect(self._thread.quit)
        self._worker.finished.connect(self._worker.deleteLater)
        self._thread.finished.connect(self._thread.deleteLater)
        self._thread.start()

    def _on_install_finished(self, ok: bool, msg: str):
        self._append_log(("SUCCESS: " if ok else "FAILED: ") + msg)
        self._set_busy(False)

    def _on_remove_clicked(self):
        ok, msg = venv_manager.remove_venv()
        self._append_log(msg)
        self._refresh_status()

    # -- Earth Engine actions ------------------------------------------

    def _on_save_project(self):
        project = self.project_edit.text().strip()
        if not project:
            self._append_log("Enter a project id before saving.")
            return
        ee_connection.set_project(project)
        self._append_log(f"Saved Earth Engine project: {project}")
        self._refresh_status()

    def _on_authenticate(self):
        self._append_log(
            "Launching Earth Engine authentication (check your browser)..."
        )
        self._run_ee_script(ee_connection.build_authenticate_code())

    def _on_test_connection(self):
        project = self.project_edit.text().strip() or ee_connection.get_project()
        if not project:
            self._append_log("Set a project id first.")
            return
        self._append_log(f"Testing Earth Engine connection for {project}...")
        self._run_ee_script(ee_connection.build_auth_check_code(project))

    def _run_ee_script(self, script: str):
        python = venv_manager.get_venv_python_path()
        self._set_busy(True)
        self._thread, self._worker = run_script_in_thread(
            python,
            script,
            on_progress=self._append_log,
            on_finished=self._on_ee_finished,
        )

    def _on_ee_finished(self, ok: bool, msg: str):
        self._append_log(("OK: " if ok else "FAILED: ") + msg)
        self._set_busy(False)
