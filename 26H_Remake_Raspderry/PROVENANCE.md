# 來源與重構邊界

## 唯一正式入口

樹莓派原命令 `python3 best/run.py --port /dev/ttyUSB0 --inference-backend hailort --debug-page --serial-read-timeout-ms 1 --wifi-stream --no-display` 保留。現在 `best/run.py` 只導入 `ballbeam.app.main.main`；不另建立視覺循環。

## 原始證據

來源工作區為樹莓派 `/home/ikun/vision_workspace/workspace`，本地採回的 `_pi_raw_new` 曾與正式來源檔逐一核對。原模組來源及實機 Python/HailoRT 版本保存在 `RUNTIME_ENVIRONMENT_RASPBERRY_PI.txt`。本輪只重構本地鏡像，未向樹莓派上傳。

| 重構前 | 重構後 |
|---|---|
| `best/algorithm/formal/track_ball.py` | `ballbeam/app/main.py` |
| `best/algorithm/app/` | `ballbeam/app/` |
| `best/algorithm/core/` | `ballbeam/vision/` |
| `best/algorithm/io/` | `ballbeam/hardware/` |
| `best/algorithm/control/` | `ballbeam/control/` |
| `ball_detection_common/`、`ball_detection_runtime/` | `ballbeam/vision/detection_common/`、`detection_runtime/` |
| `best/debug_page/`、`best/WIFI_test/` | `ballbeam/interfaces/debug_page/`、`wifi_stream/` |
| `best/algorithm/config.toml` | `config/runtime.toml` |
| `best/algorithm/calibration_data/.../*.json` | `assets/calibration/dynamic_calibration_12_30deg.json` |
| `best/algorithm/hailo_model/` | `assets/models/hailo/` |

除資產的相對路徑和四個粗 ROI 配置值外，正式命令所讀 TOML 參數值逐項不變。HEF 與原始 metadata 的內容不變。圖像真正裁切來自標定 JSON 的 `(128,425,1141,121)`；舊 TOML 寫 `(129,422,1143,124)`，且 `require_matching_source_roi()` 的相等檢查位於另一函式 `return` 後，實際不執行。本輪改為與 JSON 一致並恢復檢查，不換取像區域。

## 12–30° 生效標定與驗證邊界

本地鏡像的 active JSON 已採用樹莓派 `/home/ikun/vision_workspace/workspace_26h_remake/calibration/output/roi_128x640/dynamic_calibration.json` 的完整實測標定：`samples` 為 12、14、…、30°十個角度，`geometry_id=8a5cd731dad6021704fb36f25fd423fa7ecd1634c998e23d7eaf9b13ff81126f`。來源 ROI 與此前相同；14–30°九個原有樣本逐項相同。此前九樣本 JSON 的 ID 為 `b5db7d686fc483d125f523499dbbdb9bc71a2d9a2b7f9709992a53b8174de5ad`，其中 12°僅是範圍標記，實際採用 14°樣本。新版在 12°真正使用 12°樣本，12–14°之間按兩個樣本插值。

2405 組封存訓練資料（包括 12°組）的採集記錄仍是舊幾何 ID，未改寫；HEF 也未重新編譯。幾何 ID 差異不能單獨證明 HEF 不兼容，亦不能證明兼容。部署到樹莓派測試工作區後，須實測 12°及其附近的圖像、坐標、valid 和 Task1；本地 JSON/單元測試通過不等於此項實機驗證通過。

`assets/models/hailo/metadata.yaml` 是編譯成品自帶 metadata，內含舊 Windows 訓練路徑；這是來源記錄，不是當前運行的路徑配置。此包沒有 `deployment.json`，Hailo 模型與標定幾何不能由程式自動驗證，實機驗收時必須人工核對。

## 驗證邊界

本地可驗證：Python 導入、CLI、六組 TOML 解析、資產路徑、十個實際角度樣本、ROI 相等檢查、SHA-256。只有樹莓派可驗證：實際相機、HailoRT、串口發包、約 60 FPS、valid、座標質量和 Task1。12°實機回歸前，不應覆蓋原本已跑通的 `~/vision_workspace/workspace`。
