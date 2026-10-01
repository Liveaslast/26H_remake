# Diagnostics｜采集与分析唯一入口

这里负责测试数据的采集与离线分析，不修改正式视觉或下位机控制逻辑。第一次使用先按任务选择下面一条流程；完整参数只到[命令手册](../Docs/COMMANDS.md)查，不在本页重复维护。

## 按任务选择

| 任务 | 采集入口 | 分析入口 | 回答的问题 |
|---|---|---|---|
| Task1 控制过程 | `initialize_zero.py`（仅复位/零点改变后）→ `run_task1.py` | `analyze_task1.py` | 正负向穿越、超调、BBP/BPUSH/BTERM 时序、角度跟随、最终误差和阶段状态 |
| 单份 Pi 视觉质量 | `capture_vision_csv.sh`、`capture_vision_quality.sh` 或 `capture_motion_quality.sh` | `analyze_vision_probe.py` | 帧率、处理耗时、valid、更新空窗、静态抖动及坐标事件 |
| Pi→STM32 视觉链路 | 同时采集 Pi probe 与 `capture_mcu_csv.py --firmware-csv vision` | `analyze_vision.py` | 问题发生在 Pi 识别、串口传输还是 STM32 估计 |

三个 `analyze_*.py` 是当前全部离线分析入口。它们只读 CSV；不要为相同输入和指标另建平行脚本。

## 先分清三类数据

- **probe**：正式 `best/run.py` 每处理一帧写一行，不经过 USART6，也不代表每帧实际发包。
- **vision CSV**：STM32 每 5 ms 打印最近视觉包及内部估计，用于检查接收、valid 和数据年龄。
- **control CSV**：STM32 每 5 ms 打印控制状态，用于 Task1、角度和 BBP/BPUSH 分析。

`capture_mcu_csv.py --mode` 控制是否发送任务命令；`--firmware-csv` 控制固件打印 `vision`、`control` 或关闭，两者不等价。固件复位后默认为 `control`；切到 `vision` 后，运行 Task1 前要切回 `control`。

## 目录与新增文件

- `APP/`：唯一可直接执行的入口；`Core/` 和 `IO/` 只供入口调用。
- 原始 CSV 和整组测试结果放 `Data/TestRecords/`；Pi 可先暂存于 `~/vision_workspace/diagnostics/` 再完整取回。
- 单次试验结论放对应记录目录的 `analysis_summary.md`；可跨试验复用的规则才写进 `Diagnostics/` 或 `Docs/`。
- 新分析能力优先扩展现有三个入口；复用算法放 `Core/`，串口/文件读写放 `IO/`。
- 新增或改变 CSV 列时更新[数据格式](../Docs/DATA_FORMAT.md)；新增命令时更新[命令手册](../Docs/COMMANDS.md)。

## 按需阅读

- [命令手册](../Docs/COMMANDS.md)：可复制执行的完整命令、平台和输出位置。
- [数据格式](../Docs/DATA_FORMAT.md)：control、vision 和 probe 的逐列定义。
- [Task1 2026-09-27 调参复盘](../Data/TestRecords/TASK1_TUNING_20260927.md)：具体实验案例，不是日常操作前置阅读；串口临时覆盖不会写回固件默认 profile。
