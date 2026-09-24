# 命令手冊

按執行平台分段；Windows Support 位於 `D:\26H-remake\26H_Remake_Support`，樹莓派正式視覺位於 `~/vision_workspace/workspace`，虛擬環境是同級 `.venv`。Pi 平時不需要 Support；只有重新製作視覺資料時才部署 `Vision/`。各字段和 5 ms 通道見 [DATA_FORMAT.md](DATA_FORMAT.md)。

## 1. 樹莓派：按需部署資料工具

在 Windows PowerShell 執行。這只上傳工具，不上傳 2405 張封存訓練圖片，也不修改正式 `workspace`：

1. ssh ikun@192.168.137.2 "mkdir -p /home/ikun/vision_workspace/26H_Remake_Support/Data/Calibration/generated /home/ikun/vision_workspace/26H_Remake_Support/Data/Training/Captures"
2. scp -r "D:\26H-remake\26H_Remake_Support\Vision" ikun@192.168.137.2:/home/ikun/vision_workspace/26H_Remake_Support/

下列相機命令在樹莓派桌面終端執行，先進入工具目錄：

1. cd ~/vision_workspace/26H_Remake_Support
2. source ~/vision_workspace/.venv/bin/activate

### 看 ROI

python3 Vision/APP/select_roi.py --camera /dev/video0 --preview Data/Calibration/roi_selection_preview.png

終端顯示 `x/y/width/height`，預覽圖寫到樹莓派 `Data/Calibration/roi_selection_preview.png`。這是選取與查看，不會改正式配置。現行來源 ROI 為 `(128,425,1141,121)`。

### 重新標定（僅在需要時）

依提示把桿調到各角度，穩定後選取軌道角點與位置點：

python3 Vision/APP/calibrate_geometry.py --camera /dev/video0 --angles 12,14,16,18,20,22,24,26,28,30 --positions=-10,-5,0,5,10 --exposure-time-absolute 10 --output-dir Data/Calibration/generated

樹莓派輸出 `Data/Calibration/generated/dynamic_calibration_manual.json`，同目錄附來源圖及展開圖。人工角度產物標記 `test_only`；這個命令**不更新**正式 JSON。現行正式標定已含 12–30°十樣本，不需要為了啟動再做此步。

把新結果取回 Windows（PowerShell）：

1. cd D:\26H-remake\26H_Remake_Support
2. scp -r ikun@192.168.137.2:/home/ikun/vision_workspace/26H_Remake_Support/Data/Calibration/generated Data/Calibration/

