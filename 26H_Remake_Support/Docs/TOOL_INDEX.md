# 工具索引：先按任務找入口

所有命令均在 `26H_Remake_Support` 根目錄執行。`Vision/APP` 製作視覺資料，`Diagnostics/APP` 採集與分析測試；`Core`、`IO` 是前兩者的依賴，通常不直接運行。完整參數與複製命令見 [COMMANDS.md](COMMANDS.md)，各數據列見 [DATA_FORMAT.md](DATA_FORMAT.md)。

| 目標 | 平台 | 入口 | 主要輸入 → 輸出 |
|---|---|---|---|
| 看相機粗 ROI | 樹莓派 | `Vision/APP/select_roi.py` | `/dev/video0` → ROI 數值及預覽圖；不改配置 |
| 人工角度幾何標定 | 樹莓派 | `Vision/APP/calibrate_geometry.py` | 相機、角度/位置點 → `Data/Calibration/generated/` JSON 與檢查圖 |
| 拍 12–30°訓練圖 | 樹莓派 | `Vision/APP/capture_training_data.py` | 標定 JSON、相機 → `Data/Training/Captures/<session>/` |
| 框選球 bbox | Windows；亦可樹莓派桌面 | `Vision/APP/annotate_ball.py` | 會話 `unlabeled/` → 同會話 `images/`、`labels/` |
| 校驗並分 train/val | Windows | `Vision/APP/build_yolo_dataset.py` | 一個或多個已標註會話 → `Data/Training/Prepared/`；亦可讀封存的 `by_angle/angle_*` |
| 訓練 YOLO | Windows | `Vision/APP/train_yolo.py` | `roi_ball.yaml`、基礎 PT → `Data/Training/Models/` |
| 預覽批量改名 | Windows | `Vision/APP/rename_dataset_files.py` | 現有資料 → 預覽；只有 `--apply` 才修改 |
| 採下位機 CSV | Windows | `Diagnostics/APP/capture_mcu_csv.py` | USART6 調試串口 → `Data/TestRecords/` CSV |
| 採視覺 probe | 樹莓派 | `Diagnostics/APP/capture_vision_csv.sh` | 同一正式 `best/run.py` → `~/vision_workspace/diagnostics/` CSV |
| 看幀率/valid/跳變 | Windows | `Diagnostics/APP/analyze_vision_probe.py` | 單份 probe CSV → 分析輸出 |
| 對齊視覺與下位機 | Windows | `Diagnostics/APP/analyze_vision.py` | probe + MCU vision CSV → 聯合分析 |
| 初始化零點 | Windows | `Diagnostics/APP/initialize_zero.py` | 指定 COM 口 → 下位機 `task init` |
| 啟動並記錄 Task1 | Windows | `Diagnostics/APP/run_task1.py` | COM 口 → `Data/TestRecords/` control CSV |
| 分析 Task1 | Windows | `Diagnostics/APP/analyze_task1.py` | Task1 CSV → 分析輸出 |

復用新項目時先複製這套目錄職責，再明確替換相機 ROI、標定、資料集、模型與串口配置；不要把舊機構的成品 JSON 或 HEF 當作通用模板。正式進程和測試工具分開部署。來源與文件取捨見 [PROVENANCE.md](PROVENANCE.md)。
