# 命令手册

按执行平台分段；Windows Support 位于 **D:\26H-remake\26H_Remake_Support**，树莓派正式视觉位于 **~/vision_workspace/workspace**，虚拟环境是同级 **.venv**。Pi 平时不需要 Support；只有重新制作视觉资料时才部署 **Vision/**。各字段和 5 ms 通道见 [DATA_FORMAT.md](DATA_FORMAT.md)。

## 1. 树莓派：按需部署资料工具

在 Windows PowerShell 执行。这只上传工具，不上传 2405 张封存训练图片，也不修改正式 **workspace**：

1. ssh ikun@192.168.137.2 "mkdir -p /home/ikun/vision_workspace/26H_Remake_Support/Data/Calibration/generated /home/ikun/vision_workspace/26H_Remake_Support/Data/Training/Captures"
2. scp -r "D:\26H-remake\26H_Remake_Support\Vision" ikun@192.168.137.2:/home/ikun/vision_workspace/26H_Remake_Support/

下列相机命令在树莓派桌面终端执行，先进入工具目录：

1. cd ~/vision_workspace/26H_Remake_Support
2. source ~/vision_workspace/.venv/bin/activate

### 看 ROI

python3 Vision/APP/select_roi.py --camera /dev/video0 --preview Data/Calibration/roi_selection_preview.png

终端显示 **x/y/width/height**，预览图写到树莓派 **Data/Calibration/roi_selection_preview.png**。这是选取与查看，不会改正式配置。现行来源 ROI 为 **(128,425,1141,121)**。

### 重新标定（仅在需要时）

依提示把杆调到各角度，稳定后选取轨道角点与位置点：

python3 Vision/APP/calibrate_geometry.py --camera /dev/video0 --angles 12,14,16,18,20,22,24,26,28,30 --positions=-10,-5,0,5,10 --exposure-time-absolute 10 --output-dir Data/Calibration/generated

树莓派输出 **Data/Calibration/generated/dynamic_calibration_manual.json**，同目录附来源图及展开图。人工角度产物标记 **test_only**；这个命令**不更新**正式 JSON。现行正式标定已含 12–30°十样本，不需要为了启动再做此步。

把新结果取回 Windows（PowerShell）：

1. cd D:\26H-remake\26H_Remake_Support
2. scp -r ikun@192.168.137.2:/home/ikun/vision_workspace/26H_Remake_Support/Data/Calibration/generated Data/Calibration/

Windows 接收位置是 **Data\Calibration\generated\**；正式镜像不受影响。

### 采集 12–30°训练图片

以 12°为例，读取正式标定，输出写到树莓派 Support 的新会话：

python3 Vision/APP/capture_training_data.py --calibration ../workspace/assets/calibration/dynamic_calibration_12_30deg.json --output-dir Data/Training/Captures --session angle_12deg_exp10 --angle-deg 12 --exposure-time-absolute 10

其余角度改 **--session** 与 **--angle-deg** 为 14、16、…、30。每组在 Pi **Data/Training/Captures/angle_XXdeg_exp10/**，包含图片、会话 JSON 和逐帧 metadata；不要只复制 PNG。Windows PowerShell 取回：

1. cd D:\26H-remake\26H_Remake_Support
2. scp -r ikun@192.168.137.2:/home/ikun/vision_workspace/26H_Remake_Support/Data/Training/Captures Data/Training/

Windows 接收位置是 **Data\Training\Captures\angle_XXdeg_exp10\**。人工角度只用于采集，不进入正式闭环。

## 2. Windows：标注、整理与训练

在 PowerShell 执行：

1. cd D:\26H-remake\26H_Remake_Support
2. python Vision\APP\annotate_ball.py --dataset-root Data\Training\Captures --pattern "angle_*deg_exp10"

标注输出写回各会话的 **images/** 和同名 **labels/**。整理一组新会话：

python Vision\APP\build_yolo_dataset.py --source Data\Training\Captures\angle_12deg_exp10 --output-dir Data\Training\Prepared

要使用本地封存的 2405 组十角度资料，改用：

1. $angleDirs = Get-ChildItem Data\Training\steel_ball_12_30deg_exp10\by_angle -Directory -Filter 'angle_*' | Sort-Object Name
2. $sourceArgs = foreach ($dir in $angleDirs) { '--source'; $dir.FullName }
3. python Vision\APP\build_yolo_dataset.py @sourceArgs --output-dir Data\Training\Prepared

**Prepared** 必须为空／不存在；结果含 **images/train\|val**、**labels/train\|val**、**roi_ball.yaml** 和 **manifest.json**。整理脚本核对资料内部配对与原有 geometry ID，不会改写封存记录，也不能自动证明 HEF 的几何匹配。

将基础模型放到 **Data\Training\Models\yolo26n.pt**，再执行：

python Vision\APP\train_yolo.py --data Data\Training\Prepared\roi_ball.yaml --model Data\Training\Models\yolo26n.pt

输出 **Data\Training\Models\best.pt**、训练记录及模型几何资讯。PT 保存在 Windows Support；需要转换时将它交给本地虚拟机，转换所得 HEF 经核对后才放入树莓派运行包 **assets/models/hailo/**。本仓库不提供 PT→HEF 转换命令，NCNN 不是正式 Hailo 运行的必要产物。批量改名工具只供预览，确认配对和备份后才可加 **--apply**：

python Vision\APP\rename_dataset_files.py

## 3. 树莓派：正式视觉

先停止其他会占用同一相机、串口的进程；正式工作区不需要 Pi 端 Support：

1. cd ~/vision_workspace/workspace
2. source ~/vision_workspace/.venv/bin/activate
3. python3 best/run.py --port /dev/ttyUSB0 --inference-backend hailort --debug-page --serial-read-timeout-ms 1 --wifi-stream --no-display

进程读取 **workspace/assets/calibration/dynamic_calibration_12_30deg.json**、**assets/models/hailo/best.hef** 和 **config/runtime.toml**；不读 Support 的训练图。

## 4. Windows：STM32 CSV 与 Task1

下位机 USART6 调试串口的实际 COM 号先自行确认；以下 **COM26** 是示例。Windows PowerShell：

1. cd D:\26H-remake\26H_Remake_Support
2. python Diagnostics\APP\capture_mcu_csv.py --list-ports
3. python Diagnostics\APP\capture_mcu_csv.py --port COM26 --mode listen --firmware-csv vision --duration-s 10

**--mode listen** 只采集，不发 **ba 22** 或 **task 1**；**--firmware-csv vision** 令固件按 5 ms 打印视觉诊断。CSV 默认写到 Windows **Data\TestRecords\mcu_vision_listen_&lt;时间戳&gt;.csv**，包含主机时间和解析后栏位。串口原始行以 **V** 开头、后接 10 个数值；用 **stm32_time_ms** 核对 5 ms，不能用 Windows 收行间隔冒充。字段逐列见 [DATA_FORMAT.md](DATA_FORMAT.md#vision-通道的线上字段)。

Task1 前把固件 CSV 切回 **control**（13 列，每 5 ms）：

1. python Diagnostics\APP\capture_mcu_csv.py --port COM26 --mode listen --firmware-csv control --duration-s 1
2. python Diagnostics\APP\initialize_zero.py --port COM26
3. $task1Csv = "Data\TestRecords\task1_$(Get-Date -Format yyyyMMdd_HHmmss).csv"
4. python Diagnostics\APP\run_task1.py --port COM26 --output $task1Csv
5. python Diagnostics\APP\analyze_task1.py $task1Csv

**initialize_zero.py** 用于 MCU 复位或机械零点改变后；**run_task1.py** 发 **task 1**，退出时尝试发 **task stop**。Task1 CSV 写入 **$task1Csv**；控制字段见 [DATA_FORMAT.md](DATA_FORMAT.md#control-通道的-13-列)。

## 5. 树莓派逐帧 probe 与联合分析

probe 是同一正式进程的逐帧内部 CSV，不是另一套识别，也不等于每帧都向 STM32 发包。先停止一般视觉进程，再在 Pi 执行：

1. mkdir -p ~/vision_workspace/diagnostics
2. cd ~/vision_workspace/workspace
3. source ~/vision_workspace/.venv/bin/activate
4. python3 best/run.py --port /dev/ttyUSB0 --inference-backend hailort --debug-page --serial-read-timeout-ms 1 --wifi-stream --no-display --vision-probe-csv "$HOME/vision_workspace/diagnostics/vision_probe_$(date +%Y%m%d_%H%M%S).csv"

Pi 输出 **~/vision_workspace/diagnostics/vision_probe_&lt;时间戳&gt;.csv**。逐帧写盘可能增加耗时；不要把 probe 帧率当成无 probe 的正式帧率。Windows PowerShell 复制实际档名并分析：

1. cd D:\26H-remake\26H_Remake_Support
2. scp ikun@192.168.137.2:/home/ikun/vision_workspace/diagnostics/vision_probe_實際時間戳.csv Data/TestRecords/
3. python Diagnostics\APP\analyze_vision_probe.py Data\TestRecords\vision_probe_實際時間戳.csv
4. python Diagnostics\APP\analyze_vision.py --mcu Data\TestRecords\mcu_vision_listen_實際時間戳.csv --probe Data\TestRecords\vision_probe_實際時間戳.csv

把示例时间戳换成实际输出文件名；Pi probe 与 MCU **vision** CSV 应采自同一时段。probe、vision 和 control 各回答不同问题，字段见 [DATA_FORMAT.md](DATA_FORMAT.md)。
