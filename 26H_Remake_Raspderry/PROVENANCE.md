# 來源與重構邊界

## 唯一正式入口

樹莓派原命令 `python3 best/run.py --port /dev/ttyUSB0 --inference-backend hailort --debug-page --serial-read-timeout-ms 1 --wifi-stream --no-display` 保留。現在 `best/run.py` 只導入 `ballbeam.app.main.main`；不另建立視覺循環。

## 原始證據

重構前的來源工作區曾位於樹莓派 `/home/ikun/vision_workspace/workspace`，本地採回的 `_pi_raw_new` 曾與正式來源檔逐一核對。原模組來源及實機 Python/HailoRT 版本保存在 `RUNTIME_ENVIRONMENT_RASPBERRY_PI.txt`。2026-09-24 使用者已把重構包部署為新的 `/home/ikun/vision_workspace/workspace`；舊目錄是否仍留在樹莓派，不影響本地來源記錄。

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

生效 JSON 採用先前位於樹莓派 `/home/ikun/vision_workspace/workspace_26h_remake/calibration/output/roi_128x640/dynamic_calibration.json` 的完整實測標定；即使舊樹莓派目錄已清理，正式副本仍在本包 `assets/calibration/dynamic_calibration_12_30deg.json`，Windows Support 亦保存參考副本。`samples` 為 12、14、…、30°十個角度，`geometry_id=8a5cd731dad6021704fb36f25fd423fa7ecd1634c998e23d7eaf9b13ff81126f`。來源 ROI 與此前相同；14–30°九個原有樣本逐項相同。此前九樣本 JSON 的 ID 為 `b5db7d686fc483d125f523499dbbdb9bc71a2d9a2b7f9709992a53b8174de5ad`，其中 12°僅是範圍標記，實際採用 14°樣本。新版在 12°真正使用 12°樣本，12–14°之間按兩個樣本插值。

2405 組封存訓練資料（包括 12°組）的採集記錄仍是舊幾何 ID，未改寫；HEF 也未重新編譯。幾何 ID 差異不能單獨證明 HEF 不兼容，亦不能證明兼容。使用者已在樹莓派測試工作區實測 12–14°視覺正常，且正式 `workspace` 視覺正常；本次補標定後沒有重跑 Task1，不能將舊 Task1 結果寫成更新後的測試結果。

`assets/models/hailo/metadata.yaml` 是編譯成品自帶 metadata，內含舊 Windows 訓練路徑；這是來源記錄，不是當前運行的路徑配置。此包沒有 `deployment.json`，Hailo 模型與標定幾何不能由程式自動驗證，實機驗收時必須人工核對。

## 驗證邊界

已驗證：樹莓派部署包 49 項 SHA-256、五項離線單元測試、CLI、十個實際角度樣本，以及 12–14°與正式入口的實機視覺運行。`deployment.json` 不存在，因此模型幾何 ID 不能自動比對。未在補標定後重跑 Task1；這一點不應寫成已驗證。樹莓派正式位置現為 `~/vision_workspace/workspace`，虛擬環境獨立位於 `~/vision_workspace/.venv`。
