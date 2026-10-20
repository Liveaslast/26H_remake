"""All formal-runtime CLI declarations and validation live in this file.

Add one row to ARGUMENTS using standard argparse options.
Optional check(value) returns whether the final value is acceptable.
Defaults come from config/runtime.toml unless declared here; CLI overrides TOML.
"""
"""
统一声明、解析和校验正式程序命令行参数

"""
import argparse
import math
from pathlib import Path

from ..config import add_config_argument, parse_args_with_config
from ..paths import WORKSPACE_ROOT
from ..vision.calibration import DynamicCalibrationError, SourceRoi
from .task_startup import select_task


# 定义命令行
ARGUMENTS = (
    (("--calibration",), dict(type=Path)),
    (("--model",), dict(type=Path)),
    (("--allow-historical-ncnn-geometry",), dict(
        action="store_true",
        default=False,
        help="仅试验：允许已核对的历史NCNN模型与当前标定geometry_id不一致；不修改模型来源记录",
    )),
    (("--image-size",), dict(type=int, check=lambda v: v >= 0 and v % 32 == 0, help="0表示从NCNN metadata.yaml自动读取（默认：0）")),
    (("--model-width",), dict(type=int, check=lambda v: v >= 32 and v % 32 == 0)),
    (("--model-height",), dict(type=int, check=lambda v: v >= 32 and v % 32 == 0)),
    (("--confidence",), dict(type=float, check=lambda v: 0 <= v <= 1)),
    (("--iou",), dict(type=float, check=lambda v: 0 <= v <= 1)),
    (("--max-detections",), dict(type=int, check=lambda v: v >= 1)),
    (("--ncnn-backend",), dict(
        choices=("auto", "cpp", "ultralytics"),
        help="auto prefers native C++ and safely falls back to Ultralytics",
    )),
    (("--inference-backend",), dict(
        default="hailort",
        choices=("ncnn", "hailo", "hailort"),
        help="hailort uses the Hailo AI HAT; ncnn keeps the CPU backend; hailo uses Ultralytics",
    )),
    (("--hailo-model",), dict(
        type=Path,
        default=WORKSPACE_ROOT / "assets/models/hailo",
        help="Ultralytics Hailo export directory containing best.hef",
    )),
    (("--ncnn-threads",), dict(type=int, check=lambda v: v >= 1)),
    (("--disable-circle-refinement",), dict(
        action="store_true",
        default=False,
        help="Use YOLO bounding-box center directly; skip circle fitting and its cache",
    )),
    (("--speed-mode",), dict(choices=("precision", "balanced", "performance"), help="precision is the control-loop default")),
    (("--detection-interval",), dict(
        type=int,
        check=lambda v: v >= 1,
        help="run NCNN every N frames; checked LK flow fills intermediate frames",
    )),
    (("--refine-interval",), dict(type=int, check=lambda v: v >= 0, help="0 uses the speed-mode preset; precision preset is 3")),
    (("--track-scale",), dict(
        type=float,
        check=lambda v: 0 < v <= 1,
        help="optical-flow scale in (0,1]; narrow ROI uses 1.0 for accuracy",
    )),
    (("--camera",), dict()),
    (("--width",), dict(type=int, check=lambda v: v >= 2)),
    (("--height",), dict(type=int, check=lambda v: v >= 2)),
    (("--fps",), dict(type=float, check=lambda v: v > 0)),
    (("--camera-fourcc",), dict(check=lambda v: len(v) == 4)),
    (("--camera-buffer-size",), dict(type=int, check=lambda v: v >= 1)),
    (("--camera-read-timeout-ms",), dict(type=float, check=lambda v: v > 0)),
    (("--exposure-time-absolute",), dict(
        type=int,
        check=lambda v: v >= 1,
        help="UVC exposure in 100us units; use a short fixed value for motion",
    )),
    (("--allow-dynamic-framerate",), dict(action="store_true", default=False)),
    (("--lock-dynamic-framerate",), dict(
        action="store_false",
        dest="allow_dynamic_framerate",
        default=True,
        help=argparse.SUPPRESS,
    )),
    (("--warmup-frames",), dict(type=int, check=lambda v: v >= 0)),
    (("--skip-detector-warmup",), dict(
        action="store_true",
        default=False,
        help="skip the model warmup inference before opening camera/serial",
    )),
    (("--maximum-lost-ms",), dict(type=float, check=lambda v: v > 0)),
    (("--reset-after-ms",), dict(type=float, check=lambda v: v > 0)),
    (("--confirmation-hits",), dict(type=int, check=lambda v: v >= 1)),
    (("--measurement-center",), dict(
        choices=("refined", "bbox"),
        help="refined uses RANSAC/cached circle center; bbox uses YOLO box center",
    )),
    (("--association-gate-cm",), dict(type=float, check=lambda v: v > 0)),
    (("--physical-range-margin-cm",), dict(type=float, check=lambda v: v >= 0)),
    (("--minimum-radius-px",), dict(type=float, check=lambda v: v > 0)),
    (("--maximum-radius-height-ratio",), dict(type=float, check=lambda v: 0 < v <= 1)),
    (("--ransac-measurement-std-cm",), dict(type=float, check=lambda v: v > 0)),
    (("--yolo-measurement-std-cm",), dict(type=float, check=lambda v: v > 0)),
    (("--kalman-initial-position-std-cm",), dict(type=float, check=lambda v: v > 0)),
    (("--kalman-initial-velocity-std-cm-s",), dict(type=float, check=lambda v: v > 0)),
    (("--kalman-minimum-dt-ms",), dict(type=float, check=lambda v: v > 0)),
    (("--kalman-maximum-dt-ms",), dict(type=float, check=lambda v: v > 0)),
    (("--enable-kalman",), dict(
        action="store_true",
        default=False,
        help="enable Raspberry Pi Kalman prediction/filtering; default sends raw measurements",
    )),
    (("--refinement-score-bonus",), dict(type=float, check=lambda v: v >= 0)),
    (("--association-distance-penalty",), dict(type=float, check=lambda v: v >= 0)),
    (("--process-acceleration-std", "--process-acceleration-std-cm-s2"), dict(
        type=float,
        dest="process_acceleration_std_cm_s2",
        check=lambda v: v > 0,
        help="Kalman process acceleration standard deviation in cm/s^2",
    )),
    (("--velocity-lowpass-tau-ms",), dict(
        type=float,
        check=lambda v: v >= 0,
        help="Velocity output low-pass time constant in milliseconds; 0 disables it",
    )),
    (("--vertical-band-min",), dict(type=float, check=lambda v: 0 <= v <= 1)),
    (("--vertical-band-max",), dict(type=float, check=lambda v: 0 <= v <= 1)),
    (("--duration",), dict(type=float, check=lambda v: v >= 0, help="运行秒数，0表示运行到 Ctrl+C")),
    (("--report-period",), dict(type=float, check=lambda v: v > 0)),
    (("--no-display",), dict(action="store_true", default=False)),
    (("--display",), dict(action="store_false", dest="no_display", default=True, help=argparse.SUPPRESS)),
    (("--source-roi-x",), dict(type=int)),
    (("--source-roi-y",), dict(type=int)),
    (("--source-roi-width",), dict(type=int)),
    (("--source-roi-height",), dict(type=int)),
    (("--port",), dict(check=bool)),
    (("--baudrate",), dict(type=int, check=lambda v: v > 0)),
    (("--connect-timeout",), dict(type=float, check=lambda v: v > 0)),
    (("--maximum-angle-age-ms",), dict(type=float, check=lambda v: v > 0, help="相机帧对应角度遥测的最大时间差（默认：100ms）")),
    (("--camera-latency-ms",), dict(type=float, check=lambda v: v >= 0, help="从曝光中心到 read() 返回的估计延迟（默认：16.7ms）")),
    (("--clamp-calibration-angle",), dict(action="store_true", default=True, help="实际角度超出动态标定范围时，夹到标定边界后继续展开")),
    (("--no-clamp-calibration-angle",), dict(
        action="store_false",
        dest="clamp_calibration_angle",
        default=True,
        help="实际角度超出动态标定范围时直接判为视觉无效",
    )),
    (("--gravity-model-gain",), dict(type=float, help="角度加速度模型增益，默认0关闭；确认坐标符号后可从±0.714开始整定")),
    (("--serial-read-timeout-ms",), dict(type=float, check=lambda v: v > 0)),
    (("--serial-write-timeout-ms",), dict(type=float, check=lambda v: v > 0)),
    (("--angle-history-samples",), dict(type=int, check=lambda v: v >= 2)),
    (("--mode",), dict(choices=("run", "tuning"), default=None,
        help="通信模式；省略时兼容旧命令，提供 --velocity-test 则选 tuning，否则选 run")),
    (("--task-id",), dict(type=int, default=None, check=lambda v: 1 <= v <= 15,
        help="所选模式下的运动任务号；省略时使用该模式默认任务，0保留为启动前自动初始化")),
    (("--task-console",), dict(action="store_true", default=False, help="启动时 task init；等待输入所选任务命令；Ctrl+C 只退出树莓派进程")),
    (("--velocity-test",), dict(type=float, check=lambda v: 1 <= abs(v) <= 5, help="球速阶跃任务的带符号目标球速，绝对值 1..5 cm/s；例如 2、-5")),
    (("--task1-csv",), dict(type=Path, help="记录下位机原 Task1 控制 CSV；需与 --task-console 同用")),
    (("--task1-capture-s",), dict(type=float, default=5, check=lambda v: v > 0, help="Task1 请求发出后的 CSV 采集时长，默认 5 秒；不停止控制")),
    (("--velocity-kp",), dict(type=float, default=0.5, check=lambda v: 0 <= v <= 4)),
    (("--velocity-ki",), dict(type=float, default=0, check=lambda v: 0 <= v <= 5)),
    (("--velocity-kd",), dict(type=float, default=0, check=lambda v: 0 <= v <= 0.2)),
    (("--wifi-stream",), dict(action="store_true", default=False, help="在当前跟踪进程内启用WIFI_test MJPEG图传，不重复打开相机")),
    (("--wifi-host",), dict(default="0.0.0.0", check=bool)),
    (("--wifi-port",), dict(type=int, default=8080, check=lambda v: 0 <= v <= 65535)),
    (("--wifi-stream-width",), dict(type=int, default=640, check=lambda v: v >= 2)),
    (("--wifi-stream-height",), dict(type=int, default=360, check=lambda v: v >= 2)),
    (("--wifi-stream-fps",), dict(type=float, default=20, check=lambda v: v > 0)),
    (("--wifi-jpeg-quality",), dict(type=int, default=75, check=lambda v: 1 <= v <= 100)),
    (("--ball-state-send-rate-hz",), dict(
        type=float,
        check=lambda v: 50 <= v <= 100,
        help="fixed MCU BALL_STATE transmit rate; latest vision state wins",
    )),
    (("--vision-probe-csv",), dict(type=Path, help="记录视觉结果与待发送数据到CSV，便于排查视觉问题")),
    (("--vision-probe-print",), dict(action="store_true", default=False, help="在终端打印视觉结果与待发送数据；默认只写CSV/发串口")),
    (("--debug-page",), dict(action="store_true", default=False, help="发布钢球位置、速度、有效性和摆杆实际角度到DebugPage")),
    (("--no-debug-page",), dict(action="store_false", dest="debug_page", default=True, help=argparse.SUPPRESS)),
    (("--debug-host",), dict()),
    (("--debug-port",), dict(type=int, check=lambda v: 0 <= v <= 65535)),
    (("--debug-max-points",), dict(type=int, check=lambda v: v >= 2)),
)

