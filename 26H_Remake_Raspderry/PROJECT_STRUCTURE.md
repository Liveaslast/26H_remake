# 運行包結構與依賴邊界

部署位置是樹莓派的 `~/vision_workspace/workspace`。先看根目錄 `README.md` 的啟動命令；下圖是磁盤上的真實結構，不是計劃中的重命名。

```text
workspace/
├─ best/                       正式應用
│  ├─ run.py                   唯一正式啟動入口
│  ├─ algorithm/               運行配置、標定、追蹤、通信與流程編排
│  │  ├─ app/                  運行組裝與循環
│  │  ├─ calibration_data/     正式進程載入的生效標定 JSON
│  │  ├─ control/              可選上位機控制器實現；Task1 實際控制在 STM32
│  │  ├─ core/                 標定、估算與追蹤核心
│  │  ├─ formal/               正式追蹤入口實現
│  │  ├─ hailo_model/          Hailo HEF 與模型 metadata
│  │  └─ io/                   相機、串口與角度遙測
│  ├─ debug_page/              Web 調試頁
│  └─ WIFI_test/               --wifi-stream 所需的 Wi-Fi MJPEG 串流
├─ ball_detection_common/      共用檢測型別、基礎檢測與圓擬合
└─ ball_detection_runtime/     正式自適應檢測器及 HailoRT/NCNN 後端
```

`best/algorithm/README.md` 逐一說明 app、core、control、io 和模型資料的責任。`WIFI_test`、`formal`、`control` 等舊名稱雖不夠直觀，但已被 Python 直接導入；為避免改變已跑通命令，本次通過文檔明確職責，沒有為美觀而搬動運行模組。

正式 HailoRT 調用鏈：

```text
best/run.py
→ best/algorithm/formal/track_ball.py
→ best/algorithm/app/tracking_support.py
→ ball_detection_runtime/detector.py
→ ball_detection_runtime/hailort_backend.py
→ best/algorithm/hailo_model/best.hef
```

本地正式配置指向的標定文件：

```text
best/algorithm/calibration_data/active/roi_128x640/dynamic_calibration_12_30deg.json
```

訓練資料、標定照片和離線工具保存在本地同級工程 `26H_Remake_Support`；部署到樹莓派時它可位於 `~/vision_workspace/26H_Remake_Support`，但不會被正式運行命令載入。

PT 到 Hailo HEF 的轉換在本地虛擬機完成；本運行包只保存正式使用的 `best.hef` 和 `metadata.yaml`。

`RUNTIME_ENVIRONMENT_RASPBERRY_PI.txt` 保留重命名前的實機模組來源，是不可改寫的溯源證據。

## 依賴閉包核對與保留理由

- `ball_detection_runtime/ncnn_backend.py` 不能因正式後端是 HailoRT 就直接刪除：`hailort_backend.py` 仍導入它的 letterbox／尺寸處理函數，`tracking_support.py` 也導入後端探測函數。
- `ball_detection_common/circle_refine.py` 是正式自適應檢測器現有 RANSAC/refinement 路徑的依賴；bbox 作為最終球心來源不等於此模組未執行。
- `ball_detection_common/detector.py`、`visualization.py` 由套件 `__init__.py` 導出。它們不是本命令的主要球心計算路徑，但刪除前須先改套件介面並在樹莓派回歸測試；這次不冒險移除。
- `core/estimator.py`、`control/balance.py` 同樣在導入閉包中。正式命令未啟用 Kalman 或上位機執行器控制，不代表可以直接刪除被其他模組引用的文件。
- `debug_page/`、`WIFI_test/` 分別由 `--debug-page`、`--wifi-stream` 明確要求，均保留。鏡像沒有訓練照片、CSV 記錄、離線訓練入口或舊標定照片。

正式 `config.toml` 清理後只含上述命令實際讀取的六個分組；清理前後六組鍵值完全相同。這是配置與文檔整理，不是算法改寫。
