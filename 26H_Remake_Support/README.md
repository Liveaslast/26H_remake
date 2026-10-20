# Support｜资料制作、采集与分析

> 当前通信使用任务/调参两模式，帧格式已变更。Vision/IO/camera_telemetry.py 已适配：先确认任务模式再读取角度，不发送运动任务。正式程序、MCU 和此工具必须配套更新；旧历史 CSV 不修改。当前协议以 [通信说明](../26H_Remake_Raspderry/ballbeam/communication/README.md) 为准。

这是 Windows 工具与资料工程，不参与树莓派正式运行。按你现在要做的任务，直接进入对应小节。

| 我要做什么 | 使用入口 | 结果放哪里 |
>>>>>>> 21fd4e5 (Update Communication jiagou between pi & mcu)
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
| `Diagnostics/APP/initialize_zero.py` | Windows | 操作者确认机械零点后发送一次 `task init`；通常在 MCU 复位、烧录或零点改变后使用 | 下位机重设零点并设当前 profile 的 21°平衡角（地面测试值） |
| `Diagnostics/APP/run_task1.py` | Windows | 启动 `0 → +5 → -5 cm` Task1 并记录控制数据 | STM32 串口 → Task1 control CSV |
| `Diagnostics/APP/analyze_task1.py` | Windows | 分析 Task1 的穿越、超调、制动、角度跟随和阶段完成情况 | Task1 control CSV → 终端分析报告 |
| `Diagnostics/APP/plot_task1.m` | Windows MATLAB | 同一时间轴查看 Task1 波形；新 CSV 显示目标速度、速度误差、P/I 角度和积分权重，以及外环实际采样的离散 `x/v` | Task1 control CSV → MATLAB 图窗；不修改 CSV |
| `Diagnostics/APP/capture_vision_csv.sh` | 树莓派 | 用正式 `best/run.py` 开启一次逐帧 probe | 正式视觉进程 → 单份 `vision_probe_*.csv` |
| `Diagnostics/APP/capture_vision_quality.sh` | 树莓派 | 按多个曝光值依次采集静止和自然运动 probe，每阶段有提示和相机控件核验 | 曝光值、静止/运动时长 → 各组 probe、相机控件和运行日志 |
| `Diagnostics/APP/capture_motion_quality.sh` | 树莓派 | 只复测自然运动，适合比较照明或曝光 | 曝光值、运动时长 → `motion_probe.csv` 和运行日志 |
| `Diagnostics/APP/analyze_vision_probe.py` | Windows | 分析单份 probe 的时序和坐标质量；可选逐帧差分与多点斜率对比 | Pi probe CSV → 终端质量报告 |
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

固定球速短行程测试复用 Pi 正式入口的 `--task-console --task1-csv --vision-probe-csv`，并加 `--velocity-test +2`、`-2`、`+5` 或 `-5`。该测试保持恒定球速目标，不加入制动阶段；到达行程边界或触发安全条件后结束。记录仍由 `analyze_task1.py` 处理，`target_v` 为 MCU 外环实际速度指令。需要 Pi 和 MCU 的 40 字节 0x85 诊断协议配套更新；详细边界见 [Pi README](../26H_Remake_Raspderry/README.md)。

电脑通过 USART6 运行 Task1 时，先确认实际 COM 号。`run_task1.py` 自己会在每次运行开头发送 `task init`，这里不要再额外运行一次 `initialize_zero.py`：

```powershell
cd D:\26H-remake\26H_Remake_Support
python Diagnostics\APP\capture_mcu_csv.py --list-ports
python Diagnostics\APP\capture_mcu_csv.py --port COM26 --mode listen --firmware-csv control --duration-s 1

$task1Csv = "Data\TestRecords\task1_$(Get-Date -Format yyyyMMdd_HHmmss).csv"
python Diagnostics\APP\run_task1.py --port COM26 --output $task1Csv
python Diagnostics\APP\analyze_task1.py $task1Csv
```

需要看波形时，在 MATLAB 中运行 `addpath('D:\26H-remake\26H_Remake_Support\Diagnostics\APP')`，再运行 `plot_task1('D:\26H-remake\26H_Remake_Support\Data\TestRecords\task1_pv_20260923_050921\control.csv')`；第二个参数可选，指定显示的前几秒。脚本只调用 MATLAB 自带的 `readtable` 和 `stackedplot`，不需要额外工具箱。新 CSV 的 `i_inferred_deg` 是按当前 Task1 profile 从角度命令反推的积分贡献，**不是下位机直接发送的积分字段**；角度限幅时会留空，旧参数试验的复算参数需与当时固件核对。图中的速度是下位机**估计值**，电机角是编码器读数，不是梁实际倾角。

旧 CSV 每 5 ms 由通信任务采样一次，外环约每 20 ms 在电机任务中计算，两者未同步；每隔四行抽点只是近似。配套更新固件和 Pi 后，新 CSV 另有 `control_ms/control_x/control_v`，记录外环实际计算时的时间和输入位置、速度；MATLAB 脚本会自动另开窗口显示这些去重后的离散点，旧 CSV 仍只显示原波形。

`run_task1.py` 先要求操作者确认机械零位，再发送 `task init`（设零点并命令当前 profile 的 21°）；待杆角稳定后输入 `task 1` 启动任务。固件使用位置—速度双环；下位机 USART6 的现行调参命令见 [下位机 README](../26H_Remake_DJC/README.md)。旧 BBP/BPUSH 文本调参入口和 `capture_task1.py` 对应可选覆盖参数已删除，历史数据及调参记录仍保留。Ctrl+C 只退出电脑端，操作者手动复位下位机。

