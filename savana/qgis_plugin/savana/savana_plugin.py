"""Savana QGIS Plugin - main plugin class.

Owns the toolbar and menu, and lazily creates one dock panel per
registered analysis module plus the shared Setup panel (environment
installer + Earth Engine connection). Structure follows the GeoAI
plugin: a toolbar of checkable actions, each toggling a dock widget;
docks are created on first use and reused thereafter.
"""

from __future__ import annotations

import os

from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtGui import QIcon
from qgis.PyQt.QtWidgets import QAction, QMenu, QToolBar

from .core.registry import MODULES

TOOLBAR_OBJECT_NAME = "SavanaToolbar"
MENU_TITLE = "&Savana"
PACKAGE = __package__  # e.g. "savana" (the plugin package)


class SavanaPlugin:
    """QGIS plugin entry class."""

    def __init__(self, iface):
        self.iface = iface
        self.plugin_dir = os.path.dirname(__file__)
        self.actions: list[QAction] = []
        self.menu: QMenu | None = None
        self.toolbar: QToolBar | None = None

        # Lazily created docks, keyed by module key (+ "setup").
        self._docks: dict = {}
        self._dock_actions: dict = {}

    # -- helpers --------------------------------------------------------

    def _icon(self, filename: str, fallback: str) -> QIcon:
        path = os.path.join(self.plugin_dir, "icons", filename)
        if os.path.exists(path):
            return QIcon(path)
        return QIcon(fallback)

    def _add_action(self, icon, text, callback, checkable=False):
        action = QAction(icon, text, self.iface.mainWindow())
        # Keep actions in the Savana menu on macOS (avoid app-menu role).
        try:
            action.setMenuRole(QAction.MenuRole.NoRole)
        except AttributeError:
            action.setMenuRole(QAction.NoRole)
        action.triggered.connect(callback)
        action.setCheckable(checkable)
        self.toolbar.addAction(action)
        self.menu.addAction(action)
        self.actions.append(action)
        return action

    # -- QGIS lifecycle -------------------------------------------------

    def initGui(self):  # noqa: N802 -- QGIS-mandated name
        self.menu = QMenu(MENU_TITLE)
        self.iface.mainWindow().menuBar().addMenu(self.menu)

        self.toolbar = QToolBar("Savana Toolbar")
        self.toolbar.setObjectName(TOOLBAR_OBJECT_NAME)
        self.iface.addToolBar(self.toolbar)

        # Setup panel first (environment + Earth Engine connection).
        setup_icon = self._icon(
            "setup.svg", ":/images/themes/default/mActionOptions.svg"
        )
        self._dock_actions["setup"] = self._add_action(
            setup_icon,
            "Setup (Environment & Earth Engine)",
            self._toggle_setup,
            checkable=True,
        )

        self.menu.addSeparator()
        self.toolbar.addSeparator()

        # One toolbar action per registered analysis module.
        for spec in MODULES:
            icon = self._icon(spec.icon, ":/images/themes/default/mIconRaster.svg")
            action = self._add_action(
                icon,
                spec.title,
                lambda checked, k=spec.key: self._toggle_module(k),
                checkable=True,
            )
            self._dock_actions[spec.key] = action

    def unload(self):
        for dock in self._docks.values():
            try:
                self.iface.removeDockWidget(dock)
                dock.deleteLater()
            except Exception:  # noqa: BLE001
                pass
        self._docks.clear()

        for action in self.actions:
            try:
                self.toolbar.removeAction(action)
                self.menu.removeAction(action)
            except Exception:  # noqa: BLE001
                pass
        self.actions.clear()

        if self.toolbar is not None:
            self.toolbar.deleteLater()
            self.toolbar = None
        if self.menu is not None:
            self.menu.deleteLater()
            self.menu = None

    # -- dock toggling --------------------------------------------------

    def _toggle_setup(self, checked):
        dock = self._docks.get("setup")
        if dock is None:
            from .dialogs.setup_panel import SetupDockWidget

            dock = SetupDockWidget(self.iface)
            self.iface.addDockWidget(Qt.RightDockWidgetArea, dock)
            self._docks["setup"] = dock
            self._sync_action_on_close(dock, "setup")
        dock.setVisible(checked)

    def _toggle_module(self, key):
        dock = self._docks.get(key)
        if dock is None:
            from .core.registry import get_module

            spec = get_module(key)
            panel_cls = spec.load_panel_class(PACKAGE)
            dock = panel_cls(self.iface)
            self.iface.addDockWidget(Qt.RightDockWidgetArea, dock)
            self._docks[key] = dock
            self._sync_action_on_close(dock, key)
        action = self._dock_actions[key]
        dock.setVisible(action.isChecked())

    def _sync_action_on_close(self, dock, key):
        """Keep the toolbar toggle in sync when a dock is closed via its X."""

        def _on_visibility_changed(visible):
            action = self._dock_actions.get(key)
            if action is not None:
                action.setChecked(visible)

        dock.visibilityChanged.connect(_on_visibility_changed)
