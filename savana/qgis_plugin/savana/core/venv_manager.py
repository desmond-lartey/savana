"""Managed virtual environment for the savana package inside QGIS.

QGIS ships its own Python, and installing heavy geospatial packages
(earthengine-api, geemap, xarray, geopandas, netCDF4) directly into it
is unreliable and can corrupt the QGIS install. Following the approach
proven by the GeoAI and TerraLabAI QGIS plugins, this module instead
creates a *separate* virtual environment outside QGIS, installs savana
and its dependencies there, and the plugin runs all savana work in
subprocess workers against that env's Python.

This is a deliberately lean adaptation: savana's dependencies are pure
Python / prebuilt wheels (no PyTorch, no CUDA), so the elaborate GPU /
CUDA / torch-repair machinery in GeoAI's venv_manager is omitted. The
public interface (``venv_exists``, ``get_venv_python_path``,
``create_venv_and_install``, ``verify_venv``, ``remove_venv``,
``get_venv_status``) is kept compatible so it can be hardened toward
GeoAI's robustness later without changing callers.

All functions are import-safe outside QGIS (they only import
``qgis.core`` lazily, inside functions), so this module can be
unit-tested without QGIS present.
"""

from __future__ import annotations

import os
import subprocess
import sys
from typing import Callable, List, Optional, Tuple

PYTHON_VERSION = f"py{sys.version_info.major}.{sys.version_info.minor}"
CACHE_DIR = (
    os.environ.get("SAVANA_CACHE_DIR")
    or os.environ.get("SAVANA_VENV_DIR")
    or os.path.expanduser("~/.qgis_savana")
)
VENV_DIR = os.path.join(CACHE_DIR, f"venv_{PYTHON_VERSION}")

# The extras installed by default -- rainfall pulls in xarray, netCDF4,
# geopandas, shapely, openpyxl, matplotlib; the base package pulls in
# earthengine-api, geemap, pandas. agents is left out by default (large,
# and only needed for the optional AI panel).
SAVANA_INSTALL_SPEC = "savana[rainfall]"

MARKER_FILE = os.path.join(VENV_DIR, "savana_installed.txt")

# Optional developer override: install savana from a local source tree
# (editable) instead of from PyPI. Set via the Setup panel; persisted in
# QSettings so it survives QGIS restarts. When set, every install /
# repair uses `pip install -e <path>[rainfall]`, so edits to the repo
# are picked up by the plugin immediately with no reinstall.
_LOCAL_PATH_KEY = "savana/local_source_path"


def detect_local_source() -> str:
    """Detect a savana source checkout containing this plugin, if any.

    When the plugin is run from a repo (copied or symlinked out of
    ``<repo>/savana/qgis_plugin/savana``), the repo root is simply a few
    levels up from this file — so there's no need to ask the developer
    to type a path they've already implied by where the plugin lives.

    ``os.path.realpath`` matters here: QGIS imports the plugin through
    its plugins directory, so ``__file__`` is the *symlink* path on a
    dev setup. Resolving it gives the real location inside the repo.

    Returns the repo root (a directory holding both ``pyproject.toml``
    and a ``savana/`` package dir), or "" when the plugin isn't running
    from a source tree — which is the normal end-user case, where
    installs should come from PyPI.
    """
    here = os.path.dirname(os.path.realpath(__file__))
    # Walk up a bounded number of levels looking for the repo root.
    candidate = here
    for _ in range(6):
        candidate = os.path.dirname(candidate)
        if not candidate:
            break
        has_pyproject = os.path.isfile(os.path.join(candidate, "pyproject.toml"))
        has_package = os.path.isdir(os.path.join(candidate, "savana"))
        if has_pyproject and has_package:
            return candidate
    return ""


def get_local_source_path() -> str:
    """Return the local savana source path to install from, or "".

    Precedence: an explicitly saved setting wins (including an
    explicitly cleared one, so a developer can force a PyPI install);
    otherwise fall back to auto-detection.
    """
    try:
        from qgis.PyQt.QtCore import QSettings

        saved = QSettings().value(_LOCAL_PATH_KEY, None)
    except Exception:  # noqa: BLE001 -- outside QGIS
        saved = None

    if saved is not None:
        return str(saved)
    return detect_local_source()


