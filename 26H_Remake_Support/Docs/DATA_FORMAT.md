# 资料与 CSV 格式

本文定义资料和记录字段，不定义视觉算法或控制策略。源码入口为正式 Pi 的 `ballbeam/recording/csv_recorders.py`、MCU 的 `APP/src/DebugTask.cpp` 和本工程的 `Diagnostics/APP/capture_mcu_csv.py`。线格式以[通信说明](../../26H_Remake_Raspderry/ballbeam/communication/README.md)为准；历史 CSV 不回写。

`target_v` 是MCU外环目标速度；按 `control_ms` 去重比较控制输入。`velocity_settings.json` 用 `pid_applied_telemetry=true` 记录参数确认，不使用通用命令ACK。

## 标定

- **Data/Calibration/active/dynamic_calibration_12_30deg.json**：正式标定 JSON 的参考副本。
- **Data/Calibration/angle_12_30deg/source_images**：标定来源图，共 10 张。
- **Data/Calibration/angle_12_30deg/rectified_images**：对应展开图，共 10 张。
- **Data/Calibration/generated**：按需部署 Pi 端工具后，重新标定的结果；不自动变成正式配置。

正式 JSON 与此参考副本的 **samples** 均为 12、14、16、18、20、22、24、26、28、30°。角点和位置映射在 JSON 中；来源没有独立点位 TXT。

## 训练资料

**Data/Training/steel_ball_12_30deg_exp10/by_angle** 按 12、14、16、18、20、22、24、26、28、30°分组：

