#!/usr/bin/env bash
set -euo pipefail

VISION_ROOT="${VISION_ROOT:-$HOME/vision_workspace}"
WORKSPACE_DIR="$VISION_ROOT/workspace"
VENV_DIR="$VISION_ROOT/.venv"
DIAGNOSTICS_DIR="$VISION_ROOT/diagnostics"
STATIC_DURATION="${STATIC_DURATION:-15}"
MOTION_DURATION="${MOTION_DURATION:-15}"
CAMERA_READ_TIMEOUT_MS="${CAMERA_READ_TIMEOUT_MS:-2000}"
EXPOSURE_TIME_ABSOLUTE="${EXPOSURE_TIME_ABSOLUTE:-10}"
EXPOSURE_VALUES="${EXPOSURE_VALUES:-$EXPOSURE_TIME_ABSOLUTE}"
LIGHTING_LABEL="${LIGHTING_LABEL:-}"
INFERENCE_BACKEND="${INFERENCE_BACKEND:-hailort}"
DETECTION_INTERVAL="${DETECTION_INTERVAL:-1}"
if [[ "$INFERENCE_BACKEND" != "hailort" && "$INFERENCE_BACKEND" != "ncnn" ]]; then
  echo "ERROR: INFERENCE_BACKEND must be hailort or ncnn" >&2
  exit 1
fi
if [[ ! "$DETECTION_INTERVAL" =~ ^[1-9][0-9]*$ ]]; then
  echo "ERROR: DETECTION_INTERVAL must be a positive integer" >&2
  exit 1
fi
BACKEND_ARGS=(--inference-backend "$INFERENCE_BACKEND" --detection-interval "$DETECTION_INTERVAL" --disable-circle-refinement)
if [[ "$INFERENCE_BACKEND" == "ncnn" ]]; then
  BACKEND_ARGS+=(--ncnn-backend cpp --allow-historical-ncnn-geometry)
fi

