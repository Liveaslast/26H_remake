# Vision 視覺資料工具

本目錄負責固定 ROI、幾何標定、訓練圖採集、bbox 標註、YOLO 資料集整理和訓練。它不替代 `26H_Remake_Raspderry/best/run.py`。

```text
Vision/
├─ APP/      可直接運行的工作入口
├─ Config/   工具參數與路徑
├─ Core/     標定、幾何和資料集實現
└─ IO/       相機、遙測與人工角度輸入
```

## APP 入口和執行平台

| 腳本 | 執行平台 | 應用 |
|---|---|---|
| `select_roi.py` | 樹莓派桌面 | 使用實際 USB 相機選取軌道原圖 ROI。 |
| `calibrate_geometry.py` | 樹莓派桌面 | 在實際機構上按角度和位置點選，生成動態透視標定 JSON。 |
| `capture_training_data.py` | 樹莓派 | 使用標定 JSON 展開 ROI，按角度和曝光採集 640×128 圖片。 |
| `annotate_ball.py` | Windows，或帶桌面的樹莓派 | 框選球 bbox，生成同名 YOLO TXT。大量標註推薦 Windows。 |
| `build_yolo_dataset.py` | Windows | 校驗圖片/標籤/geometry ID，拆分 train/val 並生成 `roi_ball.yaml`。 |
| `train_yolo.py` | Windows | 使用 Ultralytics 訓練 640×128 單類鋼球模型。 |
| `rename_dataset_files.py` | Windows | 成對改名預覽；默認不修改，`--apply` 才執行。 |

`APP/__init__.py` 只是套件標記。

## Config

| 文件 | 作用 |
|---|---|
| `vision_tools.toml` | 相機、ROI、標定、採集和訓練默認值。 |
| `config.py` | 讀取並校驗 TOML，再由命令行參數覆蓋。 |
| `paths.py` | Support、資料和模型的統一路徑。 |

`vision_tools.toml` 的標定默認角度為 12、14、16、18、20、22、24、26、28、30°；拍攝仍須按實際角度指定 `--angle-deg`。

## Core 和 IO

- `calibration.py`：標定 JSON、角度插值和透視映射。
- `calibration_workflow.py`、`calibration_ui.py`：標定流程和 OpenCV 點選界面。
- `geometry.py`：相機 ROI 和尺寸。
- `dataset.py`、`dataset_tools.py`：採集記錄、YOLO 標籤、校驗和資料集拆分。
- `camera_telemetry.py`：USB 相機和可選角度遙測。
- `manual_angle.py`：人工角度輸入，只用於標定/採集，不能用於正式閉環。

這些是 APP 依賴，不作為獨立入口。

## 樹莓派上的相機相關命令

```bash
cd ~/vision_workspace/26H_Remake_Support
source ~/vision_workspace/.venv/bin/activate

python3 Vision/APP/select_roi.py --camera /dev/video0

python3 Vision/APP/calibrate_geometry.py \
  --camera /dev/video0 \
  --angles 12,14,16,18,20,22,24,26,28,30 \
  --positions=-10,-5,0,5,10

python3 Vision/APP/capture_training_data.py \
  --calibration Data/Calibration/generated/dynamic_calibration_manual.json \
  --session angle_12deg_exp10 \
  --angle-deg 12 \
  --exposure-time-absolute 10
```

## Windows 上的離線命令

```powershell
cd D:\26H-remake\26H_Remake_Support
python Vision\APP\annotate_ball.py `
  --dataset-root Data\Training\Captures `
  --pattern "angle_*deg_exp10"
python Vision\APP\build_yolo_dataset.py --source Data\Training\Captures\angle_12deg_exp10
python Vision\APP\train_yolo.py
python Vision\APP\rename_dataset_files.py
```

PT 到 Hailo HEF 在本地虛擬機完成，暫不屬於本倉庫文檔範圍。詳細輸入輸出見 `../Docs/COMMANDS.md` 和 `../Docs/DATA_FORMAT.md`。

上面的資料集整理命令使用新拍攝且完成標註的會話。樹莓派和 Windows 之間的具體複製命令、每一步的輸出位置，見 `../Docs/COMMANDS.md`。
