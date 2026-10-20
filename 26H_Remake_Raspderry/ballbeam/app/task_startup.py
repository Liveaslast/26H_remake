"""Task definitions, selection and startup coordination; no serial parsing."""
"""
任务定义、选择及启动管理模块：
"""
import sys
import time
from dataclasses import dataclass
from typing import Callable

from ..communication.protocol import Mode, TASK_ID_INIT, TUNING_TASK_VELOCITY
from ..errors import RuntimeIOError

# 等待第一份下位机要测的有效电机角度
def wait_for_first_angle(client, angles, timeout_seconds: float):
    deadline = time.perf_counter() + timeout_seconds
    while time.perf_counter() < deadline:
        reading = angles.latest(maximum_age_seconds=timeout_seconds)
        if reading is not None:
            return reading
        time.sleep(0.01)
    detail = client.last_error or "没有收到有效遥测帧"
    raise RuntimeIOError(f"等待 STM32 实际角度超时：{detail}")


"""
任务执行前初始化: 
RUN / TUNING模式下：
    TASK 0（两种模式的TASK 0都是执行以下过程）:
        在26H项目中则指把球杆的初始位置对应的电机角度设置为编码器零点，随后下位机把电机角度设置到21°（21°恰好对应于小球停止在水管0cm处的位置）
"""
def initialize_task_before_start(client) -> bool:
    return wait_for_result(client.task_result, client.request_task(TASK_ID_INIT))


"""
等待任务执行或者参数应用的结果：
    通过查询函数：read_result选择要查询的是任务执行结果还是参数应用结果
    通过请求号：确认要查询的是哪一次任务请求
    注意：目前任务模式分为TUNING 和 RUN,在两种模式下都有相应的任务ID可选择，一个任务的结果包含任务执行结果与参数应用结果
"""
def wait_for_result(read_result, number, timeout_seconds=1.0):
    """Application startup waits on execution results carried by telemetry."""
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        result = read_result(number)
        if result is not None:
            return result
        time.sleep(0.01)
    return False

# RUN任务的参数检查函数
def validate_run_task(args):
    if args.velocity_test is not None:
        raise ValueError("--velocity-test 只用于球速阶跃任务")

# TUNING / task 1 的参数检查函数
def validate_velocity_test(args):
    if args.task_console and args.velocity_test is None:
        raise ValueError("球速阶跃任务需要 --velocity-test 指定目标速度")
    if args.velocity_test is not None and (not args.task_console or args.task1_csv is None):
        raise ValueError("--velocity-test 需要 --task-console 和 --task1-csv")

# TUNING / task 1 的初始化函数
def initialize_velocity_test(client, args, capture):
    """Apply this experiment's parameters, confirm them, then save its settings."""
    revision = client.set_velocity_parameters(
        args.velocity_kp, args.velocity_ki, args.velocity_kd, args.velocity_test,
    )
    if not wait_for_result(client.parameters_result, revision):
        raise RuntimeIOError("球速环参数未在调参遥测中确认应用成功")
    _, task_id, _ = select_task(args)
    capture.save_settings("velocity_settings.json", {
        "task_id": task_id, "target_velocity_cm_s": args.velocity_test,
        "kp": args.velocity_kp, "ki": args.velocity_ki, "kd": args.velocity_kd,
        "pid_write_success": True, "pid_applied_telemetry": True,
        "stop_position_abs_cm": 6.0, "safety_timeout_ms": 8000,
        "capture_seconds": args.task1_capture_s, "diagnostic_frame": "0x85",
    })
    print(f"球速环 PID 已获 MCU 应用确认：Kp={args.velocity_kp:g} "
          f"Ki={args.velocity_ki:g} Kd={args.velocity_kd:g}", flush=True)


@dataclass(frozen=True)
class TaskSpec:                                             # 任务配置容器
    """Only task differences; startup orchestration stays outside this data type."""
    label: str                                              # 1. 任务名称
    initialize: Callable | None = None                      # 2. 任务专用的初始化函数
    validate: Callable | None = None                        # 3. 任务专用的参数检查函数



