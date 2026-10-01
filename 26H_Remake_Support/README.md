# Support｜资料制作、采集与分析

| 步骤 | 使用入口 | 结果存放路径 |
|---|---|---|
| [重新选 ROI、标定或采训练图](#1-重新制作视觉资料) | `Vision/APP/` | `Data/Calibration/`、`Data/Training/` |
| [标注、整理数据集和训练 PT](#2-标注整理与训练) | `Vision/APP/` | `Data/Training/` |
| [运行并分析 Task1](#3-task1) | `Diagnostics/APP/` | `Data/TestRecords/` |
| [检查视觉质量或传输链路](#4-视觉诊断) | `Diagnostics/APP/` | `Data/TestRecords/` |



## 工具脚本总表

### 视觉资料工具

| 脚本 | 平台 | 用途 | 输入 → 输出 |
|---|---|---|---|
| `Vision/APP/select_roi.py` | 树莓派桌面 | 在相机画面中交互选择固定 ROI | USB 相机 → ROI 数值、预览图；不修改正式配置 |
| `Vision/APP/calibrate_geometry.py` | 树莓派桌面 | 人工设定杆角度，点击轨道和位置点完成动态几何标定 | 相机、角度和点位 → 标定 JSON、来源图、展开检查图 |
| `Vision/APP/capture_training_data.py` | 树莓派 | 按指定角度和曝光采集动态展开后的训练图 | 正式标定、相机、人工角度 → 640×128 图片、会话 JSON、逐帧 metadata |
| `Vision/APP/annotate_ball.py` | Windows 或树莓派桌面 | 在图片上框选钢球 | 未标注图片 → 同名 YOLO bbox 标签 |
| `Vision/APP/build_yolo_dataset.py` | Windows | 检查图片/标签/geometry ID，并划分训练集和验证集 | 一个或多个采集会话 → `images/`、`labels/`、`roi_ball.yaml`、manifest |
| `Vision/APP/train_yolo.py` | Windows | 训练单类别钢球 YOLO 模型 | `roi_ball.yaml`、基础 PT → `best.pt`、训练记录、几何信息 |
| `Vision/APP/rename_dataset_files.py` | Windows | 成对检查和改名训练/标定资料 | 现有资料 → 改名预览；只有 `--apply` 才实际修改 |

### 采集与分析工具

| 脚本 | 平台 | 用途 | 输入 → 输出 |
|---|---|---|---|
| `Diagnostics/APP/capture_mcu_csv.py` | Windows | 读取 USART6 的 `control` 或 `vision` 调试流并附主机时间 | STM32 串口 → `Data/TestRecords/` CSV |
| `Diagnostics/APP/initialize_zero.py` | Windows | MCU 复位、烧录或机械零点改变后发送一次 `task init` | 操作者确认机械零点 → 下位机零点和 22°平衡角 |
| `Diagnostics/APP/run_task1.py` | Windows | 启动 `0 → +5 → -5 cm` Task1 并记录控制数据 | STM32 串口、可选临时参数 → Task1 control CSV |
| `Diagnostics/APP/analyze_task1.py` | Windows | 分析 Task1 的穿越、超调、制动、角度跟随和阶段完成情况 | Task1 control CSV → 终端分析报告 |
| `Diagnostics/APP/capture_vision_csv.sh` | 树莓派 | 用正式 `best/run.py` 开启一次逐帧 probe | 正式视觉进程 → 单份 `vision_probe_*.csv` |
| `Diagnostics/APP/capture_vision_quality.sh` | 树莓派 | 依次采集静止和自然运动 probe，可用环境变量覆盖曝光与时长 | 曝光值、静止/运动时长 → 两份 probe、相机控件和运行日志 |
| `Diagnostics/APP/capture_motion_quality.sh` | 树莓派 | 只复测自然运动，适合比较照明或曝光 | 曝光值、运动时长 → `motion_probe.csv` 和运行日志 |
| `Diagnostics/APP/analyze_vision_probe.py` | Windows | 分析单份 probe 的帧率、耗时、有效率、空窗、抖动和坐标事件 | Pi probe CSV → 终端质量报告 |
| `Diagnostics/APP/analyze_vision.py` | Windows | 联合检查 Pi 识别、串口传输和 STM32 估计 | 同时段 Pi probe + MCU vision CSV → 对齐分析报告 |

`EXPOSURE_TIME_ABSOLUTE` 的单位已核实为 100 μs：数值 10 是 1 ms，20 是 2 ms。`__init__.py` 只是 Python 包标记，不是工具脚本。

### 内部实现，不直接运行

| 位置 | 作用 |
|---|---|
| `Vision/Config/` | `vision_tools.toml` 默认值、配置校验和统一路径 |
| `Vision/Core/` | 标定 UI/流程、几何换算、采集与数据集实现 |
| `Vision/IO/` | 相机/角度遥测和人工角度输入 |
| `Diagnostics/Core/` | 串口采集与 Task1 记录实现 |
| `Diagnostics/IO/` | 串口链路检查实现 |

## 1. 重新制作视觉资料

平时正式运行不需要 Support。只有重做资料时，先在 Windows PowerShell 上传工具：

```powershell
cd D:\26H-remake\26H_Remake_Support
ssh ikun@192.168.137.2 "mkdir -p /home/ikun/vision_workspace/26H_Remake_Support/Data/Calibration/generated /home/ikun/vision_workspace/26H_Remake_Support/Data/Training/Captures"
scp -r .\Vision ikun@192.168.137.2:/home/ikun/vision_workspace/26H_Remake_Support/
```

然后在树莓派桌面终端执行：

```bash
cd ~/vision_workspace/26H_Remake_Support
source ~/vision_workspace/.venv/bin/activate

# 只看 ROI，不修改正式配置
python3 Vision/APP/select_roi.py --camera /dev/video0 --preview Data/Calibration/roi_selection_preview.png

# 重新标定；结果先进入 generated，不自动替换正式 JSON
python3 Vision/APP/calibrate_geometry.py --camera /dev/video0 --angles 12,14,16,18,20,22,24,26,28,30 --positions=-10,-5,0,5,10 --exposure-time-absolute 10 --output-dir Data/Calibration/generated

# 采集一个角度；其余角度修改 session 和 angle-deg
python3 Vision/APP/capture_training_data.py --calibration ../workspace/assets/calibration/dynamic_calibration_12_30deg.json --output-dir Data/Training/Captures --session angle_12deg_exp10 --angle-deg 12 --exposure-time-absolute 10
```

现行 ROI 是 `(128,425,1141,121)`；正式标定含 12、14、…、30°十个样本。人工角度只用于标定和采图，不进入正式闭环。取回资料时复制完整会话目录，不要只复制 PNG。

## 2. 标注、整理与训练

在 Windows PowerShell 执行：

```powershell
cd D:\26H-remake\26H_Remake_Support

# 标注新采集会话
python Vision\APP\annotate_ball.py --dataset-root Data\Training\Captures --pattern "angle_*deg_exp10"

# 将封存的十角度资料整理为 train/val
$angleDirs = Get-ChildItem Data\Training\steel_ball_12_30deg_exp10\by_angle -Directory -Filter 'angle_*' | Sort-Object Name
$sourceArgs = foreach ($dir in $angleDirs) { '--source'; $dir.FullName }
python Vision\APP\build_yolo_dataset.py @sourceArgs --output-dir Data\Training\Prepared

# 训练；基础模型预先放到 Models/yolo26n.pt
python Vision\APP\train_yolo.py --data Data\Training\Prepared\roi_ball.yaml --model Data\Training\Models\yolo26n.pt
```

PT 保存在 `Data/Training/Models/`。转换后的 HEF 经核对后放到树莓派工程的 `assets/models/hailo/`；本仓库不提供 PT→HEF 命令。`rename_dataset_files.py` 只有加 `--apply` 才会修改文件。

## 3. Task1

先确认 USART6 的实际 COM 号。MCU 复位、重新烧录或机械零点改变后才需要再次初始化：

```powershell
cd D:\26H-remake\26H_Remake_Support
python Diagnostics\APP\capture_mcu_csv.py --list-ports
python Diagnostics\APP\capture_mcu_csv.py --port COM26 --mode listen --firmware-csv control --duration-s 1
python Diagnostics\APP\initialize_zero.py --port COM26

$task1Csv = "Data\TestRecords\task1_$(Get-Date -Format yyyyMMdd_HHmmss).csv"
python Diagnostics\APP\run_task1.py --port COM26 --output $task1Csv
python Diagnostics\APP\analyze_task1.py $task1Csv
```

`run_task1.py` 发送 `task 1`，退出时尝试发送 `task stop`。串口 BBP/BPUSH 覆盖只对当次运行有效，不会写回固件默认 profile。2026-09-27 的具体调参案例保存在 `Data/TestRecords/TASK1_TUNING_20260927.md`，不是日常前置阅读。

## 4. 视觉诊断

单独检查 Pi 每帧视觉时，先部署并运行质量采集脚本：

```powershell
cd D:\26H-remake\26H_Remake_Support
scp .\Diagnostics\APP\capture_vision_quality.sh ikun@192.168.137.2:/home/ikun/vision_workspace/capture_vision_quality.sh
```

```bash
EXPOSURE_TIME_ABSOLUTE=20 STATIC_DURATION=10 MOTION_DURATION=20 bash /home/ikun/vision_workspace/capture_vision_quality.sh
```

结果先保存在 Pi 的 `~/vision_workspace/diagnostics/`。完整取回到 `Data/TestRecords/` 后分析：

```powershell
python Diagnostics\APP\analyze_vision_probe.py Data\TestRecords\实际目录\static_probe.csv
python Diagnostics\APP\analyze_vision_probe.py Data\TestRecords\实际目录\motion_probe.csv
```

要区分识别、传输和 STM32 估计问题，需在同一时段采集 Pi probe 和 MCU `vision` CSV：

```powershell
python Diagnostics\APP\capture_mcu_csv.py --port COM26 --mode listen --firmware-csv vision --duration-s 10
python Diagnostics\APP\analyze_vision.py --mcu Data\TestRecords\mcu_vision_实际文件.csv --probe Data\TestRecords\vision_probe_实际文件.csv
```

probe 是 Pi 每处理一帧的内部记录；`vision` CSV 是 STM32 每 5 ms 的接收和估计状态；`control` CSV 是控制过程。三者不能互相代替。`capture_mcu_csv.py --mode` 控制是否发送任务命令，`--firmware-csv` 控制固件打印内容。

## 文件规则与参考

- 原始测试记录和单次结论放 `Data/TestRecords/`，不要放进代码目录。
- 新分析能力优先扩展现有三个入口；复用算法放 `Diagnostics/Core/`，I/O 放 `Diagnostics/IO/`。
- CSV、YOLO 标签和 probe 的字段定义见 [DATA_FORMAT.md](Docs/DATA_FORMAT.md)。
- 生效标定在树莓派 `assets/calibration/`；Support 的 `Data/Calibration/active/` 只是参考副本。
- 封存训练资料共 2405 张图片及同名标签；正式树莓派运行不读取这些原始资料或 PT。

## 资料、模型与来源

| 位置 | 内容和来源 | 使用边界 |
|---|---|---|
| `Data/Calibration/active/dynamic_calibration_12_30deg.json` | 与树莓派生效 JSON 内容相同的参考副本 | 不能从 Support 自动覆盖正式配置 |
| `Data/Calibration/angle_12_30deg/` | 树莓派标定输出的十张来源图和十张展开图 | 用于追溯标定，不参与运行 |
| `Data/Training/steel_ball_12_30deg_exp10/` | 最初整理自本机历史快照 `_pi_raw/.../roi_dataset_128x640`；现已自带 2405 张图片、2405 个标签和来源记录 | 正式 Pi 只读取 HEF，不读取图片和标签 |
| `Data/Training/Models/best.pt` | Windows 训练所得 PT，复制来源为 `D:\Linux_system\VM_share\best.pt` | 交给本地虚拟机转 HEF；不放入树莓派正式工作区 |
| `Data/TestRecords/` | 视觉延迟、有效率、坐标事件和 Task1 的实测 CSV 与结论 | 新测试继续放这里，不写进代码目录 |

训练资料按 `by_angle/angle_*` 分为 12、14、…、30°十组，图片为 640×128 PNG，标签为同名 YOLO bbox TXT，原始 `source_records/` 不回写。采集 session 和 metadata 保留历史 geometry ID；内部一致不代表模型与现行标定自动匹配。

现有旧 `best.pt` 没有 `best.pt.geometry.json`，不要为消除警告而补写不实 ID。转换后的正式模型位于 `26H_Remake_Raspderry/assets/models/hailo/best.hef`；几何差异和实机验证边界见 [Raspberry README](../26H_Remake_Raspderry/README.md#标定与验证边界)。
