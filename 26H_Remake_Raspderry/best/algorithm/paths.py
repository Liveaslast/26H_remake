"""Canonical project paths used by training, export, and inference."""

from __future__ import annotations

from pathlib import Path
ALGORITHM_DIR = Path(__file__).resolve().parent
BEST_DIR = ALGORITHM_DIR.parent
WORKSPACE_ROOT = BEST_DIR.parent

# Short canonical model paths used by training, export, and inference.
MODEL_DIR = BEST_DIR / "model"
TRAINED_MODEL = MODEL_DIR / "best.pt"
LAST_MODEL = MODEL_DIR / "last.pt"
NCNN_MODEL_DIR = MODEL_DIR / "ncnn_model"
MODEL_RUNS_DIR = MODEL_DIR / "runs"
