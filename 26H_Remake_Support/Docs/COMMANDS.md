# 視覺資料製作與測試命令

先分清兩個位置：Windows 的 `D:\26H-remake\26H_Remake_Support` 完整保存資料與工具；樹莓派正式視覺在 `~/vision_workspace/workspace`，Python 環境位於同級 `.venv`，HailoRT 等系統設備／驅動仍須正常可用。清理後 Pi 不預設有 Support 目錄；只有重新選 ROI、標定或採圖時，才把 `Vision/` 部署到 `~/vision_workspace/26H_Remake_Support`。以下資料工具不會自動改動正式視覺配置。

如需在樹莓派製作新視覺資料，先在 Windows PowerShell 執行；不拍新資料時跳過整段：

```powershell
ssh ikun@192.168.137.2 "mkdir -p /home/ikun/vision_workspace/26H_Remake_Support/Data/Calibration/generated /home/ikun/vision_workspace/26H_Remake_Support/Data/Training/Captures"
scp -r "D:\26H-remake\26H_Remake_Support\Vision" ikun@192.168.137.2:/home/ikun/vision_workspace/26H_Remake_Support/
```

樹莓派只獲得工具與空輸出目錄；不必把 Windows 封存的 2405 張訓練圖重新傳上去。

## 1. 樹莓派：確認相機 ROI

在樹莓派桌面終端執行（需要 USB 相機）：

```bash
cd ~/vision_workspace/26H_Remake_Support
source ~/vision_workspace/.venv/bin/activate
```

```bash
python3 Vision/APP/select_roi.py \
  --camera /dev/video0 \
  --preview Data/Calibration/roi_selection_preview.png
```

結果：終端打印 ROI 的 `x/y/width/height`，預覽圖保存在樹莓派 `~/vision_workspace/26H_Remake_Support/Data/Calibration/roi_selection_preview.png`。此腳本**只查看、記錄 ROI，不會自動修改配置**。如四個數值不同於 `Vision/Config/vision_tools.toml` 的 `[vision_geometry]`，先統一標定和拍攝所用的 ROI，再繼續。

## 2. 樹莓派：需要重新標定時，生成新候選

在同一個樹莓派終端，人工將球桿依次調到提示角度，穩定後按空格，按畫面提示選軌道角點和位置點：

```bash
python3 Vision/APP/calibrate_geometry.py \
  --camera /dev/video0 \
  --angles 12,14,16,18,20,22,24,26,28,30 \
  --positions=-10,-5,0,5,10 \
  --exposure-time-absolute 10 \
  --output-dir Data/Calibration/generated
```

結果：樹莓派 `Data/Calibration/generated/dynamic_calibration_manual.json`，同一目錄還有供檢查的相機原圖和展開圖。這個腳本使用**人工讀取的角度**，產物會標記 `test_only`；它只供新資料採集和檢查，**不會自動變成正式運行標定**。現行正式 JSON 已包含完整 12–30°十樣本，無需為了正常啟動重跑本步。

把候選標定與檢查圖片複製回 Windows。在 Windows PowerShell 執行：

```powershell
cd D:\26H-remake\26H_Remake_Support
scp -r ikun@192.168.137.2:/home/ikun/vision_workspace/26H_Remake_Support/Data/Calibration/generated Data\Calibration\
```

`generated` 是樹莓派的輸出資料夾；`Data\Calibration\generated` 是 Windows 的副本。此命令不覆蓋正式鏡像內的標定。

## 3. 樹莓派：拍攝訓練圖片

回到樹莓派的 `~/vision_workspace/26H_Remake_Support`，以 12°為例。下面直接讀取正式 `workspace` 已生效且通過實機視覺檢查的十樣本 JSON；拍攝輸出留在 Support，不會寫回正式工作區：

```bash
python3 Vision/APP/capture_training_data.py \
  --calibration ../workspace/assets/calibration/dynamic_calibration_12_30deg.json \
  --output-dir Data/Training/Captures \
  --session angle_12deg_exp10 \
  --angle-deg 12 \
  --exposure-time-absolute 10
```