Windows 接收位置是 `Data\Calibration\generated\`；正式鏡像不受影響。

### 採集 12–30°訓練圖片

以 12°為例，讀取正式標定，輸出寫到樹莓派 Support 的新會話：

python3 Vision/APP/capture_training_data.py --calibration ../workspace/assets/calibration/dynamic_calibration_12_30deg.json --output-dir Data/Training/Captures --session angle_12deg_exp10 --angle-deg 12 --exposure-time-absolute 10

其餘角度改 `--session` 與 `--angle-deg` 為 14、16、…、30。每組在 Pi `Data/Training/Captures/angle_XXdeg_exp10/`，包含圖片、會話 JSON 和逐幀 metadata；不要只複製 PNG。Windows PowerShell 取回：

1. cd D:\26H-remake\26H_Remake_Support
2. scp -r ikun@192.168.137.2:/home/ikun/vision_workspace/26H_Remake_Support/Data/Training/Captures Data/Training/

Windows 接收位置是 `Data\Training\Captures\angle_XXdeg_exp10\`。人工角度只用於採集，不進入正式閉環。

## 2. Windows：標註、整理與訓練

在 PowerShell 執行：

1. cd D:\26H-remake\26H_Remake_Support
2. python Vision\APP\annotate_ball.py --dataset-root Data\Training\Captures --pattern "angle_*deg_exp10"

標註輸出寫回各會話的 `images/` 和同名 `labels/`。整理一組新會話：

python Vision\APP\build_yolo_dataset.py --source Data\Training\Captures\angle_12deg_exp10 --output-dir Data\Training\Prepared

要使用本地封存的 2405 組十角度資料，改用：

1. $angleDirs = Get-ChildItem Data\Training\steel_ball_12_30deg_exp10\by_angle -Directory -Filter 'angle_*' | Sort-Object Name
2. $sourceArgs = foreach ($dir in $angleDirs) { '--source'; $dir.FullName }
3. python Vision\APP\build_yolo_dataset.py @sourceArgs --output-dir Data\Training\Prepared

`Prepared` 必須為空／不存在；結果含 `images/train|val`、`labels/train|val`、`roi_ball.yaml` 和 `manifest.json`。整理腳本核對資料內部配對與原有 geometry ID，不會改寫封存記錄，也不能自動證明 HEF 的幾何匹配。

將基礎模型放到 `Data\Training\Models\yolo26n.pt`，再執行：

python Vision\APP\train_yolo.py --data Data\Training\Prepared\roi_ball.yaml --model Data\Training\Models\yolo26n.pt

輸出 `Data\Training\Models\best.pt`、訓練記錄及模型幾何資訊。PT→HEF 在本地虛擬機完成，本倉庫不提供轉換命令。批量改名工具只供預覽，確認配對和備份後才可加 `--apply`：

python Vision\APP\rename_dataset_files.py

## 3. 樹莓派：正式視覺

先停止其他會佔用同一相機、串口的進程；正式工作區不需要 Pi 端 Support：

1. cd ~/vision_workspace/workspace
2. source ~/vision_workspace/.venv/bin/activate
3. python3 best/run.py --port /dev/ttyUSB0 --inference-backend hailort --debug-page --serial-read-timeout-ms 1 --wifi-stream --no-display

進程讀取 `workspace/assets/calibration/dynamic_calibration_12_30deg.json`、`assets/models/hailo/best.hef` 和 `config/runtime.toml`；不讀 Support 的訓練圖。

## 4. Windows：STM32 CSV 與 Task1

下位機 USART6 調試串口的實際 COM 號先自行確認；以下 `COM26` 是示例。Windows PowerShell：

1. cd D:\26H-remake\26H_Remake_Support
2. python Diagnostics\APP\capture_mcu_csv.py --list-ports
3. python Diagnostics\APP\capture_mcu_csv.py --port COM26 --mode listen --firmware-csv vision --duration-s 10

`--mode listen` 只採集，不發 `ba 22` 或 `task 1`；`--firmware-csv vision` 令固件按 5 ms 打印視覺診斷。CSV 默認寫到 Windows `Data\TestRecords\mcu_vision_listen_<時間戳>.csv`，包含主機時間和解析後欄位。串口原始行以 `V` 開頭、後接 10 個數值；用 `stm32_time_ms` 核對 5 ms，不能用 Windows 收行間隔冒充。字段逐列見 [DATA_FORMAT.md](DATA_FORMAT.md#vision-通道的線上字段)。

Task1 前把固件 CSV 切回 `control`（13 列，每 5 ms）：

1. python Diagnostics\APP\capture_mcu_csv.py --port COM26 --mode listen --firmware-csv control --duration-s 1
2. python Diagnostics\APP\initialize_zero.py --port COM26
3. $task1Csv = "Data\TestRecords\task1_$(Get-Date -Format yyyyMMdd_HHmmss).csv"
4. python Diagnostics\APP\run_task1.py --port COM26 --output $task1Csv
5. python Diagnostics\APP\analyze_task1.py $task1Csv

`initialize_zero.py` 用於 MCU 復位或機械零點改變後；`run_task1.py` 發 `task 1`，退出時嘗試發 `task stop`。Task1 CSV 寫入 `$task1Csv`；控制字段見 [DATA_FORMAT.md](DATA_FORMAT.md#control-通道的-13-列)。

## 5. 樹莓派逐幀 probe 與聯合分析

probe 是同一正式進程的逐幀內部 CSV，不是另一套識別，也不等於每幀都向 STM32 發包。先停止一般視覺進程，再在 Pi 執行：

1. mkdir -p ~/vision_workspace/diagnostics
2. cd ~/vision_workspace/workspace
3. source ~/vision_workspace/.venv/bin/activate
4. python3 best/run.py --port /dev/ttyUSB0 --inference-backend hailort --debug-page --serial-read-timeout-ms 1 --wifi-stream --no-display --vision-probe-csv "$HOME/vision_workspace/diagnostics/vision_probe_$(date +%Y%m%d_%H%M%S).csv"

Pi 輸出 `~/vision_workspace/diagnostics/vision_probe_<時間戳>.csv`。逐幀寫盤可能增加耗時；不要把 probe 幀率當成無 probe 的正式幀率。Windows PowerShell 複製實際檔名並分析：

1. cd D:\26H-remake\26H_Remake_Support
2. scp ikun@192.168.137.2:/home/ikun/vision_workspace/diagnostics/vision_probe_實際時間戳.csv Data/TestRecords/
3. python Diagnostics\APP\analyze_vision_probe.py Data\TestRecords\vision_probe_實際時間戳.csv
4. python Diagnostics\APP\analyze_vision.py --mcu Data\TestRecords\mcu_vision_listen_實際時間戳.csv --probe Data\TestRecords\vision_probe_實際時間戳.csv

把示例時間戳換成實際輸出文件名；Pi probe 與 MCU `vision` CSV 應採自同一時段。probe、vision 和 control 各回答不同問題，字段見 [DATA_FORMAT.md](DATA_FORMAT.md)。
