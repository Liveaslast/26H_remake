# 運行包結構

本目錄部署到樹莓派的 `~/vision_workspace/workspace`。

```text
workspace/
├─ best/                       正式應用
│  ├─ run.py                   唯一正式啟動入口
│  ├─ algorithm/               運行配置、標定、追蹤、通信與流程編排
│  │  ├─ app/                  運行組裝與循環
│  │  ├─ calibration_data/     正式進程載入的生效標定 JSON
│  │  ├─ control/              上位機側控制命令資料型別；Task1 實際控制在 STM32
│  │  ├─ core/                 標定、估算與追蹤核心
│  │  ├─ formal/               正式追蹤入口實現
│  │  ├─ hailo_model/          Hailo HEF 與模型 metadata
│  │  └─ io/                   相機、串口與角度遙測
│  ├─ debug_page/              Web 調試頁
│  └─ WIFI_test/               Wi-Fi MJPEG 串流
├─ ball_detection_common/      共用檢測型別、基礎檢測與圓擬合
└─ ball_detection_runtime/     正式自適應檢測器及 HailoRT/NCNN 後端
```

正式 HailoRT 調用鏈：

```text
best/run.py
→ best/algorithm/formal/track_ball.py
→ best/algorithm/app/tracking_support.py
→ ball_detection_runtime/detector.py
→ ball_detection_runtime/hailort_backend.py
→ best/algorithm/hailo_model/best.hef
```

正式標定文件：

```text
best/algorithm/calibration_data/active/roi_128x640/dynamic_calibration_12_30deg.json
```

訓練資料、標定照片和離線工具保存在本地同級工程 `26H_Remake_Support`；部署到樹莓派時它可位於 `~/vision_workspace/26H_Remake_Support`，但不會被正式運行命令載入。

PT 到 Hailo HEF 的轉換在本地虛擬機完成；本運行包只保存正式使用的 `best.hef` 和 `metadata.yaml`。

`RUNTIME_ENVIRONMENT_RASPBERRY_PI.txt` 保留重命名前的實機模組來源，是不可改寫的溯源證據。