14、16、18、20、22、24、26、28、30°分別改 `--session` 和 `--angle-deg` 再拍一組。每組保存在樹莓派 `Data/Training/Captures/angle_XXdeg_exp10/`，內含會話資料、圖片和待標註圖片。這裏的人工角度只用於拍攝，不用於正式閉環控制。

拍完後，在 Windows PowerShell 複製整個會話資料夾（包含 `session.json` 和 `metadata.jsonl`，不要只複製 PNG）：

```powershell
cd D:\26H-remake\26H_Remake_Support
scp -r ikun@192.168.137.2:/home/ikun/vision_workspace/26H_Remake_Support/Data/Training/Captures Data\Training\
```

Windows 接收位置是 `Data\Training\Captures\angle_XXdeg_exp10\`。

## 4. Windows：標註、整理和訓練

```powershell
cd D:\26H-remake\26H_Remake_Support
```

若會話的 `unlabeled/` 尚有圖片，執行框選。框選結果直接寫回同一會話的 `images/` 和 `labels/`，不另建輸出目錄；也可在樹莓派桌面做同一步。

```powershell
python Vision\APP\annotate_ball.py `
  --dataset-root Data\Training\Captures `
  --pattern "angle_*deg_exp10"
```

整理已標註的會話（每個角度可重複加一個 `--source`；下面先示範一組）：

```powershell
python Vision\APP\build_yolo_dataset.py `
  --source Data\Training\Captures\angle_12deg_exp10 `
  --output-dir Data\Training\Prepared
```

結果：Windows 的 `Data\Training\Prepared\images\train|val`、`labels\train|val`、`roi_ball.yaml` 和 `manifest.json`。輸出目錄若已有內容，腳本會拒絕覆蓋，請為新一次整理使用新目錄。

若要使用本倉庫已封存的 2405 組、十個角度，無需搬動原始文件；在 Windows PowerShell 用各角度資料夾逐一傳入：

```powershell
$angleDirs = Get-ChildItem Data\Training\steel_ball_12_30deg_exp10\by_angle -Directory -Filter 'angle_*' | Sort-Object Name
$sourceArgs = foreach ($dir in $angleDirs) { '--source'; $dir.FullName }
python Vision\APP\build_yolo_dataset.py @sourceArgs --output-dir Data\Training\Prepared
```

此命令只會在空的 `Prepared` 生成副本；封存資料仍留在 `by_angle`。讀取 `geometry_id` 時，先看會話根目錄 `session.json`，否則讀 `source_records/capture_session.json`。它校驗的是資料內部一致性，**不會**證明目前十樣本生效標定與現行模型的幾何匹配。

將基礎模型放到 Windows 的 `Data\Training\Models\yolo26n.pt`，再訓練：

```powershell
python Vision\APP\train_yolo.py `
  --data Data\Training\Prepared\roi_ball.yaml `
  --model Data\Training\Models\yolo26n.pt
```

結果：Windows 的 `Data\Training\Models\best.pt` 及訓練紀錄。PT→Hailo HEF 在你的本地虛擬機完成，這裏不提供轉換命令。新訓練成品須另行核對後部署；資料集整理與訓練命令本身不會覆蓋正在運行的 `workspace`。

預覽資料改名（不改文件）：

```powershell
python Vision\APP\rename_dataset_files.py
```

只有確認配對數量和備份後才使用 `--apply`；日常資料製作不必執行改名工具。

## 樹莓派：正式視覺

正式運行包內容已由使用者部署到 `~/vision_workspace/workspace`；虛擬環境是 `~/vision_workspace/.venv`，提示符 `(vision_ws)` 不是另一個目錄。Support 工具和舊工作區不是正式啟動依賴。

這條命令打開 `~/vision_workspace/workspace/assets/calibration/dynamic_calibration_12_30deg.json` 取得角度與座標映射，實際有 12、14、…、30°十個樣本。新拍攝流程產生的 `generated/dynamic_calibration_manual.json` 不會自動改變生效文件或運行效果。使用者已在樹莓派確認正式視覺正常；補 12°後未重跑 Task1。

```bash
cd ~/vision_workspace/workspace
source ~/vision_workspace/.venv/bin/activate

