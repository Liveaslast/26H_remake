#!/usr/bin/env bash
set -euo pipefail

VISION_ROOT="${VISION_ROOT:-$HOME/vision_workspace}"
WORKSPACE_DIR="$VISION_ROOT/workspace"
VENV_DIR="$VISION_ROOT/.venv"
DIAGNOSTICS_DIR="$VISION_ROOT/diagnostics"
STATIC_DURATION="${STATIC_DURATION:-10}"
MOTION_DURATION="${MOTION_DURATION:-20}"
EXPOSURE_TIME_ABSOLUTE="${EXPOSURE_TIME_ABSOLUTE:-10}"

if [[ ! "$EXPOSURE_TIME_ABSOLUTE" =~ ^[1-9][0-9]*$ ]]; then
  echo "ERROR: EXPOSURE_TIME_ABSOLUTE must be a positive integer in 100 us units" >&2
  exit 1
fi

if [[ ! -f "$WORKSPACE_DIR/best/run.py" ]]; then
  echo "ERROR: formal vision entry not found: $WORKSPACE_DIR/best/run.py" >&2
  exit 1
fi

if [[ ! -f "$VENV_DIR/bin/activate" ]]; then
  echo "ERROR: virtual environment not found: $VENV_DIR" >&2
  exit 1
fi

mkdir -p "$DIAGNOSTICS_DIR"

RUN_ID="$(date +%Y%m%d_%H%M%S)"
RESULT_DIR="$DIAGNOSTICS_DIR/vision_quality_exp${EXPOSURE_TIME_ABSOLUTE}_$RUN_ID"
mkdir -p "$RESULT_DIR"

cd "$WORKSPACE_DIR"
# shellcheck disable=SC1090
source "$VENV_DIR/bin/activate"

{
  echo "created_at=$(date -Is)"
  echo "workspace=$WORKSPACE_DIR"
  echo "static_duration_s=$STATIC_DURATION"
  echo "motion_duration_s=$MOTION_DURATION"
  echo "exposure_time_absolute=$EXPOSURE_TIME_ABSOLUTE"
  echo "exposure_unit_us=100"
  echo "config=$WORKSPACE_DIR/config/runtime.toml"
} > "$RESULT_DIR/session.txt"

if command -v v4l2-ctl >/dev/null 2>&1; then
  v4l2-ctl -d /dev/video0 \
    --get-ctrl=auto_exposure,exposure_time_absolute,exposure_dynamic_framerate \
    > "$RESULT_DIR/camera_controls_before.txt" 2>&1 || true
fi

echo
echo "第一阶段：静止质量测试"
echo "请先让钢球自然稳定在杆上；准备好后按 Enter，随后保持静止。"
read -r

python3 best/run.py \
  --port /dev/ttyUSB0 \
  --inference-backend hailort \
  --debug-page \
  --serial-read-timeout-ms 1 \
  --wifi-stream \
  --no-display \
  --exposure-time-absolute "$EXPOSURE_TIME_ABSOLUTE" \
  --duration "$STATIC_DURATION" \
  --vision-probe-csv "$RESULT_DIR/static_probe.csv" \
  2>&1 | tee "$RESULT_DIR/static_runtime.log"

echo
echo "第二阶段：自然运动质量测试"
echo "按 Enter 后自由来回推动杆子，让钢球自然往返、反向和偶尔稳定。"
read -r

python3 best/run.py \
  --port /dev/ttyUSB0 \
  --inference-backend hailort \
  --debug-page \
  --serial-read-timeout-ms 1 \
  --wifi-stream \
  --no-display \
  --exposure-time-absolute "$EXPOSURE_TIME_ABSOLUTE" \
  --duration "$MOTION_DURATION" \
  --vision-probe-csv "$RESULT_DIR/motion_probe.csv" \
  2>&1 | tee "$RESULT_DIR/motion_runtime.log"

if command -v v4l2-ctl >/dev/null 2>&1; then
  v4l2-ctl -d /dev/video0 \
    --get-ctrl=auto_exposure,exposure_time_absolute,exposure_dynamic_framerate \
    > "$RESULT_DIR/camera_controls_after.txt" 2>&1 || true
fi

echo
echo "测试完成，结果目录："
echo "$RESULT_DIR"
ls -lh "$RESULT_DIR"
