#!/usr/bin/env python3
"""Compatibility launcher: keep the verified Raspberry Pi command working."""

from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from ballbeam.app.main import main  # noqa: E402


if __name__ == "__main__":
    raise SystemExit(main())
