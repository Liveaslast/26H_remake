# 26H Remake Support

本目錄只保存「資料製作、離線分析與測試」內容，與正式工程並列：

- `26H_Remake_DJC`：下位機正式工程。
- `26H_Remake_Raspderry`：樹莓派正式運行鏡像；部署後由 `~/vision_workspace/workspace/best/run.py` 啟動。
- `26H_Remake_Support`：本目錄，不參與正式啟動。

```text
26H_Remake_Support/
├─ Data/
│  ├─ Calibration/   標定成品、來源圖與展開圖
│  ├─ Training/      12–30° YOLO 圖片及同名標籤
│  └─ TestRecords/   視覺和控制測試 CSV
├─ Vision/
│  ├─ APP/           可直接執行的 ROI、標定、採集、框選及訓練入口
│  ├─ Core/          APP 共用的標定與資料集邏輯
│  ├─ IO/            相機、遙測及人工角度輸入
│  └─ Config/        工具配置與路徑
├─ Diagnostics/
│  ├─ APP/           CSV 採集、Task1 測試與分析入口
│  ├─ Core/          測試入口的共用實現
│  └─ IO/            串口鏈路檢查
└─ Docs/             命令、資料格式及來源溯源
```

整條項目鏈見 `Docs/PROJECT_WORKFLOW.md`，分平台命令見 `Docs/COMMANDS.md`，來源與取捨見 `Docs/PROVENANCE.md`。

## 原則

1. 正式運行代碼只在 `26H_Remake_Raspderry` 維護；Support 不覆蓋它。
2. 原始採集紀錄保留原路徑與原模式名，用於真實溯源，不做粉飾性改寫。
3. 圖片和標籤始終同名成對；批量改名工具默認只預覽。
4. `Data/Calibration/active` 中的 JSON 是正式標定文件的參考副本，不是另一份運行入口。
5. ROI 選取、幾何標定和實機圖像採集在樹莓派執行；Windows 負責標註、資料整理、訓練和 CSV 分析。
6. PT 到 Hailo HEF 在本地虛擬機完成，暫不在本倉庫展開。
