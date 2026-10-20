# 资料与 CSV 格式

固定球速阶跃测试先通过 0x06/0x86 确认调参模式，随后使用 39 字节 0x08（视觉、参数、测试指令）和 44 字节 0x85（控制数据、执行结果）；Task1 使用 21 字节 0x07 和 42 字节 0x84。target_v 是 MCU 外环实际目标速度，按 control_ms 去重比较 target_v/control_v。速度测试无制动阶段，沿目标方向到 ±6 cm 后回平衡角。参数应用结果随 0x85 返回，velocity_settings.json 用 pid_applied_telemetry=true 记录确认，不再使用通用命令 ACK 或 pid_applied_ack。新旧帧格式不兼容，历史 CSV 不回写。

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

### control 通道的 13 列

| # | 字段 | 含义 |
|---:|---|---|
| 1 | **estimated_x_cm** | 下位机使用的球位置估计（a-b滤波）。 |
| 2 | **target_x_cm** | 当前目标位置。 |
| 3 | **estimated_vx_cm_s** | 下位机估计球速度（a-b滤波）。 |
| 4 | **motor_angle_deg** | 实际电机/杆角度。 |
| 5 | **angle_command_deg** | 控制器目标角度。 |
| 6 | **brake_p_offset_deg** | BBP 制动角度偏移。 |
| 7 | **terminal_offset_deg** | 终端修正角度偏移。 |
| 8 | **brake_p_active** | BBP 是否有效。 |
| 9 | **terminal_push_active** | 终端推动是否有效。 |
| 10 | **terminal_trim_active** | 终端微调是否有效。 |
| 11 | **terminal_brake_gate_active** | 终端制动门是否有效。 |
| 12 | **sequence_stage** | 0=无序列，Task1 中 1=+5、2=-5。 |
| 13 | **vision_age_ms** | 最近有效视觉观测的年龄。 |

Task1 文件另加 **t_s** 和 **phase**。

USART6 的 `control` 原始行仍为 13 列，但前 7 列现在是带符号整数，单位分别为 0.01 cm、0.01 cm/s 或 0.01°；后 6 列是未缩放的整数。Windows 采集器将前 7 列除以 100 后再写入上述工程单位列。旧版直接打印小数的固件与当前采集器不兼容。

通过树莓派正式程序的 `--task1-csv` 采集时，前述 13 个控制量保持同名含义，沿用 `run_task1.py` 生成的 `ab_x`、`target_x` 等 Task1 列名，仍由同一个 `analyze_task1.py` 分析。Pi 文件另加 `stm32_ms`（下位机时基）、`frame_seq`（诊断帧序号）和 `vision_seq`（最近收到的 BALL_STATE 包序号）。新协议还加 `control_ms`、`control_x`、`control_v`：外环当次实际计算的下位机时间、输入位置和输入速度；同一次控制更新可能在多个采样行中重复，用 `control_ms` 变化去重，值为 0 表示尚无外环计算。`vision_seq` 不变说明这段时间未接收新包；变化只说明收到新包，**不等于相机完成一次新识别**：Pi 会按 10 ms 固定周期重复发送最新状态，并为每次发送分配新包序号。当前调参遥测 5 ms、任务遥测 20 ms、状态估计 2 ms、外环 20 ms；对照 Pi 的逐帧 vision probe 才能进一步判断识别何时真正更新。

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

### sysid 通道的线上字段

原始行以 **S** 开头，后接 5 个整数：`stm32_time_ms,motor_angle_001deg,estimated_x_001cm,estimated_vx_001cms,sysid_state_valid`。Windows 采集器将三个 0.01 单位的物理量换算成度、cm、cm/s，并写为 `record_type=sysid_sample`。无状态快照或估计状态无效时仍保留行，但 `sysid_state_valid=0`；此时位置和速度是占位或过期值，不能用于辨识。该通道记录估计器输出，不包含 Pi 原始帧详情。

## 树莓派 vision probe

probe 是 **best/run.py** 同一正式视觉进程内的逐帧观测 CSV：每处理完一个相机帧写一行。它不经过 USART6，不改变识别和坐标计算逻辑；但逐帧写盘本身可能增加耗时，不能把开启 probe 时测得的帧率无条件当成无 probe 的正式帧率。

| 字段 | 含义 |
|---|---|
| **t**、**frame_seq** | 帧时间和 probe 行序号。 |
| **result_ready_t**、**capture_to_log_ms** | 结果完成时间和从帧到落盘的总延迟。 |
| **inference_ms** | Hailo 推理耗时。 |
| **refinement_ms** | 原程序 refinement/RANSAC 路径耗时；正式坐标仍取 bbox 中心。 |
| **processing_ms** | 本帧视觉总处理耗时。 |
| **raw_x_cm**、**raw_vx_cm_s** | 视觉结果位置和速度字段。 |
| **sent_x_cm**、**sent_vx_cm_s** | 提交给 BALL_STATE 发送端的最新值；逐帧记录不等于串口逐帧都实际发包。 |
| **measurement_valid** | 本帧是否有有效测量。 |
| **tracking_valid** | tracker 是否保持有效。 |
| **sent_valid** | 发送状态是否标记有效。 |
| **confidence**、**source**、**reason** | 置信度、来源和无效/回退原因。 |
| **actual_angle_deg** | 与该帧匹配的下位机实际角度。 |
| **center_x_px**、**center_y_px**、**radius_px** | 检测中心和半径诊断值。 |
| **measurement_x_cm** | 本帧直接测量位置。 |
| **kalman_x_cm**、**kalman_vx_cm_s** | 兼容分析器的字段名；正式命令未启用树莓派 Kalman，不能因列名判定 Kalman 已开。 |

probe 回答“树莓派产生了甚么”；下位机 **vision** CSV 回答“STM32 收到及估计成甚么”；**control** CSV 回答“控制器如何使用估计结果”。联合对齐才能区分问题在识别、传输还是下位机估计。

Pi Task1 启动且指定 `--task1-csv` 时，同目录另有 **ball_state_tx.csv**，记录实际写入串口的每个 BALL_STATE 包。`seq` 对应 control CSV 的 `vision_seq`；`pi_time_ms` 是包内时间，`write_done_t` 是 Pi 本地写入完成时刻；`position_001cm`、`velocity_001cms` 是包内精确量化值，另有 `tracking_valid`、`task_request_id` 和 `capture_requested`。此日志不增加串口流量；没有出现在 MCU `vision_seq` 中的包不能仅据此判为“已被拒绝”，也可能未抵达或被后续包覆盖。MCU 对超出 ±11 cm 的有效位置不更新估计器，沿上一有效状态短时预测，超时后失效。

当前 ball_state_tx.csv 保留既有列，并增加 request_seq 与 mode（1 任务、2 调参）；task_request_id 为包内真实任务 ID，不再从 flags 提取。capture_requested 为兼容列，当前表示是否调参模式，不是请求切换遥测类型的标志位。传输 seq 每包递增，request_seq 只在提交新的动作时改变，两者不能混用。当前线格式以 [通信说明](../../26H_Remake_Raspderry/ballbeam/communication/README.md) 为准。
