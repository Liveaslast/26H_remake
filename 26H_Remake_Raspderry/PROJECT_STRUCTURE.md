# 運行架構與路徑

```text
best/run.py (相容入口)
  → ballbeam/app/main.py
      → app/tracking_setup.py + app/tracking_loop.py
      → vision/calibration.py + vision/tracker.py
      → vision/detection_runtime/detector.py
      → vision/detection_runtime/hailort_backend.py
      → assets/models/hailo/best.hef
      → hardware/runtime.py (相機、角度遙測、BALL_STATE)
      → interfaces/debug_page + interfaces/wifi_stream
```

| 目錄 | 職責 | 復用時要替換甚麼 |
|---|---|---|
| `ballbeam/app/` | 設定、逐幀流程、結果發送、probe | 任務編排與對外數據格式 |
| `ballbeam/vision/` | 幾何標定、bbox 球心、追蹤、推理後端 | 模型、ROI、標定與目標類型 |
| `ballbeam/hardware/` | 固定 USB 相機與下位機串口 | 設備節點、時序與協議適配 |
| `ballbeam/interfaces/` | 只讀調試頁及串流 | 頁面或網絡接口；不可另開相機 |
| `config/` | 正式命令的 TOML 參數 | 新機構的相機及串口參數 |
| `assets/` | 與本機構綁定的生效 JSON、HEF | 整套重新校驗，不能單檔替換 |

`vision/detection_common` 是來源程式的基礎檢測型別及圓擬合；`vision/detection_runtime` 是現行自適應檢測和 HailoRT。`ncnn_backend.py` 仍提供 Hailo 後端使用的圖像尺寸/letterbox 函式，不能因命令選擇 Hailo 就直接刪除。`control/balance.py` 被現有發送/診斷模組導入；實際閉環控制仍屬 MCU。

目前 `hardware/runtime.py` 和 `app/balance_runtime.py` 仍偏大，屬下一層模組拆分工作；這次先完成實際包歸位。拆分其內部類別前，需要樹莓派時序回歸測試，不能僅憑本地導入成功宣稱等價。
