# Support｜资料制作、采集与分析

本工程不参与正式逐帧控制。命令只在下列位置维护，不再同时提供新旧两套资料制作流程。

| 工作 | 入口 |
|---|---|
| ROI、标定、采图、标注、数据集与训练 | [完整资料制作流程](Docs/CALIBRATION_V2_WORKFLOW.md) |
| Windows串口采集、任务测试和分析 | 本页 |
| CSV、probe、标签及资料字段 | [数据格式](Docs/DATA_FORMAT.md) |

`Vision/APP` 是资料工具入口，`Core` 放处理逻辑，`IO` 放相机/串口访问，`Config` 放默认配置。`Diagnostics/APP` 是分析与采集入口。工具角度客户端仍独立于正式Pi客户端，协议改动需单独核对。

新实验写独立目录；不覆盖旧数据、旧结论、正式模型或生效标定。

## 3. Task1

电脑通过USART6运行任务：先确认COM号。`run_task1.py` 已包含机械零位确认和 `task init`，不要再额外初始化一次；杆角稳定后输入 `task 1`。Ctrl+C只退出电脑端，需人工复位或急停。

```powershell
cd D:\26H-remake\26H_Remake_Support
python Diagnostics\APP\capture_mcu_csv.py --list-ports
$checkArgs = @('--port', 'COM26', '--mode', 'listen',
    '--firmware-csv', 'control', '--duration-s', '1')
python Diagnostics\APP\capture_mcu_csv.py @checkArgs

$task1Csv = "Data\TestRecords\task1_$(Get-Date -Format yyyyMMdd_HHmmss).csv"
python Diagnostics\APP\run_task1.py --port COM26 --output $task1Csv
python Diagnostics\APP\analyze_task1.py $task1Csv
```

查看波形，替换为实际CSV路径：

```matlab
addpath('D:\26H-remake\26H_Remake_Support\Diagnostics\APP')
plot_task1('D:\26H-remake\26H_Remake_Support\Data\TestRecords\control.csv')
```

可用第二个参数指定显示的前几秒。`i_inferred_deg` 是按实验配置反推的积分，不是MCU直接发送值；限幅时留空。速度是估计值，电机角不是独立测量的梁倾角。脚本按 `control_ms` 去重查看实际控制输入，旧CSV不做同步假设。

Pi串口链的启动和采集由[Pi README](../26H_Remake_Raspderry/README.md)维护；这里不复制命令。USART6命令查询[MCU README](../26H_Remake_DJC/README.md#usart6-调试口)。

离线比较相邻帧差分与3/5帧速度拟合：

```powershell
$probe = 'Data\TestRecords\task1_fw_20261006_01\vision_probe.csv'
$fitArgs = @($probe, '--control-period-ms', '20',
    '--velocity-fit-compare', '--velocity-fit-end-s', '2')
python Diagnostics\APP\analyze_vision_probe.py @fitArgs
```

这只比较内部预测一致性，不是真实速度标定，也不会修改线上控制。

## 4. 视觉诊断

先确认任务已停、机械零点正确、角度在生效标定范围；采集脚本不发送初始化或角度命令。Windows上传诊断工具：

```powershell
cd D:\26H-remake\26H_Remake_Support
$pi = 'ikun@192.168.137.2'
$tools = '/home/ikun/vision_workspace/26H_Remake_Support'
ssh $pi "mkdir -p $tools"
scp -r .\Diagnostics "${pi}:$tools/"
```

Pi终端运行，按提示完成静态和自然运动采集：

```bash
cd ~/vision_workspace/26H_Remake_Support
LIGHTING_LABEL=dark \
EXPOSURE_VALUES="80" \
STATIC_DURATION=15 \
MOTION_DURATION=15 \
bash Diagnostics/APP/capture_vision_quality.sh
```

`EXPOSURE_VALUES` 单位100μs，80表示8ms。`DETECTION_INTERVAL=1` 每帧检测，设2才在间隔帧采用光流；默认HailoRT，可设 `INFERENCE_BACKEND=ncnn` 对照。控件核验失败会停止，模型几何警告不能忽略后直接进入闭环。

完整取回结果目录再分析：

```powershell
cd D:\26H-remake\26H_Remake_Support
$run = "vision_quality_dark_ncnn_实际时间"
$remote = "/home/ikun/vision_workspace/diagnostics/$run"
scp -r "ikun@192.168.137.2:$remote" .\Data\TestRecords\
foreach ($exp in 80) {
    $dir = Join-Path (Join-Path 'Data\TestRecords' $run) "exp$exp"
    $static = Join-Path $dir 'static_probe.csv'
    $motion = Join-Path $dir 'motion_probe.csv'
    python Diagnostics\APP\analyze_vision_probe.py $static --control-period-ms 20
    python Diagnostics\APP\analyze_vision_probe.py $motion --control-period-ms 20
}
```

比较时同时看球速分布；`--control-period-ms 20` 仅用于标记更新空窗，不代表启动了Task1。

联合分析识别、串口传输和MCU估计，需要同时段的Pi probe与MCU vision CSV：

```powershell
$listenArgs = @('--port', 'COM26', '--mode', 'listen',
    '--firmware-csv', 'vision', '--duration-s', '10')
python Diagnostics\APP\capture_mcu_csv.py @listenArgs

$compareArgs = @(
    '--mcu', 'Data\TestRecords\mcu_vision_实际文件.csv',
    '--probe', 'Data\TestRecords\vision_probe_实际文件.csv'
)
python Diagnostics\APP\analyze_vision.py @compareArgs
```

`--mode` 决定采集器是否发送任务命令，`--firmware-csv` 决定固件打印类型。原始数据留在 `Data/TestRecords`，不要覆盖已有实验。

## 资料来源

- 生效模型和标定属于Pi工程；Support的 `Data/Calibration/active` 只是参考副本，不自动回写。
- 封存训练集 `Data/Training/steel_ball_12_30deg_exp10` 有2405组图片/标签及原始来源记录。
- `Data/Training/Models/best.pt` 来自历史训练，没有geometry sidecar，不能补写不实ID。当前几何与模型部署限制只在[Pi模型说明](../26H_Remake_Raspderry/README.md#模型与标定边界)维护。
- 历史实验保留当时条件及结论，不作为现行接口说明。
