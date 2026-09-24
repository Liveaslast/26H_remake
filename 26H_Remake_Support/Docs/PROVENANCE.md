# Support 资料与工具来源

## 资料

| 现行位置 | 可追溯来源 |
|---|---|
| **Data/Calibration/active/dynamic_calibration_12_30deg.json** | 与 Raspberry **assets/calibration/dynamic_calibration_12_30deg.json** 内容相同，实际含 12、14、…、30°十样本 |
| **Data/Calibration/angle_12_30deg/** | 从树莓派标定输出保存的十张来源图及十张展开图 |
| **Data/Training/steel_ball_12_30deg_exp10/** | 本地 **_pi_raw/best/algorithm/no_m0/roi_dataset_128x640**；2405 张图片与 2405 个同名标签 |
| **Data/TestRecords/** | 视觉延迟、有效率、座标跳变及 Task1 的实际测试 CSV |

采集 session、逐帧 metadata 与标注原文均保留，不为对齐现行标定而回写历史 geometry ID。资料集脚本可读 **source_records/capture_session.json**，不要求搬动封存文件。生效标定的几何差异与实机验证边界见 [Raspberry PROVENANCE](../../26H_Remake_Raspderry/PROVENANCE.md)。

## 工具映射

| 现行入口 | 原用途／来源 |
|---|---|
| **Vision/APP/select_roi.py**、**calibrate_geometry.py**、**capture_training_data.py** | 相机 ROI、轨道标定与训练图采集 |
| **Vision/APP/annotate_ball.py**、**build_yolo_dataset.py**、**train_yolo.py** | bbox 标注、资料集整理与 YOLO 训练 |
| **Vision/APP/rename_dataset_files.py** | 训练与标定资料的成对改名预览 |
| **Diagnostics/APP/capture_mcu_csv.py**、**capture_vision_csv.sh** | STM32 5 ms CSV 与 Pi 逐帧 probe |
| **Diagnostics/APP/analyze_vision.py**、**analyze_vision_probe.py** | 视觉链路与帧率分析 |
| **Diagnostics/APP/initialize_zero.py**、**run_task1.py**、**analyze_task1.py** | 零点初始化、Task1 记录与分析 |

可执行入口只在 **APP/**；**Core/**、**IO/**、**Config/** 是按依赖闭包收纳的实现。未纳入一次性参数遍历、旧阶跃、VOFA 监视、重复备份和其他与当前资料／5 ms 诊断链无关的脚本。正式视觉代码由 Raspberry 包单独维护。
