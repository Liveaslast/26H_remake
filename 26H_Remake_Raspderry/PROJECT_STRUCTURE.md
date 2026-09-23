# 運行包結構

本目錄部署到樹莓派的 `~/vision_workspace/workspace`。

```text
workspace/
├─ best/                       正式應用
│  ├─ run.py                   唯一正式啟動入口
│  ├─ algorithm/               運行配置、標定、追蹤、通信與流程編排
│  │  ├─ app/                  運行組裝與循環
│  │  ├─ calibration_data/     生效標定 JSON 與對應標定照片
│  │  ├─ control/              上位機安全外環控制類
│  │  ├─ core/                 標定、估算與追蹤核心
│  │  ├─ formal/               正式追蹤入口實現
│  │  ├─ hailo_model/          Hailo HEF 與模型 metadata
│  │  └─ io/                   相機、串口與角度遙測
│  ├─ debug_page/              Web 調試頁
│  └─ WIFI_test/               Wi-Fi MJPEG 串流
├─ ball_detection_common/      共用檢測型別、基礎檢測與圓擬合
├─ ball_detection_runtime/     正式自適應檢測器及 HailoRT/NCNN 後端
├─ datasets/                   不被正式進程載入的訓練資料
│  └─ steel_ball_12_30deg_exp10/
│     └─ by_angle/             12、14……30°的圖片、YOLO 標註與來源記錄
└─ tools/
   └─ data_maintenance/        資料文件安全改名與完整性維護工具
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

標定照片位於 `best/algorithm/calibration_data/source_capture/angle_12_30deg/`；它們僅用於核對和重建標定，不會被正式運行命令載入。

`RUNTIME_ENVIRONMENT_RASPBERRY_PI.txt` 保留重命名前的實機模組來源，是不可改寫的溯源證據。
