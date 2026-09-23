#!/usr/bin/env python3
"""Short launcher for the formal Raspberry Pi tracking application."""

from pathlib import Path
import sys

BEST_DIR = Path(__file__).resolve().parent
if str(BEST_DIR) not in sys.path:
    sys.path.insert(0, str(BEST_DIR))

from algorithm.formal.track_ball import main  # noqa: E402


if __name__ == "__main__":
    raise SystemExit(main())
