# 來源溯源與取捨

## 資料來源

- 訓練集來自 `D:\26H-remake\_pi_raw\best\algorithm\no_m0\roi_dataset_128x640`：2405 張 640×128 PNG 與 2405 個同名 YOLO TXT。
- 標定圖片來自 `D:\26H-remake\_pi_raw\best\algorithm\no_m0\calibration_output\roi_128x640`：10 張來源圖與 10 張展開圖。
- `Data/Calibration/active/dynamic_calibration_12_30deg.json` 與本地 `26H_Remake_Raspderry/assets/calibration/dynamic_calibration_12_30deg.json` 內容相同，只供工具復現與校驗；舊鏡像中的路徑是 `best/algorithm/calibration_data/active/roi_128x640/dynamic_calibration_12_30deg.json`。
- `Data/TestRecords` 是本次視覺延遲、有效率、座標跳變及 Task1 驗證時實際生成的 8 份 CSV。

## 視覺工具映射

| 現入口 | 原文件 |
|---|---|
| `Vision/APP/select_roi.py` | `no_m0/select_source_roi.py` |
| `Vision/APP/calibrate_geometry.py` | `no_m0/calibrate.py` |
| `Vision/APP/capture_training_data.py` | `no_m0/collect_roi.py` |
| `Vision/APP/annotate_ball.py` | `no_m0/label_pruned_roi_dataset.py` |
| `Vision/APP/build_yolo_dataset.py` | `train/prepare_dataset.py` |
| `Vision/APP/train_yolo.py` | `train/train_roi.py` |
| `Vision/APP/rename_dataset_files.py` | `tools/vision_dataset_pipeline/rename_visual_assets.py` |

所需的 `calibration`、`geometry`、`dataset`、相機及遙測模組按依賴閉包分入 `Core`、`IO`、`Config`。只調整 Support 內的匯入路徑和輸出路徑，未修改 `26H_Remake_Raspderry` 的視覺算法。

相機相關入口由樹莓派執行；標註、資料集整理和訓練由 Windows 執行。PT→HEF 在本地虛擬機完成，暫不納入這組 Support 腳本。

## 診斷工具映射

| 現入口 | 原文件 |
|---|---|
| `Diagnostics/APP/capture_mcu_csv.py` | `csv_diagnostics/windows/capture_mcu_vision_csv.py` |
| `Diagnostics/APP/analyze_vision.py` | `csv_diagnostics/windows/analyze_vision_csv.py` |
| `Diagnostics/APP/capture_vision_csv.sh` | `csv_diagnostics/raspberry_pi/run_vision_probe.sh` |
| `Diagnostics/APP/analyze_vision_probe.py` | `csv_diagnostics/raspberry_pi/analyze_vision_probe.py` |
| `Diagnostics/APP/initialize_zero.py` | `control_testing/01_run/initialize_ballbeam_zero.py` |
| `Diagnostics/APP/run_task1.py` | `control_testing/01_run/run_task1_sequence.py` |
| `Diagnostics/APP/analyze_task1.py` | `control_testing/03_analyze/analyze_task1_sequence.py` |
| `Diagnostics/IO/check_serial_link.py` | `control_testing/04_tools/check_serial_duplex.py` |

`Diagnostics/Core` 只保留 Task1 入口的直接依賴。

## 明確排除

- BBP/BPUSH 一次性調參腳本。
- 正負階躍的舊採集與分析腳本。
- 舊 alpha-beta、插值、候選比較與參數遍歷腳本。
- VOFA 監視、自由串口監視及 UART 演示。
- 舊 Task 樣本庫、legacy、重複備份與訓練輸出。
- `capture_roll_frames.py`、`prune_roi_dataset.py` 及正式運行才需要的 tracker/estimator。

排除的依據是：不屬於當前 ROI/標定/YOLO 資料鏈，也不屬於本次 5 ms 視覺與 Task1 驗證鏈。
