# Raspberry Pi 正式視覺運行包

這個目錄是部署到樹莓派 `~/vision_workspace/workspace` 的**運行包**，不是照片採集或模型訓練工作區。正式入口固定為 `best/run.py`；資料製作、訓練和 CSV 分析放在同級的 `26H_Remake_Support`。

## 目錄分工

| 位置 | 責任 |
|---|---|
| `best/run.py` | 唯一正式命令入口。 |
| `best/algorithm/` | 視覺流程、幾何標定、球追蹤、串口與配置。逐文件作用見 `best/algorithm/README.md`。 |
| `ball_detection_common/` | 檢測資料型別、圓擬合與原套件的基礎功能。 |
| `ball_detection_runtime/` | 正式自適應檢測器和 HailoRT 後端。 |
| `best/debug_page/` | `--debug-page` 的 Web 頁面。 |
| `best/WIFI_test/` | `--wifi-stream` 的 MJPEG 串流；名稱沿用現行導入路徑，並非另開相機的測試程式。 |
| `requirements-runtime.txt`、`RUNTIME_ENVIRONMENT_RASPBERRY_PI.txt` | 已驗證樹莓派環境的版本與模組來源記錄；前者不是可直接執行的跨平台 `pip install -r` 清單。 |

各個目錄的載入關係和留存理由見 `PROJECT_STRUCTURE.md`；原始鏡像、重命名及校驗證據見 `PROVENANCE.md`。

## 正式啟動

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

`config.toml` 只保留這條命令讀取的六個分組。這次整理沒有修改 `run.py`、推理、bbox 球心、RANSAC、追蹤、串口、HEF 或標定 JSON，也沒有上傳到樹莓派。

## 標定待核對

目前本地運行包與樹莓派現行正式工作區一致，仍使用九樣本的標定 JSON；另一份含 12°的十樣本 JSON 已找到，但其 `geometry_id` 與現行訓練資料不同。此事記錄於 Support 根目錄 README，未自動提升為 active。
