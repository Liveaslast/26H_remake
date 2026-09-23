# Diagnostics 診斷與測試工具

本目錄採集和分析樹莓派視覺、上下位機鏈路與 Task1 數據，不替代正式視覺入口或下位機控制邏輯。

```text
Diagnostics/
├─ APP/    可直接運行的採集、測試和分析入口
├─ Core/   APP 的底層採集實現
└─ IO/     獨立串口鏈路檢查
```

## APP

| 腳本 | 平台 | 應用 |
|---|---|---|
| `capture_mcu_csv.py` | Windows | 從下位機 USART6 調試串口採集 `vision` 或 `control` CSV，附加主機時間。 |
| `capture_vision_csv.sh` | 樹莓派 | 啟動正式 `best/run.py`，額外寫逐幀 vision probe。 |
| `analyze_vision.py` | Windows | 聯合對齊下位機 `vision` CSV 與樹莓派 probe。 |
| `analyze_vision_probe.py` | Windows | 單獨分析 probe 的幀率、耗時、valid、更新間隔和坐標事件。 |
| `initialize_zero.py` | Windows | 發送 `task init`；下位機設當前機械零點並設 22°平衡角。 |
| `run_task1.py` | Windows | 只發送 `task 1`，記錄約 12 秒 `control` CSV，退出時發 `task stop`。 |
| `analyze_task1.py` | Windows | 分析 Task1 的位置、速度、角度和控制狀態。 |

## CSV 模式不是採集 mode

`capture_mcu_csv.py` 有兩組不同參數：

- `--mode listen/ba22/task1`：採集器是否順便發控制命令。
- `--firmware-csv vision/control/off/unchanged`：要求下位機打印哪組字段。

二者互不等價。固件啟動默認為 `control`；切到 `vision` 後會保持，Task1 前必須再切回 `control`。

### control

下位機每 5 ms 打印 13 列：估計位置、目標位置、估計速度、實際角度、命令角度、BBP/終端偏移、四個控制狀態、序列階段和 vision age。它用於 Task1 控制分析。

### vision

下位機每 5 ms 打印：STM32 時間、樹莓派包序號和時間、tracking valid、接收 age、包內位置、estimate valid、下位機估計位置/速度和 vision age。它用於檢查包是否按時到達、valid 是否掉失及下位機估計是否滯後。

完整列定義見 `../Docs/DATA_FORMAT.md`。

## vision probe 到底是甚麼

probe 是正式樹莓派 `best/run.py` 內部加開的逐幀 CSV 日誌。每處理完一個相機幀寫一行，記錄 Hailo 推理耗時、總處理耗時、bbox/測量坐標、提交給 BALL_STATE 發送端的最新坐標、三層 valid、置信度、角度和原因。逐幀記錄不表示串口逐幀實際發包；寫盤本身也可能帶來額外耗時。

它不是：

- 另一套視覺算法；
- 下位機 CSV 通道；
- 對圖像再做一次識別；
- 控制器的最終狀態。

probe 的作用是確定“樹莓派原本產生了甚麼”。下位機 `vision` CSV 則確定“STM32 收到並估計成甚麼”。兩者對齊後才能判斷跳變或延遲在樹莓派端、傳輸中還是下位機端。

## Core 和 IO

- `capture_task1.py`：`run_task1.py` 的 Task1 串口、CSV 和安全停止實現。
- `ballbeam_capture.py`：控制 CSV 字段解析和通用採集功能。
- `check_serial_link.py`：兩個 COM 口的雙向鏈路測試，只用於通信排障。

`__init__.py` 都只是套件標記。

## 常用命令

```powershell
cd D:\26H-remake\26H_Remake_Support
python Diagnostics\APP\capture_mcu_csv.py --list-ports
python Diagnostics\APP\capture_mcu_csv.py --port COM26 --mode listen --firmware-csv vision --duration-s 10
python Diagnostics\APP\capture_mcu_csv.py --port COM26 --mode listen --firmware-csv control --duration-s 1
python Diagnostics\APP\initialize_zero.py --port COM26
$task1Csv = "Data\TestRecords\task1_$(Get-Date -Format yyyyMMdd_HHmmss).csv"
python Diagnostics\APP\run_task1.py --port COM26 --output $task1Csv
python Diagnostics\APP\analyze_task1.py $task1Csv
```

樹莓派 probe 的啟動和聯合分析命令見 `../Docs/COMMANDS.md`。
