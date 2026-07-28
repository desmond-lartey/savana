"""Shared UI building blocks for Savana dock panels.

Gives every panel the same look and structure as the GeoAI plugin:
a scroll area wrapping a header, a tab widget, and a progress bar, plus
consistent colored status labels (gray = idle, green = success,
red = error, amber = busy). Keeping these here means the three panels
stay visually consistent and a fourth module's panel gets the same look
for free.
"""

from __future__ import annotations

from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtWidgets import (
    QLabel,
    QProgressBar,
    QScrollArea,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

# Status colors, matching GeoAI's convention.
STATUS_IDLE = "color: gray;"
STATUS_OK = "color: #2e7d32;"  # green 800
STATUS_ERROR = "color: #c62828;"  # red 800
STATUS_BUSY = "color: #f9a825;"  # amber 800


def make_status_label(text: str = "") -> QLabel:
    """A gray, word-wrapped status label."""
    label = QLabel(text)
    label.setWordWrap(True)
    label.setStyleSheet(STATUS_IDLE)
    return label


def set_status(label: QLabel, text: str, kind: str = "idle") -> None:
    """Set a status label's text and color.

    kind: one of "idle", "ok", "error", "busy".
    """
    label.setText(text)
    label.setStyleSheet(
        {
            "idle": STATUS_IDLE,
            "ok": STATUS_OK,
            "error": STATUS_ERROR,
            "busy": STATUS_BUSY,
        }.get(kind, STATUS_IDLE)
    )


class PanelScaffold:
    """Builds the scroll + header + tabs + progress-bar shell for a panel.

    Usage in a QDockWidget subclass::

        scaffold = PanelScaffold(
            title="Precipitation Assessment",
            subtitle="Validate rainfall products against GPCC gauges",
        )
        scaffold.add_tab(self._build_run_tab(), "Run")
        scaffold.add_tab(self._build_maps_tab(), "Maps")
        self.progress = scaffold.progress
        self.setWidget(scaffold.finish())
    """

    def __init__(self, title: str, subtitle: str = "", link: str = ""):
        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        self._root = QWidget()
        self._layout = QVBoxLayout()
        self._root.setLayout(self._layout)

        header_html = f"<b>{title}</b>"
        if link:
            header_html += f' — <a href="{link}">{title}</a>'
        header = QLabel(header_html)
        header.setOpenExternalLinks(True)
        header.setWordWrap(True)
        self._layout.addWidget(header)

        if subtitle:
            sub = QLabel(subtitle)
            sub.setWordWrap(True)
            sub.setStyleSheet(STATUS_IDLE)
            self._layout.addWidget(sub)

        self.tabs = QTabWidget()
        self._layout.addWidget(self.tabs)

        self.progress = QProgressBar()
        self.progress.setRange(0, 0)  # indeterminate
        self.progress.setVisible(False)
        self._layout.addWidget(self.progress)

    def add_tab(self, widget: QWidget, label: str) -> None:
        self.tabs.addTab(widget, label)

    def finish(self) -> QScrollArea:
        """Return the scroll area to hand to setWidget()."""
        self._scroll.setWidget(self._root)
        return self._scroll