- **images/\*.png**：640×128 ROI。
- **labels/\*.txt**：同名 YOLO 标签，格式为 **class x_center y_center width height**。
- **source_records/**：不可改写的原采集会话和逐帧 metadata。

完整资料为 2405 张图片和 2405 个配对标签。

资料集整理脚本先读会话根目录的 **session.json**；没有时读封存的 **source_records/capture_session.json**。因此十个 **by_angle/angle_\*** 目录可直接作为 **--source**，无需改写资料。整理时校验图片、标注和采集时的 **geometry_id**；这是资料内部一致性检查，不是 HEF／生效标定的自动匹配检查。

## 下位机 CSV 模式

下位机 USART6 调试打印有四种固件模式：

| 固件命令 | 频率 | 用途 |
|---|---:|---|
| **csv control** | 5 ms / 200 Hz | Task1 和控制过程分析；MCU 启动后默认模式。 |
| **csv vision** | 5 ms / 200 Hz | 视觉包到达、valid、延迟和下位机估计质量分析。 |
| **csv sysid** | 5 ms / 200 Hz | 电机实测角度与估计小球运动的系统辨识记录。 |
| **csv off** | — | 关闭周期 CSV 打印。 |

**--firmware-csv unchanged** 表示不发切换命令。模式会保持到再次切换或 MCU 复位。

### control 通道的7列

| # | 字段 | 含义 |
|---:|---|---|
| 1 | **estimated_x_cm** | 下位机使用的球位置估计（a-b滤波）。 |
| 2 | **target_x_cm** | 当前目标位置。 |
| 3 | **estimated_vx_cm_s** | 下位机估计球速度（a-b滤波）。 |
| 4 | **motor_angle_deg** | 编码器实际电机角，不是独立测得的水管角。 |
| 5 | **angle_command_deg** | 控制器目标角度。 |
| 6 | **sequence_stage** | 0=无序列，Task1中1=+5、2=-5；球速调参10=运行、12=结束、13=中止。 |
| 7 | **vision_age_ms** | 最近有效视觉观测的年龄。 |

Task1 文件另加 **t_s** 和 **phase**。

USART6的 `control` 原始行严格为7列，前5列是带符号整数，单位分别为0.01cm、0.01cm/s或0.01°；后2列是未缩放的阶段号和毫秒数。Windows采集器将前5列除以100后再写入工程单位列；旧13列或直接打印小数的固件不兼容。`vision`和 `sysid`通道布局不变。

通过Pi正式程序的 `--task1-csv` 采集时，前述7个控制量沿用 `run_task1.py` 的 `ab_x`、`target_x` 等列名，由同一个 `analyze_task1.py` 分析；不再生成 `bbp_deg/trim_deg/bbp/bpush/btrim/bterm`列。记录器类名 `Task1CsvLogger` 也用于球速实验，不表示MCU一定在RUN/task 1。

Pi 文件另加 `stm32_ms`（下位机时基）、`frame_seq`（遥测帧序号）、`vision_seq`（该估计状态对应的 Pi 周期包序号）以及 `control_ms/control_x/control_v/target_v`。`control_ms` 是外环实际计算时刻，同次更新可重复出现在多行中；按它变化去重，0 表示尚无外环计算。

`vision_seq` 变化表示估计状态对应了新编号的Pi包，**不等于完成新识别**：通信线程按配置周期重复发送最新状态，每次发包递增序号。无效或越界包虽然收到，也可能不被估计器采用，因此接收序号与估计状态序号可能不同。默认周期 10 ms，可由 `ball_state_send_rate_hz` 改变；两种模式的二进制遥测周期统一为20ms。状态估计2ms、外环20ms，USART6 CSV打印周期仍为5ms。实际间隔以采集版本、时间戳和日志为准，对照逐帧probe才能判断视觉何时更新；不据新源码重解释历史数据。

### vision 通道的线上字段

原始行以 **V** 开头，后接 10 个整数：

| # | 字段 | 含义 |
|---:|---|---|
| 1 | **stm32_time_ms** | STM32 时基。 |
| 2 | **rx_seq** | 最近 BALL_STATE 序号。 |
| 3 | **pi_time_ms** | 包内树莓派时间。 |
| 4 | **tracking_valid** | 树莓派追踪有效标志。 |
| 5 | **rx_age_ms** | 最近接收包年龄。 |
| 6 | **packet_x_001cm** | 包内位置，单位 0.01 cm。 |
| 7 | **estimate_valid** | 下位机估计是否有效。 |
| 8 | **estimated_x_001cm** | 下位机估计位置，单位 0.01 cm。 |
| 9 | **estimated_vx_001cms** | 下位机估计速度，单位 0.01 cm/s。 |
| 10 | **vision_age_ms** | 最近有效视觉观测年龄。 |

Windows 采集器会转换成 cm/cm/s，并附加主机时间、**rx_interval_ms**、**record_type**、**rx_present**、**x_changed**、**x_unchanged_ms** 和 **raw_line**。5 ms 完整性必须使用 **stm32_time_ms** 判断，不能用 Windows 的 **rx_interval_ms** 冒充。

视觉通道中的接收序号、位置和跟踪标志来自MCU最新收到的数据，包含估计器没有采用的无效或越界测量；估计位置、速度和有效位来自估计器输出，不能把两组字段视为同一份已采用测量。分析时分别检查接收数据和估计结果的有效性及序号。

### sysid 通道的线上字段

原始行以 **S** 开头，后接 5 个整数：`stm32_time_ms,motor_angle_001deg,estimated_x_001cm,estimated_vx_001cms,sysid_state_valid`。Windows 采集器将三个 0.01 单位的物理量换算成度、cm、cm/s，并写为 `record_type=sysid_sample`。无状态快照或估计状态无效时仍保留行，但 `sysid_state_valid=0`；此时位置和速度是占位或过期值，不能用于辨识。该通道记录估计器输出，不包含 Pi 原始帧详情。

## 树莓派 vision probe

probe 是 **best/run.py** 同一正式视觉进程内的逐帧观测：`app/main.py.handle_result()` 调用 `CaptureSession.record_vision()`，由 `VisionProbeLogger` 格式化并交给共享 `CsvWriteWorker` 排队写盘。它不经过 USART6，不改变识别和坐标计算逻辑；但格式化、排队、后台写盘仍有开销，不能把开启 probe 的帧率无条件当成无 probe 的正式帧率。

| 字段 | 含义 |
|---|---|
| **t**、**frame_seq** | 帧时间和 probe 行序号。 |
| **result_ready_t**、**capture_to_log_ms** | 记录器构建该行时刻及其相对图像读取时刻的差值；不是文件实际落盘完成时间。 |
| **inference_ms** | 当前模型后端推理耗时，不限定 Hailo。 |
| **refinement_ms** | 可选圆拟合节点耗时；是否启用与坐标来源须结合配置、source 判断。 |
| **processing_ms** | 本帧视觉总处理耗时。 |
| **raw_x_cm**、**raw_vx_cm_s** | `DynamicTrackingResult.position_cm/velocity_cm_s`；虽名 raw，启用可选估计时也可能是跟踪输出，不等于直接测量。 |
| **sent_x_cm**、**sent_vx_cm_s** | 最终 `BallState` 提交给客户端的值；逐帧记录不等于串口逐帧实际发包。 |
| **measurement_valid** | 本帧是否有有效测量。 |
| **tracking_valid** | tracker 是否保持有效。 |
| **sent_valid** | 提交客户端的 `BallState.valid`，不保证此后实际发包仍有效，发送时另查 100 ms 时效。 |
| **confidence**、**source**、**reason** | 置信度、来源和无效/回退原因。 |
| **actual_angle_deg** | 与该帧匹配的下位机实际角度。 |
| **center_x_px**、**center_y_px**、**radius_px** | 检测中心和半径诊断值。 |
| **measurement_x_cm** | 本帧直接测量位置。 |
| **kalman_x_cm**、**kalman_vx_cm_s** | 兼容分析器的字段名；正式命令未启用树莓派 Kalman，不能因列名判定 Kalman 已开。 |

probe 回答“树莓派产生了甚么”；下位机 **vision** CSV 回答“STM32 收到及估计成甚么”；**control** CSV 回答“控制器如何使用估计结果”。联合对齐才能区分问题在识别、传输还是下位机估计。

视觉输出约定：直接测量留在 `measurement_x_cm`，时序跟踪输出留在结果字段，最终控制输入统一为 `BallState(position_cm, velocity_cm_s, valid, measured_at)`。默认来源由 `measurement_state` 明确选择，新增处理应替换/扩展该来源，不能在客户端重新取原始字段绕过它。未启用 Pi 估计时，当前默认速度为 0，不可把列名误读为独立真实速度测量。

指定 `--task1-csv` 时，同目录另有 **ball_state_tx.csv**，记录通过本地串口成功写入的 RUN/TUNING 周期包。文件名是兼容名，当前帧名以协议说明为准。`seq` 对应 control CSV 的 `vision_seq`；`pi_time_ms` 是包内时间，`write_done_t` 是本地串口写入调用完成时刻，不是 MCU 接收或执行时刻；`position_001cm`、`velocity_001cms` 是精确量化值，另有 `tracking_valid`、`task_request_id` 和 `capture_requested`。

日志不增加串口流量，也不代表远端确认。没有出现在 MCU `vision_seq` 中的包不一定被拒绝，也可能未抵达或被后续包覆盖。MCU 对超出 ±11 cm 的有效位置不更新估计器，沿上一有效状态短时预测，超时后失效。

当前 ball_state_tx.csv 保留既有列，并增加 `request_seq` 与 `mode`（1=RUN、2=TUNING）；`task_request_id` 为包内真实任务 ID，不从 flags 提取。`capture_requested` 是兼容列，表示是否 TUNING，不是请求切换遥测类型的标志。

请求号、包号和参数版本的定义由本文开头链接的协议约定维护；记录中的编号不能当作新图像或新动作的直接证据。