# 定义命令行之间的关联约束
CONSTRAINTS = (
    (lambda a: a.inference_backend not in ("hailo", "hailort") or a.hailo_model is not None,
     "Hailo后端需要 --hailo-model"),
    (lambda a: not a.allow_historical_ncnn_geometry or a.inference_backend == "ncnn",
     "--allow-historical-ncnn-geometry 仅用于NCNN后端"),
    (lambda a: a.reset_after_ms > a.maximum_lost_ms,
     "--reset-after-ms 必须大于 --maximum-lost-ms"),
    (lambda a: a.kalman_maximum_dt_ms >= a.kalman_minimum_dt_ms,
     "--kalman-maximum-dt-ms 不能小于 --kalman-minimum-dt-ms"),
    (lambda a: a.vertical_band_min < a.vertical_band_max,
     "--vertical-band-min 必须小于 --vertical-band-max"),
    (lambda a: a.task1_csv is None or a.task_console,
     "--task1-csv 需要 --task-console"),
)

## 创建参数解析器
def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="actual_angle_deg 动态透视展开 + Hailo/NCNN 检测；正式坐标取 YOLO bbox 中心。",
    )
    add_config_argument(parser)
    for flags, options in ARGUMENTS:
        parser.add_argument(*flags, **{key: value for key, value in options.items() if key != "check"})
    return parser

