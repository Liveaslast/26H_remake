"""Canonical project paths used by training, export, and inference."""

from __future__ import annotations

from pathlib import Path
CONFIG_DIR = Path(__file__).resolve().parent
VISION_DIR = CONFIG_DIR.parent
SUPPORT_ROOT = VISION_DIR.parent
WORKSPACE_ROOT = SUPPORT_ROOT

# Short canonical model paths used by training, export, and inference.
MODEL_DIR = SUPPORT_ROOT / "Data" / "Training" / "Models"
TRAINED_MODEL = MODEL_DIR / "best.pt"
LAST_MODEL = MODEL_DIR / "last.pt"
NCNN_MODEL_DIR = MODEL_DIR / "ncnn_model"
MODEL_RUNS_DIR = MODEL_DIR / "Runs"
