"""Run savana work in the managed venv, off the QGIS UI thread.

Two layers:

- :class:`SubprocessWorker` is a ``QObject`` that runs a given Python
  script (as source text) using the managed venv's interpreter in a
  child process, streaming its stdout lines out as Qt signals and
  emitting a final ``finished(success, message)``. It's moved onto a
  ``QThread`` by the panel so the potentially very slow savana call
  (a 20-year Earth Engine ingestion, say) never blocks QGIS's UI.

- :func:`run_script_in_thread` is the convenience the panels actually
  call: it wires up the QThread + worker + signal connections and hands
  back both so the panel can keep references (Qt will garbage-collect a
  thread out from under you otherwise) and connect its own slots.

Why a subprocess and not just importing savana in QGIS's Python? Because
savana's heavy deps (earthengine-api, geemap, xarray, geopandas) live in
the *managed venv*, not QGIS's Python — see :mod:`..core.venv_manager`.
The subprocess is how we reach them.

All savana calls are expressed as small self-contained scripts that read
their inputs from a JSON file and write their outputs (status, result
file paths) to another JSON file, so nothing needs to be importable on
the QGIS side. The panels build those scripts.
"""

from __future__ import annotations

import os
import subprocess
from typing import Optional, Tuple

from qgis.PyQt.QtCore import QObject, QThread, pyqtSignal


class SubprocessWorker(QObject):
    """Runs one Python script in the managed venv, streaming output."""

    progress = pyqtSignal(str)  # a line of stdout
    finished = pyqtSignal(bool, str)  # (success, final message)

    def __init__(self, python_exe: str, script: str, workdir: Optional[str] = None):
        super().__init__()
        self._python = python_exe
        self._script = script
        self._workdir = workdir
        self._cancelled = False
        self._process: Optional[subprocess.Popen] = None

    def cancel(self) -> None:
        """Request cancellation; kills the child process if running."""
        self._cancelled = True
        if self._process and self._process.poll() is None:
            try:
                self._process.kill()
            except Exception:  # noqa: BLE001
                pass

    def run(self) -> None:
        """Execute the script. Intended to be invoked via QThread.started."""
        kwargs: dict = {}
        if os.name == "nt":
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            kwargs["startupinfo"] = startupinfo
            kwargs["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0)

        try:
            self._process = subprocess.Popen(
                [self._python, "-u", "-c", self._script],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
                cwd=self._workdir,
                **kwargs,
            )
        except FileNotFoundError:
            self.finished.emit(False, f"Could not launch interpreter: {self._python}")
            return

        assert self._process.stdout is not None
        tail: list[str] = []
        for line in self._process.stdout:
            if self._cancelled:
                break
            line = line.rstrip()
            if line:
                tail.append(line)
                if len(tail) > 60:
                    tail.pop(0)
                self.progress.emit(line)

        self._process.wait()

        if self._cancelled:
            self.finished.emit(False, "Cancelled.")
        elif self._process.returncode == 0:
            self.finished.emit(True, "\n".join(tail[-10:]) or "Done.")
        else:
            self.finished.emit(
                False,
                "Process failed (exit code "
                f"{self._process.returncode}):\n" + "\n".join(tail[-15:]),
            )


def run_script_in_thread(
    python_exe: str,
    script: str,
    on_progress,
    on_finished,
    workdir: Optional[str] = None,
) -> Tuple[QThread, SubprocessWorker]:
    """Create + start a QThread running ``script`` in the given interpreter.

    Args:
        python_exe: Path to the managed venv's python.
        script: Python source to execute.
        on_progress: slot taking one ``str`` (a stdout line).
        on_finished: slot taking ``(bool, str)``.
        workdir: optional working directory for the child process.

    Returns:
        (thread, worker). **The caller must keep references to both** or
        Qt will destroy the thread mid-run. Cleanup (quit/wait/delete) is
        wired up here on the worker's ``finished`` signal.
    """
    thread = QThread()
    worker = SubprocessWorker(python_exe, script, workdir=workdir)
    worker.moveToThread(thread)

    thread.started.connect(worker.run)
    worker.progress.connect(on_progress)
    worker.finished.connect(on_finished)

    # Teardown once the work is done.
    worker.finished.connect(thread.quit)
    worker.finished.connect(worker.deleteLater)
    thread.finished.connect(thread.deleteLater)

    thread.start()
    return thread, worker