read -r -a EXPOSURES <<< "$EXPOSURE_VALUES"
if (( ${#EXPOSURES[@]} == 0 )); then
  echo "ERROR: EXPOSURE_VALUES must contain at least one exposure value" >&2
  exit 1
fi
declare -A seen_exposures=()
for exposure in "${EXPOSURES[@]}"; do
  if [[ ! "$exposure" =~ ^[1-9][0-9]*$ ]]; then
    echo "ERROR: each exposure must be a positive integer in 100 us units: $exposure" >&2
    exit 1
  fi
  if [[ -n "${seen_exposures[$exposure]+set}" ]]; then
    echo "ERROR: duplicate exposure value: $exposure" >&2
    exit 1
  fi
  seen_exposures[$exposure]=1
done
if [[ -n "$LIGHTING_LABEL" && ! "$LIGHTING_LABEL" =~ ^[a-zA-Z0-9_-]+$ ]]; then
  echo "ERROR: LIGHTING_LABEL may contain only letters, digits, _ and -" >&2
  exit 1
fi
if [[ ! "$STATIC_DURATION" =~ ^[1-9][0-9]*$ || ! "$MOTION_DURATION" =~ ^[1-9][0-9]*$ ]]; then
  echo "ERROR: STATIC_DURATION and MOTION_DURATION must be positive integer seconds" >&2
  exit 1
fi
if [[ ! "$CAMERA_READ_TIMEOUT_MS" =~ ^[1-9][0-9]*$ ]]; then
  echo "ERROR: CAMERA_READ_TIMEOUT_MS must be a positive integer" >&2
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
if ! command -v v4l2-ctl >/dev/null 2>&1; then
  echo "ERROR: v4l2-ctl is required to verify actual camera exposure" >&2
  exit 1
fi

mkdir -p "$DIAGNOSTICS_DIR"

RUN_ID="$(date +%Y%m%d_%H%M%S)"
TRACKING_SUFFIX=""
if (( DETECTION_INTERVAL > 1 )); then
  TRACKING_SUFFIX="_flow${DETECTION_INTERVAL}"
fi
if [[ -n "$LIGHTING_LABEL" || ${#EXPOSURES[@]} -gt 1 ]]; then
  LABEL="${LIGHTING_LABEL:-unspecified}"
  RESULT_ROOT="$DIAGNOSTICS_DIR/vision_quality_${LABEL}_${INFERENCE_BACKEND}${TRACKING_SUFFIX}_$RUN_ID"
else
  RESULT_ROOT="$DIAGNOSTICS_DIR/vision_quality_exp${EXPOSURES[0]}_${INFERENCE_BACKEND}${TRACKING_SUFFIX}_$RUN_ID"
fi
if ! mkdir "$RESULT_ROOT"; then
  echo "ERROR: result directory already exists: $RESULT_ROOT" >&2
  exit 1
fi

cd "$WORKSPACE_DIR"
# shellcheck disable=SC1090
source "$VENV_DIR/bin/activate"

verify_camera_controls() {
  local record_path="$1"
  local expected_exposure="$2"
  v4l2-ctl -d /dev/video0 \
    --get-ctrl=auto_exposure,exposure_time_absolute,exposure_dynamic_framerate \
    > "$record_path" 2>&1
  if ! grep -Eq 'auto_exposure: 1([[:space:]]|$)' "$record_path" ||
     ! grep -Eq "exposure_time_absolute: ${expected_exposure}([[:space:]]|\$)" "$record_path" ||
     ! grep -Eq 'exposure_dynamic_framerate: 0([[:space:]]|$)' "$record_path"; then
    echo "ERROR: camera controls do not match manual exposure $expected_exposure; see $record_path" >&2
    return 1
  fi
}

verify_probe() {
  local probe_path="$1"
  if [[ ! -f "$probe_path" ]] || (( $(wc -l < "$probe_path") < 3 )); then
    echo "ERROR: probe has fewer than two data rows: $probe_path" >&2
    return 1
  fi
}

echo "本轮结果目录：$RESULT_ROOT"
echo "曝光顺序（单位 100 us）：${EXPOSURES[*]}"
echo "检测后端：$INFERENCE_BACKEND；每 ${DETECTION_INTERVAL} 帧 YOLO、其余帧光流、bbox 中心、关闭圆拟合"
echo "开始前请自行完成机械零点初始化；本脚本不会发送 task init 或 ba 21，也不会在各阶段重设零点。"
echo "请确认控制任务已停止，杆角处于 12-30 度标定范围；本轮地面测试建议从 21 度开始。"
echo "请保持暗场照明、相机位置、模型和测试动作一致；每组静态/动态分别确认后开始。"

for exposure in "${EXPOSURES[@]}"; do
  if [[ "$RESULT_ROOT" == "$DIAGNOSTICS_DIR/vision_quality_exp${exposure}_${INFERENCE_BACKEND}${TRACKING_SUFFIX}_$RUN_ID" ]]; then
    RESULT_DIR="$RESULT_ROOT"
  else
    RESULT_DIR="$RESULT_ROOT/exp${exposure}"
  fi
  mkdir -p "$RESULT_DIR"

  {
    echo "created_at=$(date -Is)"
    echo "workspace=$WORKSPACE_DIR"
    echo "lighting_label=${LIGHTING_LABEL:-unspecified}"
    echo "static_duration_s=$STATIC_DURATION"
    echo "motion_duration_s=$MOTION_DURATION"
    echo "camera_read_timeout_ms=$CAMERA_READ_TIMEOUT_MS"
    echo "exposure_time_absolute=$exposure"
    echo "exposure_unit_us=100"
    echo "inference_backend=$INFERENCE_BACKEND"
    echo "detection_interval=$DETECTION_INTERVAL"
    echo "circle_refinement=off"
    echo "config=$WORKSPACE_DIR/config/runtime.toml"
  } > "$RESULT_DIR/session.txt"

  v4l2-ctl -d /dev/video0 \
    --get-ctrl=auto_exposure,exposure_time_absolute,exposure_dynamic_framerate \
    > "$RESULT_DIR/camera_controls_before.txt" 2>&1

  echo
  echo "曝光 $exposure（$((exposure * 100)) us）：第一阶段，静止质量测试（${STATIC_DURATION} 秒）"
  echo "请让钢球自然稳定在同一位置；准备好后按 Enter，采集期间保持静止。"
  read -r

  python3 best/run.py \
    --port /dev/ttyUSB0 \
    "${BACKEND_ARGS[@]}" \
    --debug-page \
    --serial-read-timeout-ms 1 \
    --camera-read-timeout-ms "$CAMERA_READ_TIMEOUT_MS" \
    --wifi-stream \
    --no-display \
    --exposure-time-absolute "$exposure" \
    --duration "$STATIC_DURATION" \
    --vision-probe-csv "$RESULT_DIR/static_probe.csv" \
    2>&1 | tee "$RESULT_DIR/static_runtime.log"
  verify_probe "$RESULT_DIR/static_probe.csv"
  verify_camera_controls "$RESULT_DIR/camera_controls_after_static.txt" "$exposure"
  echo "静态采集结束：$RESULT_DIR/static_probe.csv"

  echo
  echo "曝光 $exposure：第二阶段，自然运动质量测试（${MOTION_DURATION} 秒）"
  echo "准备好后按 Enter，采集期间轻推钢球使其在杆上往返、反向并偶尔稳定；不要强行扳动正在控角的杆。"
  read -r

  python3 best/run.py \
    --port /dev/ttyUSB0 \
    "${BACKEND_ARGS[@]}" \
    --debug-page \
    --serial-read-timeout-ms 1 \
    --camera-read-timeout-ms "$CAMERA_READ_TIMEOUT_MS" \
    --wifi-stream \
    --no-display \
    --exposure-time-absolute "$exposure" \
    --duration "$MOTION_DURATION" \
    --vision-probe-csv "$RESULT_DIR/motion_probe.csv" \
    2>&1 | tee "$RESULT_DIR/motion_runtime.log"
  verify_probe "$RESULT_DIR/motion_probe.csv"
  verify_camera_controls "$RESULT_DIR/camera_controls_after_motion.txt" "$exposure"
  echo "动态采集结束：$RESULT_DIR/motion_probe.csv"

  echo "曝光 $exposure 采集完成：$RESULT_DIR"
done

echo
echo "测试完成，结果目录："
echo "$RESULT_ROOT"
ls -lh "$RESULT_ROOT"
echo "PowerShell 取回目录："
echo 'cd D:\26H-remake\26H_Remake_Support'
echo "scp -r \"ikun@192.168.137.2:$RESULT_ROOT\" '.\\Data\\TestRecords\\'"
