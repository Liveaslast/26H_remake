#!/usr/bin/env bash
set -euo pipefail

VISION_ROOT="${VISION_ROOT:-$HOME/vision_workspace}"
WORKSPACE="$VISION_ROOT/workspace"
VENV="$VISION_ROOT/.venv"
DURATION="${MOTION_DURATION:-20}"
EXPOSURE_TIME_ABSOLUTE="${EXPOSURE_TIME_ABSOLUTE:-10}"

if [[ ! "$EXPOSURE_TIME_ABSOLUTE" =~ ^[1-9][0-9]*$ ]]; then
  echo "ERROR: EXPOSURE_TIME_ABSOLUTE must be a positive integer in 100 us units" >&2
  exit 1
fi

RUN_ID="$(date +%Y%m%d_%H%M%S)"
RESULT_DIR="$VISION_ROOT/diagnostics/vision_quality_exp${EXPOSURE_TIME_ABSOLUTE}_bright_$RUN_ID"

cd "$WORKSPACE"
mkdir -p "$RESULT_DIR"
# shellcheck disable=SC1090
source "$VENV/bin/activate"

echo "提高光照并准备好钢球后，按 Enter 开始 ${DURATION} 秒动态采集。"
read -r

{
  date -Is
  v4l2-ctl -d /dev/video0 \
    --get-ctrl=auto_exposure,exposure_time_absolute,exposure_dynamic_framerate

  python3 best/run.py \
    --port /dev/ttyUSB0 \
    --inference-backend hailort \
    --debug-page \
    --serial-read-timeout-ms 1 \
    --wifi-stream \
    --no-display \
    --exposure-time-absolute "$EXPOSURE_TIME_ABSOLUTE" \
    --duration "$DURATION" \
    --vision-probe-csv "$RESULT_DIR/motion_probe.csv"
} 2>&1 | tee "$RESULT_DIR/motion_runtime.log"

echo "采集完成：$RESULT_DIR"
ls -lh "$RESULT_DIR"
