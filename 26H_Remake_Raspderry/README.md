# Raspberry Pi｜鋼球視覺運行包

這是樹莓派正式視覺進程的本地部署鏡像。2026-09-24 已由使用者部署到樹莓派 `/home/ikun/vision_workspace/workspace`，正式視覺實機運行正常。標定拍攝、YOLO 訓練與 CSV 分析工具在 Windows 同級的 `26H_Remake_Support`；下位機控制在 `26H_Remake_DJC`。本目錄不是另一套視覺算法。

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

## 樹莓派正式命令

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

`(vision_ws)` 是提示符名稱；實際虛擬環境位於 `/home/ikun/vision_workspace/.venv`。正式包直接位於 `workspace`；`26H_Remake_Support` 不是運行依賴，不必常駐樹莓派。`python3 -m ballbeam` 也進入同一個 `main()`，但以上命令是實機驗證過的入口。HEF、bbox 球心及 RANSAC 算法未改；標定 JSON 已補入真實 12°樣本。Hailo 模組導入失敗時會明確報錯，不會悄悄改跑 Ultralytics。

部署包的 49 項 SHA-256 校驗均在樹莓派通過；`python3 -B -m unittest discover -s tests -v` 的 5 項離線測試也通過。使用者在樹莓派測試目錄實測新版 12–14°視覺正常，並在正式 `workspace` 啟動後確認正式視覺正常。Task1 曾在補入 12°樣本之前通過；本次沒有重跑，不能記作更新後的 Task1 驗收。舊有 14–30°標定樣本逐項未變，且實際 Task1 電機不進入 12°。
