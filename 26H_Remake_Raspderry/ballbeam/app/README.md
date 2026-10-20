# 上位机应用职责

`main.py` 只组装对象、连接回调、启动流程和清理资源；不要在这里定义参数、画图或实现滤波。

| 文件 | 职责 |
| --- | --- |
| `main.py` | 创建客户端和角度历史，明确连接收发、视觉、任务和输出 |
| `arguments.py` | 全部正式运行参数的统一声明、单值及关联校验；调用 config.py 加载 TOML 与命令行覆盖 |
| `tracking.py` | TrackingComponents 保存组件；build_tracking_components 创建组件；process_frame 组织单帧处理；run_tracking_loop 管理相机生命周期和逐帧调用 |
| `detector_setup.py` | 通过模型解析、部署校验、后端选择、检测器创建和预热接口组装检测器 |
| `task_startup.py` | TaskSpec/TASKS 定义任务差异，select_task 选择模式与任务；独立准备函数、通用启动函数和 TaskRunner 各自负责自己的流程或状态 |
| `../vision/angles.py` | `AngleHistory` 保存与插值角度；`FrameAngleSource` 为图像匹配角度并应用延迟、边界策略 |
| `../vision/metrics.py` | 一个滑动窗口统一计算循环 FPS、有效模型检测结果频率和平均耗时，返回统计快照 |
| `../vision/calibration.py` | 动态标定、透视展开和粗 ROI 一致性检查 |
| `../recording/capture.py` | 创建记录器、控制采集窗口、保存测试参数和关闭记录 |
| `../recording/csv_recorders.py` | 三种 CSV 的列定义、行整理和采集时间窗，不直接写文件 |
| `../recording/csv_writer.py` | 共用的 CSV 文件操作、有限队列和后台写盘；正常关闭时排空队列 |
| `../interfaces/presentation.py` | `VisionReporter` 管理报告周期，`TrackingDisplay` 管理画面回退及按键；同时提供页面、图传和采集完成提示接口 |

`../vision/ball_state.py` 只检查测量有效性并整理为 `BallState`，不平滑或修改有效测量值；它不认识客户端、文件或页面。无效测量保留上一组数值，但明确标为无效。
`../communication/` 只负责协议、串口收发、模式确认和周期发送，不加载模型。
`../hardware/` 负责设备访问，模型与图像算法归 `../vision/`。

文件归属按职责划分，不为每个类单建文件。角度服务合并到 `vision/angles.py`；模式请求确认类 `ModeRequest` 归 `communication/session.py`，字节流组帧类 `FrameDecoder` 归 `communication/protocol.py`。client 对外接口不变，旧路径不保留转发空壳。`app/vision_geometry.py` 已移除：一致性检查归标定，未调用的 ROI 绘制副本删除；Support 的前置视觉工具不受影响。

`../vision/detection_runtime/detector.py` 中保留四个独立组件，不按代码片段拆文件：`ModelInference` 管理后端及预测结果整理，`OpticalFlowTracker` 管理光流状态，`CircleRefinementCache` 管理圆拟合关联与复用，`AdaptiveBallDetector` 只协调检测周期和这些组件。共享尺寸及 letterbox 预处理归 `preprocessing.py`，不归任何具体后端。

`CaptureSession.finish_if_needed()` 只关闭采集并返回是否刚结束；`main` 根据返回值解除通信回调、调用报告接口。CSV 记录器不修改客户端，不内嵌 SCP 地址或本地目录。

## 模式与任务

模式和任务在 `task_startup.py` 的 `TASKS` 集中登记。RUN 当前默认任务为 1，TUNING 默认任务为 1；两种模式的 task 0 均用于自动初始化，不作为运动任务选择。`--mode run --task-id 1` 显式选择正式任务；球速阶跃使用 `--mode tuning --task-id 1 --velocity-test 2 --task-console --task1-csv <路径>`。省略模式和任务号时，旧 `--velocity-test` 命令仍选择 TUNING/1，否则选择 RUN/1。

这些任务相关定义统一放在一个文件，不单独保留 tasks.py：任务差异、任务参数初始化、通用启动流程、运行中结果检查通过独立的类与函数形成边界，不因合并文件而揉进同一个大函数或大类。