另一种触发方式是配套更新树莓派与下位机后，在 Pi 正式视觉入口加 `--task-console`：先确认机械零位并执行 `task init`，再输入 `task 1` 启动视觉和任务。Ctrl+C 只退出树莓派进程，随后由操作者手动复位下位机。握手细节见 [Pi README](../26H_Remake_Raspderry/README.md) 和 [STM32 README](../26H_Remake_DJC/README.md)。默认仍不生成 CSV；需要 Task1 控制 CSV 时再加 `--task1-csv`，Pi 通过原视觉串口采集下位机诊断帧，生成与本节 **同一个** `analyze_task1.py` 兼容的文件，无需电脑 USART6 USB-TTL。Task1 CSV 默认采集 5 秒；若同时开启视觉 probe，它也在 5 秒后停录，但程序仍运行直到 Ctrl+C。需要看完整任务序列时，可显式加 `--task1-capture-s 8` 或更长。2026-10-06 首次采集已得到有效 CSV，显示任务未进入 −5 cm 阶段。纯视觉质量 CSV 使用已有独立采集脚本，且不会自动重设零点。

离线比较相邻帧差分与 3/5 帧最小二乘速度，沿用 `analyze_vision_probe.py`：`python Diagnostics\APP\analyze_vision_probe.py Data\TestRecords\task1_fw_20261006_01\vision_probe.csv --control-period-ms 20 --velocity-fit-compare --velocity-fit-end-s 2`。比较使用逐帧 `sent_x_cm` 和实际图像时间戳；下一帧预测误差只是内部一致性指标，不是高速运动的绝对真值。固件已有最小二乘速度函数，但当前未调用；此命令不会改变线上控制速度。

## 4. 视觉诊断

`capture_vision_quality.sh` 默认 `DETECTION_INTERVAL=1`，每帧 YOLO。要在相同静态／动态流程比较现有 YOLO+OpenCV 光流，设 `DETECTION_INTERVAL=2`；它会在两次 YOLO 之间跟踪一帧，并在结果目录名与 `session.txt` 中记录 `_flow2`／实际间隔。先比较视觉质量，再决定是否用于 Task1；这不是另一套新视觉程序。

单独检查 Pi 每帧视觉前，先自行在本地完成机械零点初始化，确认控制任务已停止、杆角在 12–30°标定范围内。当前地面测试固件的 `task init` 已包含设 21°，无需再发 `ba 21`；桌面曾在 22°附近平衡，不能把地面的 21°直接沿用到桌面。采集脚本本身不会发送初始化或角度指令，也不会在不同曝光或静动态阶段之间重新初始化。

在 Windows PowerShell 上传采集脚本：

```powershell
cd D:\26H-remake\26H_Remake_Support
scp .\Diagnostics\APP\capture_vision_quality.sh ikun@192.168.137.2:/home/ikun/vision_workspace/capture_vision_quality.sh
```

然后在树莓派终端运行；静态和动态阶段各 15 秒，每阶段会提示何时按 Enter。实验中保持暗场照明和测试动作尽量一致：

```bash
LIGHTING_LABEL=dark EXPOSURE_VALUES="80" STATIC_DURATION=15 MOTION_DURATION=15 bash /home/ikun/vision_workspace/capture_vision_quality.sh
```

`EXPOSURE_VALUES` 用空格分隔，单位 100 μs；`80` 是 8 ms。默认后端为 HailoRT；若要比较旧 NCNN 原生后端，在同一命令前加 `INFERENCE_BACKEND=ncnn`。脚本对两者统一使用每帧 YOLO、bbox 中心并关闭圆拟合，不开启 OpenCV 中间帧跟踪；NCNN 的历史模型几何差异会明确警告，必须先确认坐标合理，不能仅凭脚本成功就进入闭环 Task1。结果目录形如 `~/vision_workspace/diagnostics/vision_quality_dark_hailort_时间/exp80/` 或 `vision_quality_dark_ncnn_时间/exp80/`，包含 probe、日志、会话信息和静态/动态各自的相机控件核验记录；控件不符会停止采集。脚本结束会打印实际结果目录。

在 Windows PowerShell 中取回**整个结果目录**，将下面的时间换为刚才打印的实际值，再用同一个分析入口处理每组：

```powershell
cd D:\26H-remake\26H_Remake_Support
$run = "vision_quality_dark_ncnn_实际时间"
scp -r "ikun@192.168.137.2:/home/ikun/vision_workspace/diagnostics/$run" .\Data\TestRecords\
foreach ($exp in 80) {
    $dir = Join-Path (Join-Path 'Data\TestRecords' $run) "exp$exp"
    python Diagnostics\APP\analyze_vision_probe.py (Join-Path $dir 'static_probe.csv') --control-period-ms 20 | Tee-Object -FilePath (Join-Path $dir 'static_analysis.txt')
    python Diagnostics\APP\analyze_vision_probe.py (Join-Path $dir 'motion_probe.csv') --control-period-ms 20 | Tee-Object -FilePath (Join-Path $dir 'motion_analysis.txt')
}
```

这组 probe 只评价视觉本身；人工推动的动态动作很难完全相同，比较时要同时看球速分布，不能只按有效率排序。`--control-period-ms 20` 用 Task1 当前外环周期标记视觉更新空窗，不代表此次测试启用了 Task1。

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