python3 best/run.py \
  --port /dev/ttyUSB0 \
  --inference-backend hailort \
  --debug-page \
  --serial-read-timeout-ms 1 \
  --wifi-stream \
  --no-display
```

## Windows：下位機 CSV

這裏使用下位機 USART6 調試串口。先確認實際 COM 號：

```powershell
python Diagnostics\APP\capture_mcu_csv.py --list-ports
```

採集 10 秒 `vision` 通道：

```powershell
python Diagnostics\APP\capture_mcu_csv.py `
  --port COM26 `
  --mode listen `
  --firmware-csv vision `
  --duration-s 10
```

- `--mode listen`：只採集，不發 `ba 22` 或 `task 1`。
- `--firmware-csv vision`：切到 5 ms 視覺鏈路診斷通道。
- 固件 CSV 模式在腳本退出後仍保持。

下位機 `vision` 模式的**串口原始行**是 `V,數值1,數值2,...,數值10`；`V` 是通道標記，不是數據。數值按以下順序打印，週期標稱 5 ms：

| 數值列 | 名稱 | 單位／含義 |
|---:|---|---|
| 1 | `stm32_time_ms` | ms；下位機時鐘，用它核對 5 ms 打印間隔。 |
| 2 | `rx_seq` | 最近收到的樹莓派 BALL_STATE 包序號；連續打印相同值不等於新包。 |
| 3 | `pi_time_ms` | ms；該包攜帶的樹莓派時間戳。 |
| 4 | `tracking_valid` | 0/1；該包聲稱的上位機追蹤有效標誌。 |
| 5 | `rx_age_ms` | ms；距離最近收到 BALL_STATE 包的時間；無包時為 9999。 |
| 6 | `packet_x_001cm` | 0.01 cm；最近收到的包內球坐標，除以 100 才是 cm。 |
| 7 | `estimate_valid` | 0/1；下位機當前球狀態估計是否有效。 |
| 8 | `estimated_x_001cm` | 0.01 cm；下位機估計的球坐標。 |
| 9 | `estimated_vx_001cms` | 0.01 cm/s；下位機估計的球速度。 |
| 10 | `vision_age_ms` | ms；最近有效視覺觀測距今的時間；無有效觀測時為 9999。 |

Windows 採集腳本保存的文件**不是直接把這 10 列當成文件第 1～10 列**：它先加 `host_iso8601`（本機日期時間）、`host_unix_ns`（本機 Unix 納秒）、`elapsed_s`（採集經過秒數）、`rx_interval_ms`（Windows 相鄰收行間隔）、`record_type`（如 `vision_sample`），再放解析後的下位機字段。文件有表頭，按字段名讀；`packet_x_cm`、`estimated_x_cm`、`estimated_vx_cm_s` 已轉為 cm、cm/s。Windows 收行間隔受串口緩衝影響，不能代替第 1 列的 STM32 5 ms 時基。

Task1 前恢復 `control`：

```powershell
python Diagnostics\APP\capture_mcu_csv.py `
  --port COM26 `
  --mode listen `
  --firmware-csv control `
  --duration-s 1
