"""Module registry: how analysis types register themselves with the hub.

This is the mechanism that makes the plugin extensible without rewrites.
Each analysis type (land-system classification, precipitation assessment,
and any future module) is described by one ``ModuleSpec`` and added to
``MODULES``. The hub launcher builds its list of buttons from this
registry, and the main plugin creates a dock panel per entry — so adding
a new analysis type is: write its panel class, add one ``ModuleSpec``
here, done. No changes to the hub or the plugin shell.

A ModuleSpec deliberately holds only *metadata plus a lazy import path*,
never the panel class itself, so importing this registry stays cheap and
never drags in heavy Qt/savana imports until a panel is actually opened.
"""

from __future__ import annotations

import importlib
from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class ModuleSpec:
    """Describes one analysis module the plugin exposes.

    Attributes:
        key: Stable machine identifier (used for dock object names, etc).
        title: Human-readable name shown on the hub button and dock title.
        description: One-line summary shown under the hub button.
        icon: Filename (within the plugin's ``icons/`` folder) for this
            module's toolbar/hub icon. May be missing; a fallback QGIS
            icon is used if the file isn't present.
        panel_module: Dotted path (relative to the plugin package) of the
            module containing the panel class.
        panel_class: Name of the QDockWidget subclass in ``panel_module``.
        available: If False, the hub shows the entry greyed out with a
            "coming soon" note instead of opening it. Lets a module be
            registered (so the structure is visible) before it's wired.
    """

    key: str
    title: str
    description: str
    icon: str
    panel_module: str
    panel_class: str
    available: bool = True

    def load_panel_class(self, package: str):
        """Import and return this module's panel class.

        Args:
            package: The plugin's package name (``__name__`` of the
                top-level plugin package), used to resolve the relative
                ``panel_module`` path.

        Returns:
            The panel class object (not an instance).
        """
        module = importlib.import_module(f".{self.panel_module}", package)
        return getattr(module, self.panel_class)


# The registry. Order here is the order shown in the hub.
MODULES: tuple[ModuleSpec, ...] = (
    ModuleSpec(
        key="rainfall",
        title="Precipitation Product Assessment",
        description=(
            "Validate global precipitation products against GPCC gauge "
            "observations and rank them for your application."
        ),
        icon="rainfall.svg",
        panel_module="dialogs.rainfall_panel",
        panel_class="RainfallDockWidget",
        available=True,
    ),
    ModuleSpec(
        key="classification",
        title="Land-System Classification",
        description=(
            "Adaptive classification of a savanna landscape into "
            "ecologically meaningful structural classes, with change "
            "detection across epochs."
        ),
        icon="classification.svg",
        panel_module="dialogs.classification_panel",
        panel_class="ClassificationDockWidget",
        available=True,
    ),
)


def get_module(key: str) -> Optional[ModuleSpec]:
    """Return the ModuleSpec with the given key, or None."""
    for spec in MODULES:
        if spec.key == key:
            return spec
    return None
