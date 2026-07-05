#!/usr/bin/env python3
"""Fail the commit if pyproject.toml and savana/__init__.py disagree on version.

This exists because bump-my-version keeps both files in sync automatically,
but nothing stops a manual hand-edit of just one of them. This script is
run as a local pre-commit hook to catch that before it reaches PyPI.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent


def _extract(path: Path, pattern: str) -> str | None:
    text = path.read_text()
    match = re.search(pattern, text, flags=re.MULTILINE)
    return match.group(1) if match else None


def main() -> int:
    pyproject_path = REPO_ROOT / "pyproject.toml"
    init_path = REPO_ROOT / "savana" / "__init__.py"

    pyproject_version = _extract(pyproject_path, r'^\s*version\s*=\s*"([^"]+)"')
    init_version = _extract(init_path, r'__version__\s*=\s*"([^"]+)"')

    if pyproject_version is None:
        print(f'ERROR: could not find `version = "..."` in {pyproject_path}')
        return 1
    if init_version is None:
        print(f'ERROR: could not find `__version__ = "..."` in {init_path}')
        return 1

    if pyproject_version != init_version:
        print(
            "ERROR: version mismatch between pyproject.toml and savana/__init__.py\n"
            f"  pyproject.toml         -> {pyproject_version}\n"
            f"  savana/__init__.py     -> {init_version}\n"
            "Fix by running: bump-my-version bump patch   (or edit both by hand to match)"
        )
        return 1

    print(f"Version OK: {pyproject_version}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
