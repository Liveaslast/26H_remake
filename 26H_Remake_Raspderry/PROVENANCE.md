# 樹莓派正式運行包：嚴格溯源記錄

## 唯一根命令

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

本目錄的正式運行代碼只按上述命令的實際載入鏈整理，沒有替換演算法，也沒有把歷史版本、測試程式、NCNN 回退模型或舊標定混入運行鏈。訓練資料另置於頂層 `datasets/`，不會被正式進程匯入。

## 實際載入鏈

1. `best/run.py` → `best/algorithm/formal/track_ball.py`
2. `track_ball.py` → `algorithm.app`、`algorithm.core`、`algorithm.io`、`algorithm.config`
3. `algorithm/config.toml` 載入分組：`vision_geometry`、`tracking`、`detector`、`tracker`、`debug`、`formal_tracking`
4. `tracking_support.py` → `ball_detection_runtime.detector.AdaptiveBallDetector`
5. `--inference-backend hailort` → `ball_detection_runtime/hailort_backend.py`
6. HailoRT 後端 → `best/algorithm/hailo_model/best.hef`
7. 正式標定 → `best/algorithm/calibration_data/active/roi_128x640/dynamic_calibration_12_30deg.json`
8. `--debug-page` → `best/debug_page`（Flask 模板與靜態資源）
9. `--wifi-stream` → `best/WIFI_test/mjpeg_stream.py`
10. `/dev/ttyUSB0` → `algorithm/io/runtime.py` 的串口遙測與 BALL_STATE 發送

## 關鍵行為核對

- 推理後端：原生 HailoRT；模型是 `best.hef`，固定輸入 `128x640`。
- 檢測週期：`detection_interval=1`，每幀呼叫 HAT 推理。
- 球心輸出：`measurement_center="bbox"`，厘米位置取 YOLO bbox 中心。
- 卡爾曼：命令沒有 `--enable-kalman`，其 `store_true` 預設為 `False`；正式輸出走原始測量分支，不做樹莓派端卡爾曼濾波。
- 霍夫圓：此運行閉包內沒有 `cv2.HoughCircles`。
- 注意：`precision` 檢測器仍會執行來源程式既有的 RANSAC 圓擬合/快取；正式 tracker 因 `measurement_center="bbox"` 不採用該圓心。這是原始命令的真實行為，本整理未擅自刪改。
- 顯示：`--no-display` 關閉本機 OpenCV 視窗；Debug Page 與 Wi-Fi MJPEG 仍啟用。

## 12–30°資料與標定證據

- Hailo 模型的 `metadata.yaml` 明寫訓練來源為 `roi_ball_128x640_angle12/roi_ball.yaml`。
- 原鏡像中的對應 ROI 資料目錄由 `angle12_exp10`、`angle14_exp10` 一直到 `angle30_exp10`。
- 正式命令實際載入的標定 JSON 明寫 `angle_range_deg: [12.0, 30.0]`。
- 該 JSON 內實際標定樣本是 `14,16,18,20,22,24,26,28,30`，metadata 同時標記 `test_only=true`、`angle_source=manual_assumed`。這個差異來自原始檔案，未被本整理修飾或補造。
- 訓練圖片與標註不會在正式推理時被讀取；它們只作為可選的來源資料保存在頂層 `datasets/`。正式進程使用的是已編譯 HEF、模型 metadata 和生效標定 JSON。

## 樹莓派實機來源核驗

第一份 `D:\26H-remake\_pi_raw` 只含 `best`，缺少正式程式會從工作區根目錄匯入的兩個檢測套件，因此不能單獨構成完整運行環境。

其後從樹莓派重新取得 `D:\26H-remake\_pi_raw_new`。實機環境記錄確認以下模組全部直接來自 `/home/ikun/vision_workspace/workspace`：

- `ball_detect_yolo`
- `ball_detect_yolo_combind`
- `ball_detect_yolo_combind.detector`
- `ball_detect_yolo_combind.hailort_backend`

整理前的 41 個正式運行來源檔已與 `_pi_raw_new` 逐檔進行 SHA-256 比對，差異數為 0。因此程式、HEF 和標定 JSON 均源自樹莓派實際版本，不依賴候選歷史版本或本機推測。

## 溯源後的指向性重命名

以下改名只改目錄、模組引用與配置路徑，不替換檢測算法、模型或標定內容：

- `ball_detect_yolo` → `ball_detection_common`
- `ball_detect_yolo_combind` → `ball_detection_runtime`
- `best/algorithm/best_hailo_model` → `best/algorithm/hailo_model`
- `best/algorithm/no_m0/calibration_output/roi_128x640/dynamic_calibration_no_m0.json` → `best/algorithm/calibration_data/active/roi_128x640/dynamic_calibration_12_30deg.json`

`no_m0` 原本是歷史上的「不依賴 MSPM0、人工提供角度」命名，但該目錄在正式命令中實際承擔的是 12–30°視覺標定資料，因此改為 `calibration_data`。重命名前的實機模組名稱與絕對路徑仍原樣保存在 `RUNTIME_ENVIRONMENT_RASPBERRY_PI.txt`，作為來源證據，不隨整理結果改寫。

標定來源照片按用途分到 `calibration_data/source_capture/angle_12_30deg/source_images` 與 `rectified_images`。角點、位置映射與透視資料原本就保存在生效 JSON 的 `samples` 中，來源沒有獨立點位 TXT，因此未人工生成替代文件。

`datasets/steel_ball_12_30deg_exp10` 保存從原鏡像 `no_m0/roi_dataset_128x640` 溯源出的 2405 張訓練輸入圖與 2405 個一一配對的 YOLO TXT，按 12、14、16、18、20、22、24、26、28、30°和曝光值 10 分組。未標註圖、source ROI 與其他中間圖不屬於這批訓練對，沒有混入。

另外同步了已在實機測試流程中確認的兩個本地修正：`io/runtime.py` 不再因遙測請求而注入假的零值 BALL_STATE；`app/balance_runtime.py` 增加診斷 CSV 欄位。兩者均不改動 Hailo 推理、bbox 球心、RANSAC 執行條件或控制參數。

實機記錄同時確認：Python 3.13.5、HailoRT 4.23.0、NumPy 2.2.4、OpenCV 4.10.0、pyserial 3.5、Flask 3.1.3。完整輸出保存為 `RUNTIME_ENVIRONMENT_RASPBERRY_PI.txt`。

## 明確捨棄

- `algorithm_versions/` 歷史封存與壓縮包
- `__pycache__/`、`.pytest_cache/`、測試、示例、基準、採集與標註工具
- 未標註圖、非訓練中間圖、訓練輸出與舊模型（正式 2405 組訓練對和 20 張標定核對圖除外）
- NCNN 模型與原生 NCNN 擴充（本命令固定 HailoRT）
- TFT、serial_moni、舊標定、標定圖片、Hailo 日誌
- `hailo`（Ultralytics）後端；只保留命令使用的 `hailort` 原生後端

## 部署位置

把本目錄內容放到樹莓派的 `~/vision_workspace/workspace`。虛擬環境仍位於 `~/vision_workspace/.venv`，不包含在此原始碼/模型運行包中。

`SHA256SUMS.txt` 記錄整理後每個檔案的 SHA-256，可用於傳輸後核對。
