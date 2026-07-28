"""Shared Google Earth Engine connection state for the plugin.

One EE project id is entered once (in the connection panel) and reused
by every analysis panel. The actual ``ee.Initialize`` happens inside the
managed-venv subprocess workers, not in QGIS's own Python — so this
module only *stores and validates* the project id and reports connection
status; it never imports ``ee`` in QGIS's process.

The project id is persisted with ``QSettings`` so it survives QGIS
restarts. Authentication itself (the one-time ``earthengine authenticate``
browser flow) is run in the managed venv via the worker, since that's
where ``earthengine-api`` actually lives.
"""

from __future__ import annotations

_SETTINGS_GROUP = "savana"
_PROJECT_KEY = "savana/ee_project"


def _settings():
    from qgis.PyQt.QtCore import QSettings

    return QSettings()


def get_project() -> str:
    """Return the saved EE project id, or empty string if none set."""
    try:
        value = _settings().value(_PROJECT_KEY, "")
        return str(value) if value else ""
    except Exception:  # noqa: BLE001 -- outside QGIS
        return ""


def set_project(project_id: str) -> None:
    """Persist the EE project id."""
    _settings().setValue(_PROJECT_KEY, project_id.strip())


def is_configured() -> bool:
    """True if a non-empty project id has been saved."""
    return bool(get_project())


def status_line() -> str:
    """Human-readable one-liner for the UI."""
    project = get_project()
    if project:
        return f"Earth Engine project: {project}"
    return "No Earth Engine project set. Enter one and click Connect."


def build_auth_check_code(project_id: str) -> str:
    """Return Python source (run in the venv) that verifies EE auth works.

    Kept here (rather than inline in a worker) so the exact check is in
    one place. It initializes EE with the given project and does one
    trivial server call; success means auth + project are both valid.
    """
    safe_project = project_id.replace('"', '\\"')
    return (
        "import ee\n"
        f'ee.Initialize(project="{safe_project}")\n'
        "n = ee.Number(1).add(1).getInfo()\n"
        'assert n == 2, "unexpected EE compute result"\n'
        'print("EE_OK")\n'
    )


def build_authenticate_code() -> str:
    """Return Python source (run in the venv) that triggers the EE auth flow.

    This launches Earth Engine's standard browser-based authentication.
    It only needs to be run once per machine; afterwards
    :func:`build_auth_check_code` will succeed without it.
    """
    return "import ee\nee.Authenticate()\nprint('AUTH_DONE')\n"
