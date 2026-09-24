"""Canonical root path of the Raspberry Pi runtime bundle."""

from __future__ import annotations

from pathlib import Path
PACKAGE_DIR = Path(__file__).resolve().parent
WORKSPACE_ROOT = PACKAGE_DIR.parent
