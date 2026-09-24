# algorithm：正式運行流程

這裏只放 `best/run.py` 正式命令需要的流程與資料。文件按職責分開；`formal/` 和 `WIFI_test/` 等既有 Python 導入名稱暫不更動，以保持已驗證的啟動鏈。

| 目錄／文件 | 作用 | 正式命令中的位置 |
|---|---|---|
| `formal/track_ball.py` | 解析參數、啟動／停止正式跟蹤。 | `run.py` 的下一層入口。 |
| `app/tracking_setup.py` | 建立相機、標定、檢測器和 tracker。 | 啟動初始化。 |
| `app/tracking_loop.py` | 相機幀與角度對齊、逐幀追蹤。 | 主循環。 |
| `app/tracking_support.py` | 選擇 HailoRT/NCNN 後端，校驗模型尺寸及幾何資料。 | 檢測器裝配。 |
| `app/vision_geometry.py` | 固定相機 ROI 與圖像尺寸檢查。 | 幾何檢查。 |
| `app/balance_runtime.py` | BALL_STATE 發送、診斷 probe、debug 頁等運行服務。 | 上下位機數據交接；本命令未啟用上位機執行器控制。 |
| `core/calibration.py` | 角度樣本、透視展開與像素到厘米映射。 | 讀取 active JSON。 |
| `core/tracker.py`、`core/estimator.py` | 候選關聯、valid、估計器實現。 | 正式使用 bbox 中心；Kalman 類存在但本命令未啟用。 |
| `io/runtime.py` | USB 相機、串口、角度遙測與 BALL_STATE 協議。 | 硬件 IO。 |
| `control/balance.py` | 可選的上位機平衡控制器；此模組被運行服務導入。 | 本命令不帶啟用執行器的兩個安全開關；Task1 控制在 STM32。 |
| `config.py`、`config.toml`、`paths.py` | 配置解析、正式參數與統一路徑。 | 正式入口只讀 TOML 的六個分組。 |
| `calibration_data/active/` | 正式進程打開的標定 JSON。 | 相機展開和厘米座標。 |
| `hailo_model/` | `best.hef` 與 `metadata.yaml`。 | HailoRT 推理。 |

資料流：相機幀 + STM32 實際角度 → 固定 ROI 與動態展開 → Hailo bbox → 球心厘米座標與 valid → BALL_STATE → STM32 估計及 Task1 控制。`debug_page/` 與 `WIFI_test/` 只鏡像／傳送圖像，不應再擁有第二個相機。

## 配置邊界

`formal/track_ball.py` 明確讀取 `vision_geometry`、`tracking`、`detector`、`tracker`、`debug`、`formal_tracking` 六組；標定、採集、訓練和模型匯出的工具配置應放在 Support，不留在這份運行 TOML。除這個配置清理外，這次不更改算法參數或模組導入路徑。