## 命令行参数检查器
def validate_args(args, parser) -> None:
    # Validate final merged values so TOML and command-line input follow one rule.
    for flags, options in ARGUMENTS:
        dest = options.get("dest", flags[0][2:].replace("-", "_"))
        value = getattr(args, dest)
        if value is None:
            continue
        if isinstance(value, float) and not math.isfinite(value):
            parser.error(f"{flags[0]} 必须是有限数值")
        check = options.get("check")
        if check is not None and not check(value):
            parser.error(f"{flags[0]} 的取值不合法：{value!r}")
    for check, message in CONSTRAINTS:
        if not check(args):
            parser.error(message)
    try:
        SourceRoi(args.source_roi_x, args.source_roi_y,
                  args.source_roi_width, args.source_roi_height).validate_inside((args.width, args.height))
    except (DynamicCalibrationError, TypeError, ValueError) as exc:
        parser.error(str(exc))
    try:
        select_task(args)
    except ValueError as exc:
        parser.error(str(exc))

## 对外总入口
def parse_runtime_args(argv=None):
    parser = build_parser()
    args = parse_args_with_config(
        parser,
        sections=("vision_geometry", "tracking", "detector", "tracker", "debug", "formal_tracking"),
        argv=argv,
    )
    validate_args(args, parser)
    return args
