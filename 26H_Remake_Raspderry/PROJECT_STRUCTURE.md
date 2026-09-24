# 運行架構

正式入口是 **best/run.py**，由 **ballbeam/app/main.py** 啟動。逐幀處理在 **ballbeam/app/tracking_setup.py** 與 **ballbeam/app/tracking_loop.py**；它們調用下列模組：

| 位置 | 責任 | 復用時需核對 |
|---|---|---|
| **ballbeam/app/** | 正式流程、最新球狀態、probe | 任務編排和發送時序 |
| **ballbeam/vision/** | 動態透視、位置映射、bbox 球心、追蹤及 HailoRT 推理 | 相機幾何、模型輸入與檢測目標 |
| **ballbeam/hardware/** | USB 相機、下位機串口及角度遙測 | 設備節點與協議 |
| **ballbeam/interfaces/** | 同進程 DebugPage、MJPEG | 網絡接口；不另開相機 |
| **config/runtime.toml** | 正式命令參數 | 新機構的設備和算法參數 |
| **assets/** | 生效 JSON、HEF、metadata | 標定與模型需成套驗證 |

正式配置採用 HailoRT、每幀推理與 YOLO bbox 球心；不啟用霍夫圓或樹莓派 Kalman。來源中的 RANSAC refinement 路徑可能執行，但正式球位置仍取 bbox。**vision/detection_runtime/ncnn_backend.py** 含 Hailo 後端共用的尺寸／letterbox 輔助，不能只因選 Hailo 就刪除。閉環控制在 STM32，本包的 **control/** 是現有 Python 代碼依賴。

正式依賴與精確命令見 [README.md](README.md)；文件搬遷映射及校驗邊界見 [PROVENANCE.md](PROVENANCE.md)。
