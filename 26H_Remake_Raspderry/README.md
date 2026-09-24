# Raspberry Pi｜鋼球視覺運行包

這是樹莓派正式視覺進程的本地部署鏡像。標定拍攝、YOLO 訓練與 CSV 分析在同級 `26H_Remake_Support`；下位機控制在 `26H_Remake_DJC`。本目錄不是另一套視覺算法。

```text
ballbeam/
  app/                 啟動編排、逐幀循環、球狀態發送
  vision/              標定展開、檢測、追蹤、HailoRT/NCNN 後端
  hardware/            USB 相機、串口與角度遙測
  interfaces/          調試頁與 Wi-Fi MJPEG；共用同一相機進程
  control/             來源代碼中的可選控制輔助，正式控制在 MCU
config/runtime.toml    正式進程參數
assets/calibration/    生效標定 JSON
assets/models/hailo/   HEF 與原始模型 metadata
tests/                 不需相機的結構與配置測試
best/run.py            舊命令相容入口，僅轉發到 ballbeam.app.main
```

精確模組責任見 [PROJECT_STRUCTURE.md](PROJECT_STRUCTURE.md)，來源與改動邊界見 [PROVENANCE.md](PROVENANCE.md)。

## 已驗證的正式命令，保持不變

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

新包也提供 `python3 -m ballbeam`，但部署驗收之前以上述舊命令為準；兩者進入同一個 `main()`。HEF、標定 JSON、bbox 球心與 RANSAC 算法未改。Hailo 模組導入失敗時會明確報錯，不會悄悄改跑 Ultralytics。

在電腦上可先執行 `python -B -m unittest discover -s tests -v` 和 `python -B best/run.py --help`。這些不能代替樹莓派相機、Hailo、串口、幀率和 Task1 的實機驗收；本地重構不會自動上傳或覆蓋樹莓派現行工作區。

## ROI 對齊

生效 JSON 的粗 ROI 是 `(128,425,1141,121)`，舊 TOML 卻寫 `(129,422,1143,124)`。原本的相等檢查誤放在另一函式 `return` 之後，沒有執行；真正圖像裁切始終使用 JSON 的 ROI。此鏡像把 TOML 對齊 JSON，並恢復檢查，不改實際裁切像素。生效 JSON 現有 12、14、…、30° 十個實測樣本；標定幾何 ID 隨之改變，實機 12°附近的圖像和模型匹配仍須驗證，見 [PROVENANCE.md](PROVENANCE.md)。
