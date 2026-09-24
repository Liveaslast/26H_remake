# 资料与 CSV 格式

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

下位机 USART6 调试打印有三种固件模式：

| 固件命令 | 频率 | 用途 |
|---|---:|---|
| **csv control** | 5 ms / 200 Hz | Task1 和控制过程分析；MCU 启动后默认模式。 |
| **csv vision** | 5 ms / 200 Hz | 视觉包到达、valid、延迟和下位机估计质量分析。 |
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