TASKS = {                                                   # 创建任务对象
    Mode.RUN: {1: TaskSpec("Task1", validate=validate_run_task)},
    Mode.TUNING: {TUNING_TASK_VELOCITY: TaskSpec("球速阶跃", initialize_velocity_test, validate_velocity_test)},
}
DEFAULT_TASKS = {Mode.RUN: 1, Mode.TUNING: TUNING_TASK_VELOCITY}

## 任务选择器： 选择模式、任务编号、任务
def select_task(args):
    """Resolve CLI/config once; legacy --velocity-test commands keep their meaning."""
    mode_name = args.mode or ("tuning" if args.velocity_test is not None else "run")
    mode = Mode[mode_name.upper()]
    task_id = args.task_id if args.task_id is not None else DEFAULT_TASKS[mode]
    try:
        task = TASKS[mode][task_id]
    except KeyError as exc:
        raise ValueError(f"模式 {mode.name} 未配置 task {task_id}") from exc
    if task.validate is not None:
        task.validate(args)
    return mode, task_id, task


"""
等待用户输入任务启动命令:
    eg. 在电机编码器零角度点以及角度设置为21°后，在终端输入task 1并回车，将会启动task 1 
"""
def wait_for_operator_start(task_id: int) -> None:
    """Keep the camera and scrolling diagnostics idle until the operator starts."""
    if not sys.stdin.isatty():
        raise RuntimeIOError("--task-console 需要交互终端")
    expected = f"task {task_id}"
    while True:
        try:
            command = input(f"零点和 ba 21 已设置；确认杆角稳定、球位在 0 cm 且接近静止后，输入 {expected} 并按 Enter：").strip().lower()
        except EOFError as exc:
            raise RuntimeIOError(f"未收到 {expected}，视觉未启动") from exc
        if command == expected:
            return
        print(f"尚未启动；请输入 {expected}。", flush=True)


## 等待人工确认机械零点（确认电机编码器零角度点）
def confirm_mechanical_zero():
    if not sys.stdin.isatty():
        raise RuntimeIOError("--task-console 需要交互终端")
    input("请先把梁放在机械零位；确认安全后按 Enter 设置零点并执行 ba 21：")

"""
通用任务初始化（TASK 1 -> TASK 15):
"""
def initialize_task_startup(client, args, capture, *, task_id, task):
    if not args.task_console:                                               # 判断是否开启终端交互 -> 执行初始化
        return
    if not initialize_task_before_start(client):                            # 判断是否先执行TASK 0初始化
        raise RuntimeIOError("未收到下位机 task init 确认；请勿启动控制任务")
    if task.initialize is not None:                                         # 判断是否执行任务ID对应的专用初始化函数
        task.initialize(client, args, capture)
    wait_for_operator_start(task_id)                                        # 等待任务执行

# 任务启动管理器
class TaskRunner:
    """Submit one selected task after vision is ready, then check its result."""

    def __init__(self, client, *, task_id, enabled, timeout_seconds=1.0):       # 保存任务编号、启动状态、超时参数
        self.client = client
        self.task_id = task_id
        self.pending = enabled
        self.request_seq = None
        self.requested_at = None
        self.timeout = timeout_seconds

    def check_result(self):                                                     # 检查任务启动状态
        if self.request_seq is None:
            return
        accepted = self.client.task_result(self.request_seq)
        if accepted is False or (
            accepted is None and time.monotonic() - self.requested_at > self.timeout
        ):
            raise RuntimeIOError("任务启动失败或未收到执行结果，请检查球位与视觉状态")
        if accepted is True:
            print(f"遥测已确认 task {self.task_id} 启动。", flush=True)
            self.request_seq = None

    def start_if_ready(self, vision_ready):                                     #  检查视觉启动状态
        if not self.pending or not vision_ready or not self.client.visual_state_sent:
            return False
        self.request_seq = self.client.request_task(self.task_id)
        self.requested_at = time.monotonic()
        self.pending = False
        print(f"有效视觉已就绪；task {self.task_id} 将随当前模式数据包发送。"
              "Ctrl+C 只退出树莓派，请手动复位下位机。", flush=True)
        return True
