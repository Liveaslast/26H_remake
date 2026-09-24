# 資料與 CSV 格式

## 標定

- **Data/Calibration/active/dynamic_calibration_12_30deg.json**：正式標定 JSON 的參考副本。
- **Data/Calibration/angle_12_30deg/source_images**：標定來源圖，共 10 張。
- **Data/Calibration/angle_12_30deg/rectified_images**：對應展開圖，共 10 張。
- **Data/Calibration/generated**：按需部署 Pi 端工具後，重新標定的結果；不自動變成正式配置。

正式 JSON 與此參考副本的 **samples** 均為 12、14、16、18、20、22、24、26、28、30°。角點和位置映射在 JSON 中；來源沒有獨立點位 TXT。

## 訓練資料

**Data/Training/steel_ball_12_30deg_exp10/by_angle** 按 12、14、16、18、20、22、24、26、28、30°分組：

- **images/\*.png**：640×128 ROI。
- **labels/\*.txt**：同名 YOLO 標籤，格式為 **class x_center y_center width height**。
- **source_records/**：不可改寫的原採集會話和逐幀 metadata。

完整資料為 2405 張圖片和 2405 個配對標籤。

資料集整理腳本先讀會話根目錄的 **session.json**；沒有時讀封存的 **source_records/capture_session.json**。因此十個 **by_angle/angle_\*** 目錄可直接作為 **--source**，無需改寫資料。整理時校驗圖片、標註和採集時的 **geometry_id**；這是資料內部一致性檢查，不是 HEF／生效標定的自動匹配檢查。

## 下位機 CSV 模式

下位機 USART6 調試打印有三種固件模式：

| 固件命令 | 頻率 | 用途 |
|---|---:|---|
| **csv control** | 5 ms / 200 Hz | Task1 和控制過程分析；MCU 啟動後默認模式。 |
| **csv vision** | 5 ms / 200 Hz | 視覺包到達、valid、延遲和下位機估計質量分析。 |
| **csv off** | — | 關閉週期 CSV 打印。 |

**--firmware-csv unchanged** 表示不發切換命令。模式會保持到再次切換或 MCU 復位。

### control 通道的 13 列

| # | 字段 | 含義 |
|---:|---|---|
| 1 | **estimated_x_cm** | 下位機使用的球位置估計（a-b濾波）。 |
| 2 | **target_x_cm** | 當前目標位置。 |
| 3 | **estimated_vx_cm_s** | 下位機估計球速度（a-b濾波）。 |
| 4 | **motor_angle_deg** | 實際電機/桿角度。 |
| 5 | **angle_command_deg** | 控制器目標角度。 |
| 6 | **brake_p_offset_deg** | BBP 制動角度偏移。 |
| 7 | **terminal_offset_deg** | 終端修正角度偏移。 |
| 8 | **brake_p_active** | BBP 是否有效。 |
| 9 | **terminal_push_active** | 終端推動是否有效。 |
| 10 | **terminal_trim_active** | 終端微調是否有效。 |
| 11 | **terminal_brake_gate_active** | 終端制動門是否有效。 |
| 12 | **sequence_stage** | 0=無序列，Task1 中 1=+5、2=-5。 |
| 13 | **vision_age_ms** | 最近有效視覺觀測的年齡。 |

Task1 文件另加 **t_s** 和 **phase**。

### vision 通道的線上字段

原始行以 **V** 開頭，後接 10 個整數：

| # | 字段 | 含義 |
|---:|---|---|
| 1 | **stm32_time_ms** | STM32 時基。 |
| 2 | **rx_seq** | 最近 BALL_STATE 序號。 |
| 3 | **pi_time_ms** | 包內樹莓派時間。 |
| 4 | **tracking_valid** | 樹莓派追蹤有效標誌。 |
| 5 | **rx_age_ms** | 最近接收包年齡。 |
| 6 | **packet_x_001cm** | 包內位置，單位 0.01 cm。 |
| 7 | **estimate_valid** | 下位機估計是否有效。 |
| 8 | **estimated_x_001cm** | 下位機估計位置，單位 0.01 cm。 |
| 9 | **estimated_vx_001cms** | 下位機估計速度，單位 0.01 cm/s。 |
| 10 | **vision_age_ms** | 最近有效視覺觀測年齡。 |

Windows 採集器會轉換成 cm/cm/s，並附加主機時間、**rx_interval_ms**、**record_type**、**rx_present**、**x_changed**、**x_unchanged_ms** 和 **raw_line**。5 ms 完整性必須使用 **stm32_time_ms** 判斷，不能用 Windows 的 **rx_interval_ms** 冒充。

## 樹莓派 vision probe

probe 是 **best/run.py** 同一正式視覺進程內的逐幀觀測 CSV：每處理完一個相機幀寫一行。它不經過 USART6，不改變識別和坐標計算邏輯；但逐幀寫盤本身可能增加耗時，不能把開啟 probe 時測得的幀率無條件當成無 probe 的正式幀率。

| 字段 | 含義 |
|---|---|
| **t**、**frame_seq** | 幀時間和 probe 行序號。 |
| **result_ready_t**、**capture_to_log_ms** | 結果完成時間和從幀到落盤的總延遲。 |
| **inference_ms** | Hailo 推理耗時。 |
| **refinement_ms** | 原程序 refinement/RANSAC 路徑耗時；正式坐標仍取 bbox 中心。 |
| **processing_ms** | 本幀視覺總處理耗時。 |
| **raw_x_cm**、**raw_vx_cm_s** | 視覺結果位置和速度字段。 |
| **sent_x_cm**、**sent_vx_cm_s** | 提交給 BALL_STATE 發送端的最新值；逐幀記錄不等於串口逐幀都實際發包。 |
| **measurement_valid** | 本幀是否有有效測量。 |
| **tracking_valid** | tracker 是否保持有效。 |
| **sent_valid** | 發送狀態是否標記有效。 |
| **confidence**、**source**、**reason** | 置信度、來源和無效/回退原因。 |
| **actual_angle_deg** | 與該幀匹配的下位機實際角度。 |
| **center_x_px**、**center_y_px**、**radius_px** | 檢測中心和半徑診斷值。 |
| **measurement_x_cm** | 本幀直接測量位置。 |
| **kalman_x_cm**、**kalman_vx_cm_s** | 兼容分析器的字段名；正式命令未啟用樹莓派 Kalman，不能因列名判定 Kalman 已開。 |

probe 回答“樹莓派產生了甚麼”；下位機 **vision** CSV 回答“STM32 收到及估計成甚麼”；**control** CSV 回答“控制器如何使用估計結果”。聯合對齊才能區分問題在識別、傳輸還是下位機估計。