```

下位機 `control` 模式的**串口原始行**沒有 `V` 前綴，直接按以下順序打印 13 列，週期標稱 5 ms：

| 列 | 名稱 | 單位／含義 |
|---:|---|---|
| 1 | `estimated_x_cm` | cm；下位機球位置估計，**不是直接收到的上位機原始坐標**。 |
| 2 | `target_x_cm` | cm；當前球目標位置。 |
| 3 | `estimated_vx_cm_s` | cm/s；下位機球速度估計。 |
| 4 | `motor_angle_deg` | °；實際電機／球桿角度。 |
| 5 | `angle_command_deg` | °；控制器要求的角度。 |
| 6 | `brake_p_offset_deg` | °；BBP 制動角度偏移。 |
| 7 | `terminal_offset_deg` | °；終端修正角度偏移。 |
| 8 | `brake_p_active` | 0/1；BBP 是否啟用。 |
| 9 | `terminal_push_active` | 0/1；終端推動是否啟用。 |
| 10 | `terminal_trim_active` | 0/1；終端微調是否啟用。 |
| 11 | `terminal_brake_gate_active` | 0/1；終端制動門是否啟用。 |
| 12 | `sequence_stage` | 0=無序列；Task1 中 1=+5 階段、2=-5 階段。 |
| 13 | `vision_age_ms` | ms；最近有效視覺觀測距今的時間。 |

`capture_mcu_csv.py` 保存的 `control_sample` 行同樣先有 Windows 時間戳等輔助列；`run_task1.py` 的 Task1 CSV 則在上述 13 個控制通道前另加 `t_s`、`phase`。完整文件字段和 probe 定義見 `DATA_FORMAT.md`。

## 樹莓派：vision probe

vision probe 是同一個正式 `best/run.py` 進程的逐幀內部觀測 CSV，不是另一套識別算法，也不是下位機串口通道。它為每個已處理相機幀記錄耗時、坐標、valid、置信度、角度和 bbox 中心，用於定位漏幀、延遲與坐標跳變發生在哪一端。

清理後無須重新上傳整套 Support；在樹莓派直接運行以下命令。先停止平時的視覺進程，避免兩個進程同時佔用相機與串口：

```bash
mkdir -p ~/vision_workspace/diagnostics
cd ~/vision_workspace/workspace
source ~/vision_workspace/.venv/bin/activate
python3 best/run.py \
  --port /dev/ttyUSB0 \
  --inference-backend hailort \
  --debug-page \
  --serial-read-timeout-ms 1 \
  --wifi-stream \
  --no-display \
  --vision-probe-csv "$HOME/vision_workspace/diagnostics/vision_probe_$(date +%Y%m%d_%H%M%S).csv"
```

此命令與平時正式入口相同，只額外加入 `--vision-probe-csv`，輸出到樹莓派 `~/vision_workspace/diagnostics/`；若先前清理掉該目錄，`mkdir -p` 會重新建立。完成後在 Windows PowerShell 複製回本地 `Data/TestRecords/`：

```powershell
cd D:\26H-remake\26H_Remake_Support
scp ikun@192.168.137.2:/home/ikun/vision_workspace/diagnostics/vision_probe_實際時間戳.csv Data\TestRecords\
```

將 `實際時間戳` 換成 Pi 端產生的檔名，不要照抄佔位符。`Diagnostics/APP/capture_vision_csv.sh` 保留為可復用腳本；只有把它單獨部署到 Pi 後才可直接在 Pi 執行。

## Windows：聯合分析與 Task1

將樹莓派 probe 複製到 `Data/TestRecords`，與同一時段的下位機 `vision` CSV 聯合分析。下列兩個檔名是示例，執行時須替換成採集器實際打印的 CSV 路徑；下位機採集器默認會產生帶時間戳的檔名，probe 亦然：

```powershell
python Diagnostics\APP\analyze_vision.py `
  --mcu Data\TestRecords\mcu_vision_10s.csv `
  --probe Data\TestRecords\vision_probe_10s.csv
```

MCU 剛復位或機械零點改變後初始化：

```powershell
python Diagnostics\APP\initialize_zero.py --port COM26
```

確保固件已恢復 `control` 且樹莓派正式視覺正在運行，再啟動 Task1。用同一個變量把本次採集檔交給分析腳本，不要分析舊檔：

```powershell
$task1Csv = "Data\TestRecords\task1_$(Get-Date -Format yyyyMMdd_HHmmss).csv"
python Diagnostics\APP\run_task1.py --port COM26 --output $task1Csv
python Diagnostics\APP\analyze_task1.py $task1Csv
```

`run_task1.py` 只發 `task 1`；Task1 參數和 `0 → +5 → -5` 狀態機屬於下位機固件，退出時腳本會嘗試發送 `task stop`。