新增任务时，登记 `TaskSpec` 的名称和可选 `initialize`、`validate` 函数；无专用初始化工作就留空。`initialize_task_startup()` 固定执行MCU初始化、任务初始化接口、人工确认，`wait_for_operator_start(task_id)` 不为每个编号新建函数。MCU 对应动作登记在 `PiControl.cpp` 的 `kTasks`；上位机配置并不能替代下位机动作实现。通信会话只检查编号是否能编码，不维护应用任务白名单。

具体速度任务负责生成参数记录，再调用 `CaptureSession.save_settings(filename, settings)` 保存。采集管理器不解释 PID 或任务编号。

本次初始化由 task 15 改为 task 0，`request_seq=0` 专用于无任务请求，真实任务请求使用 1..65535 并在回绕时跳过 0。必须配套更新 Pi 和重新烧录 MCU，帧长度不变不代表旧固件兼容。

## 两条主线

1. 遥测角度 → `client.record_actual_angle` → `angles.record()` → `frame_angles.for_frame()` → 跟踪器动态标定。
2. 跟踪结果 → `ball_states.update()` → `client.publish_ball_state()` → 通信线程按周期打包发送。

在 `main.run()` 中直接查看 `handle_result()`，就能看到第二条链路；这里不会调用另一套隐藏的控制器。

## 添加参数

只在 `arguments.py` 的 `ARGUMENTS` 添加一条声明，例如：

```python
(("--fps",), dict(type=float, check=lambda v: v > 0)),
```

标准设置直接交给 argparse；`check` 是最终合并值的可选约束，TOML 与命令行使用同一条规则。浮点值统一排除 NaN/Inf。
只有参数之间的关系放入 `CONSTRAINTS`，无需逐项修改创建器或解析器。`tracking_arguments.py` 已合并移除。

## 运行约定

- Pi 发送前的附加滤波及对应命令行、TOML 配置已删除；CSV 列和输出路径保留，启动入口仍为 `best/run.py`。
- 图像时间是 Pi 读取完成时间；遥测时间是 Pi 接收时间，不是硬件同步采样时间。
- 终端和图像显示共用统计快照的 FPS；`valid_detect_hz` 表示有效模型检测结果频率，不是模型调用频率，不再估算 `track_hz`。平均推理耗时包含报告了正推理耗时的失败检测；平均处理耗时取跟踪器的 `processing_ms`，不是整个循环含显示、回调的耗时。
- 100 ms 视觉有效期从传入的图像时间计算，不从推理完成时重新计算。
- 角度插值要求两侧样本都在允许时间差内；长空档只允许取足够近的真实样本，否则判无角度。
- 启用文件采集时，三个记录器共用一个 `CsvWriter` 后台线程，通信回调只整理数据、非阻塞入队。队列默认4096行；队列满或写盘失败会报告错误，`output.dropped_rows` 记录丢行数，`output.error` 保存错误。
- 发包记录回调接收 `(packet, sent_at)`；`packet` 是协议解码结果，客户端和记录器不直接读取字节偏移。
- `--task-console` 的 Ctrl+C 保留立即退出 Pi 的行为，不保证运行清理代码或排空待写日志，MCU 需要手动复位。完整采集应先等采集窗口结束。
- 本次整理不改变帧布局；旧 `balance_runtime.py`、`tracking_support.py` 已移除，不再作为学习入口。

## 任务扩展与最终视觉状态

任务编号以模式解释，球速阶跃使用协议常量 `TUNING_TASK_VELOCITY=1`。TaskSpec.validate 和 TaskSpec.initialize 保存专用校验及初始化；公共参数解析器不再硬编码球速任务编号。新增业务应登记自己的回调，不向公共启动流程追加业务分支。

`main.run()` 显式创建 `BallStateBuilder(state_source=measurement_state)`。`measurement_state()` 是当前数据来源策略：测量位置优先、缺失时回退跟踪位置，速度取跟踪输出，不额外滤波。它返回 `BallState(position_cm, velocity_cm_s, valid, measured_at)`。Builder 只校验并在无效时保留上一组最终数值，不重新读取原始字段。未来在本视觉模块替换 state_source，即可接入处理后的最终状态；客户端和协议不变，原始 result 仍留给诊断记录。
