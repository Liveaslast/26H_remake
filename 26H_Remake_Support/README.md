# Support｜资料制作、采集与分析

这是 Windows 工具与资料工程，不参与树莓派正式运行。按你现在要做的任务，直接进入对应小节。

| 我要做什么 | 使用入口 | 结果放哪里 |
|---|---|---|
| [重新选 ROI、标定或采训练图](#1-重新制作视觉资料) | `Vision/APP/` | `Data/Calibration/`、`Data/Training/` |
| [标注、整理数据集和训练 PT](#2-标注整理与训练) | `Vision/APP/` | `Data/Training/` |
| [运行并分析 Task1](#3-task1) | `Diagnostics/APP/` | `Data/TestRecords/` |
| [检查视觉质量或传输链路](#4-视觉诊断) | `Diagnostics/APP/` | `Data/TestRecords/` |

`APP/` 中的文件才是可执行入口；`Core/`、`IO/`、`Config/` 只是内部实现。现有离线分析入口只有 `analyze_task1.py`、`analyze_vision_probe.py` 和 `analyze_vision.py`，不要为相同输入另建脚本。

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
- CSV 列定义见 [DATA_FORMAT.md](Docs/DATA_FORMAT.md)。资料来源只在追溯时查看 [PROVENANCE.md](Docs/PROVENANCE.md)。
- 生效标定在树莓派 `assets/calibration/`；Support 的 `Data/Calibration/active/` 只是参考副本。
- 封存训练资料共 2405 张图片及同名标签；正式树莓派运行不读取这些原始资料或 PT。
