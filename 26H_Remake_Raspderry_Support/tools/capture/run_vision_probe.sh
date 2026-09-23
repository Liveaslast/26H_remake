#!/usr/bin/env bash
set -euo pipefail

VISION_ROOT="${VISION_ROOT:-$HOME/vision_workspace}"
WORKSPACE_DIR="$VISION_ROOT/workspace"
VENV_DIR="$VISION_ROOT/.venv"
OUTPUT_DIR="$VISION_ROOT/diagnostics"
STAMP="$(date +%Y%m%d_%H%M%S)"
OUTPUT_PATH="${1:-$OUTPUT_DIR/vision_probe_$STAMP.csv}"

mkdir -p "$(dirname "$OUTPUT_PATH")"
cd "$WORKSPACE_DIR"
source "$VENV_DIR/bin/activate"

echo "vision probe: $OUTPUT_PATH"

exec python3 best/run.py \
  --port /dev/ttyUSB0 \
  --inference-backend hailort \
  --debug-page \
  --serial-read-timeout-ms 1 \
  --wifi-stream \
  --no-display \
  --vision-probe-csv "$OUTPUT_PATH"