def set_local_source_path(path: str) -> None:
    """Persist (or clear, if empty) the local savana source path."""
    from qgis.PyQt.QtCore import QSettings

    QSettings().setValue(_LOCAL_PATH_KEY, (path or "").strip())


def resolve_install_spec(spec: Optional[str] = None) -> Tuple[list, str]:
    """Work out what pip should actually install.

    Returns ``(pip_args, description)`` — either a normal PyPI install
    of ``savana[rainfall]``, or an editable install of a local source
    tree when a developer path is configured.
    """
    local = get_local_source_path()
    if local:
        target = f"{local}[rainfall]"
        return ["install", "-e", target], f"local source (editable): {local}"
    return ["install", spec or SAVANA_INSTALL_SPEC], spec or SAVANA_INSTALL_SPEC


def _log(message: str, level=None) -> None:
    """Log to the QGIS message log if available, else print."""
    try:
        from qgis.core import Qgis, QgsMessageLog

        QgsMessageLog.logMessage(message, "Savana", level or Qgis.Info)
    except Exception:  # noqa: BLE001 -- outside QGIS, fall back to print
        print(f"[Savana] {message}")


def _subprocess_kwargs() -> dict:
    """Platform-appropriate subprocess kwargs (hide console window on Windows)."""
    kwargs: dict = {}
    if os.name == "nt":
        startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        kwargs["startupinfo"] = startupinfo
        kwargs["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    return kwargs


def get_venv_dir() -> str:
    """Return the managed venv directory path."""
    return VENV_DIR


def get_venv_python_path(venv_dir: Optional[str] = None) -> str:
    """Path to the Python executable inside the managed venv."""
    venv_dir = venv_dir or VENV_DIR
    if os.name == "nt":
        return os.path.join(venv_dir, "Scripts", "python.exe")
    return os.path.join(venv_dir, "bin", "python")


def venv_exists(venv_dir: Optional[str] = None) -> bool:
    """True if a venv with a usable Python executable exists."""
    return os.path.isfile(get_venv_python_path(venv_dir))


def _get_system_python() -> str:
    """Find a Python interpreter to build the venv from.

    Prefers ``sys.executable`` when it's a real Python (not the QGIS
    GUI binary). On Windows, QGIS's ``sys.executable`` is often
    ``qgis-bin.exe``, so we look for ``python.exe`` alongside it.
    """
    exe = sys.executable or ""
    base = os.path.basename(exe).lower()
    if base.startswith("python"):
        return exe

    # QGIS: look for a python next to the QGIS binary
    exe_dir = os.path.dirname(exe)
    candidates = []
    if os.name == "nt":
        candidates = [
            os.path.join(exe_dir, "python.exe"),
            os.path.join(exe_dir, "python3.exe"),
        ]
    else:
        candidates = [
            os.path.join(exe_dir, "python3"),
            os.path.join(exe_dir, "python"),
            "/usr/bin/python3",
        ]
    for c in candidates:
        if os.path.isfile(c):
            return c

    # Last resort: hope sys.executable works
    return exe


def create_venv(
    venv_dir: Optional[str] = None,
    log_callback: Optional[Callable[[str], None]] = None,
) -> Tuple[bool, str]:
    """Create an empty virtual environment.

    Args:
        venv_dir: Target directory. Uses VENV_DIR if None.
        log_callback: Optional callable receiving progress strings.

    Returns:
        (success, message).
    """
    venv_dir = venv_dir or VENV_DIR
    log = log_callback or _log

    if venv_exists(venv_dir):
        return True, "Virtual environment already exists."

    os.makedirs(os.path.dirname(venv_dir), exist_ok=True)
    system_python = _get_system_python()
    log(f"Creating virtual environment with {system_python} ...")

    # --without-pip: QGIS's bundled Python on Windows ships without
    # ensurepip, so a plain `python -m venv` dies trying to seed pip.
    # We create the bare venv here and bootstrap pip separately (see
    # bootstrap_pip), which handles both normal and QGIS Pythons.
    try:
        result = subprocess.run(
            [system_python, "-m", "venv", "--without-pip", venv_dir],
            capture_output=True,
            text=True,
            timeout=300,
            **_subprocess_kwargs(),
        )
    except FileNotFoundError:
        return False, f"Could not run {system_python!r} to create the venv."
    except subprocess.TimeoutExpired:
        return False, "Timed out creating the virtual environment."

    if result.returncode != 0:
        return False, f"venv creation failed:\n{result.stderr.strip()}"
    if not venv_exists(venv_dir):
        return False, "venv creation reported success but no python was found."

    return True, "Virtual environment created."


GET_PIP_URL = "https://bootstrap.pypa.io/get-pip.py"


def _venv_has_pip(venv_dir: Optional[str] = None) -> bool:
    """True if pip is importable inside the venv."""
    python = get_venv_python_path(venv_dir)
    try:
        result = subprocess.run(
            [python, "-m", "pip", "--version"],
            capture_output=True,
            text=True,
            timeout=60,
            **_subprocess_kwargs(),
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False
    return result.returncode == 0


def bootstrap_pip(
    venv_dir: Optional[str] = None,
    log_callback: Optional[Callable[[str], None]] = None,
) -> Tuple[bool, str]:
    """Make sure the venv has pip, whichever Python built it.

    Strategy 1: ``ensurepip`` (works when the venv was built from a
    normal Python install). Strategy 2: download and run get-pip.py
    (needed when the venv came from QGIS's bundled Python on Windows,
    which ships without ensurepip). The download uses the venv's own
    Python and stdlib urllib, so no external tooling is required.
    """
    venv_dir = venv_dir or VENV_DIR
    log = log_callback or _log
    python = get_venv_python_path(venv_dir)

    if _venv_has_pip(venv_dir):
        return True, "pip already available in the venv."

    log("Bootstrapping pip: trying ensurepip ...")
    try:
        result = subprocess.run(
            [python, "-m", "ensurepip", "--upgrade", "--default-pip"],
            capture_output=True,
            text=True,
            timeout=300,
            **_subprocess_kwargs(),
        )
        if result.returncode == 0 and _venv_has_pip(venv_dir):
            return True, "pip installed via ensurepip."
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass

    log(
        "ensurepip unavailable (normal for QGIS's bundled Python); "
        "downloading get-pip.py ..."
    )
    bootstrap_code = (
        "import os, runpy, sys, tempfile, urllib.request\n"
        f"url = {GET_PIP_URL!r}\n"
        "path = os.path.join(tempfile.gettempdir(), 'get-pip.py')\n"
        "urllib.request.urlretrieve(url, path)\n"
        "sys.argv = [path]\n"
        "runpy.run_path(path, run_name='__main__')\n"
    )
    try:
        result = subprocess.run(
            [python, "-c", bootstrap_code],
            capture_output=True,
            text=True,
            timeout=900,
            **_subprocess_kwargs(),
        )
    except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
        return False, f"get-pip.py bootstrap could not run: {exc}"

    if result.returncode == 0 and _venv_has_pip(venv_dir):
        return True, "pip installed via get-pip.py."

    tail = (result.stdout + "\n" + result.stderr).strip().splitlines()[-12:]
    return False, "Could not bootstrap pip into the venv:\n" + "\n".join(tail)


def _run_pip(
    args: List[str],
    venv_dir: str,
    log_callback: Optional[Callable[[str], None]] = None,
    timeout: int = 3600,
) -> Tuple[bool, str]:
    """Run pip inside the venv, streaming output to the log callback."""
    log = log_callback or _log
    python = get_venv_python_path(venv_dir)
    cmd = [python, "-m", "pip"] + args

    try:
        process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            **_subprocess_kwargs(),
        )
    except FileNotFoundError:
        return False, f"Could not run pip via {python!r}."

    output_lines: List[str] = []
    try:
        assert process.stdout is not None
        for line in process.stdout:
            line = line.rstrip()
            if line:
                output_lines.append(line)
                log(line)
        process.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        process.kill()
        return False, "pip timed out."

    ok = process.returncode == 0
    return ok, "\n".join(output_lines[-40:])  # tail, for error context


def install_dependencies(
    venv_dir: Optional[str] = None,
    spec: str = SAVANA_INSTALL_SPEC,
    log_callback: Optional[Callable[[str], None]] = None,
) -> Tuple[bool, str]:
    """Upgrade pip, then install savana (+ extras) into the venv."""
    venv_dir = venv_dir or VENV_DIR
    log = log_callback or _log

    log("Upgrading pip ...")
    ok, msg = _run_pip(
        ["install", "--upgrade", "pip"], venv_dir, log_callback, timeout=600
    )
    if not ok:
        return False, f"pip upgrade failed:\n{msg}"

    pip_args, description = resolve_install_spec(spec)
    log(f"Installing {description} (this can take several minutes) ...")
    ok, msg = _run_pip(pip_args, venv_dir, log_callback, timeout=3600)
    if not ok:
        return False, f"Install of {description} failed:\n{msg}"

    try:
        with open(MARKER_FILE, "w", encoding="utf-8") as f:
            f.write(description)
    except OSError:
        pass  # marker is a convenience, not required for correctness

    return True, f"Installed {description} successfully."


def verify_venv(
    venv_dir: Optional[str] = None,
    log_callback: Optional[Callable[[str], None]] = None,
) -> Tuple[bool, str]:
    """Import savana in the venv and report its version, as a smoke test."""
    venv_dir = venv_dir or VENV_DIR
    python = get_venv_python_path(venv_dir)
    code = (
        "import savana, savana.rainfall, os; "
        "print(getattr(savana, '__version__', 'unknown')); "
        "print(os.path.dirname(os.path.dirname(savana.__file__)))"
    )
    try:
        result = subprocess.run(
            [python, "-c", code],
            capture_output=True,
            text=True,
            timeout=120,
            **_subprocess_kwargs(),
        )
    except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
        return False, f"Verification could not run: {exc}"

    if result.returncode != 0:
        return False, f"savana failed to import in the venv:\n{result.stderr.strip()}"

    lines = result.stdout.strip().splitlines()
    version = lines[0] if lines else "unknown"
    location = lines[1] if len(lines) > 1 else ""
    # Distinguish an editable install of the user's repo from a plain
    # PyPI install -- otherwise both just report the same version number
    # and it's easy to think a local fix is live when it isn't.
    if "site-packages" in location.replace("/", os.sep).lower():
        origin = "installed from PyPI"
    else:
        origin = f"EDITABLE, loaded from {location}"
    return True, f"savana {version} is importable in the managed venv ({origin})."


def create_venv_and_install(
    venv_dir: Optional[str] = None,
    spec: str = SAVANA_INSTALL_SPEC,
    log_callback: Optional[Callable[[str], None]] = None,
) -> Tuple[bool, str]:
    """Full one-call setup: create venv, install savana, verify import.

    This is what the "Install / Repair environment" button calls (on a
    worker thread). Each step short-circuits with a clear message on
    failure so the panel can surface exactly what went wrong.
    """
    ok, msg = create_venv(venv_dir, log_callback)
    if not ok:
        return False, msg

    ok, msg = bootstrap_pip(venv_dir, log_callback)
    if not ok:
        return False, msg

    ok, msg = install_dependencies(venv_dir, spec, log_callback)
    if not ok:
        return False, msg

    ok, msg = verify_venv(venv_dir, log_callback)
    if not ok:
        return False, msg

    return True, msg


def get_venv_status() -> Tuple[bool, str]:
    """Quick readiness check for the UI: (ready, human-readable status)."""
    if not venv_exists():
        return False, "Not installed. Click 'Install environment' to set up savana."
    if not os.path.isfile(MARKER_FILE):
        return False, "Environment exists but savana isn't confirmed installed."
    return True, "Savana environment is ready."


def remove_venv(venv_dir: Optional[str] = None) -> Tuple[bool, str]:
    """Delete the managed venv (for a clean reinstall)."""
    import shutil

    venv_dir = venv_dir or VENV_DIR
    if not os.path.isdir(venv_dir):
        return True, "Nothing to remove."
    try:
        shutil.rmtree(venv_dir)
    except OSError as exc:
        return False, f"Could not remove venv: {exc}"
    return True, "Environment removed."
