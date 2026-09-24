# Support 資料與工具來源

## 資料

| 現行位置 | 可追溯來源 |
|---|---|
| **Data/Calibration/active/dynamic_calibration_12_30deg.json** | 與 Raspberry **assets/calibration/dynamic_calibration_12_30deg.json** 內容相同，實際含 12、14、…、30°十樣本 |
| **Data/Calibration/angle_12_30deg/** | 從樹莓派標定輸出保存的十張來源圖及十張展開圖 |
| **Data/Training/steel_ball_12_30deg_exp10/** | 本地 **_pi_raw/best/algorithm/no_m0/roi_dataset_128x640**；2405 張圖片與 2405 個同名標籤 |
| **Data/TestRecords/** | 視覺延遲、有效率、座標跳變及 Task1 的實際測試 CSV |

採集 session、逐幀 metadata 與標註原文均保留，不為對齊現行標定而回寫歷史 geometry ID。資料集腳本可讀 **source_records/capture_session.json**，不要求搬動封存文件。生效標定的幾何差異與實機驗證邊界見 [Raspberry PROVENANCE](../../26H_Remake_Raspderry/PROVENANCE.md)。

## 工具映射

| 現行入口 | 原用途／來源 |
|---|---|
| **Vision/APP/select_roi.py**、**calibrate_geometry.py**、**capture_training_data.py** | 相機 ROI、軌道標定與訓練圖採集 |
| **Vision/APP/annotate_ball.py**、**build_yolo_dataset.py**、**train_yolo.py** | bbox 標註、資料集整理與 YOLO 訓練 |
| **Vision/APP/rename_dataset_files.py** | 訓練與標定資料的成對改名預覽 |
| **Diagnostics/APP/capture_mcu_csv.py**、**capture_vision_csv.sh** | STM32 5 ms CSV 與 Pi 逐幀 probe |
| **Diagnostics/APP/analyze_vision.py**、**analyze_vision_probe.py** | 視覺鏈路與幀率分析 |
| **Diagnostics/APP/initialize_zero.py**、**run_task1.py**、**analyze_task1.py** | 零點初始化、Task1 記錄與分析 |

可執行入口只在 **APP/**；**Core/**、**IO/**、**Config/** 是按依賴閉包收納的實現。未納入一次性參數遍歷、舊階躍、VOFA 監視、重複備份和其他與當前資料／5 ms 診斷鏈無關的腳本。正式視覺代碼由 Raspberry 包單獨維護。
