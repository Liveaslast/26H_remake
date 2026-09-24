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

先從 `Docs/TOOL_INDEX.md` 按任務找腳本；整條項目鏈見 `Docs/PROJECT_WORKFLOW.md`，分平台命令見 `Docs/COMMANDS.md`，資料及 CSV 字段見 `Docs/DATA_FORMAT.md`，來源與取捨見 `Docs/PROVENANCE.md`。

## 原則

1. 正式運行代碼只在 `26H_Remake_Raspderry` 維護；Support 不覆蓋它。
2. 原始採集紀錄保留原路徑與原模式名，用於真實溯源，不做粉飾性改寫。
3. 圖片和標籤始終同名成對；批量改名工具默認只預覽。
4. `Data/Calibration/active` 中的 JSON 是正式標定文件的參考副本，不是另一份運行入口。
5. ROI 選取、幾何標定和實機圖像採集在樹莓派執行；Windows 負責標註、資料整理、訓練和 CSV 分析。
6. PT 到 Hailo HEF 在本地虛擬機完成，暫不在本倉庫展開。

## 待處理：12° 標定與現行模型對齊

2026-09-24 核對樹莓派原始文件後確認：

- 完整標定位於樹莓派 `/home/ikun/vision_workspace/workspace_26h_remake/calibration/output/roi_128x640/dynamic_calibration.json`，含 12、14、…、30° 十個實測樣本，`geometry_id=8a5cd731dad6021704fb36f25fd423fa7ecd1634c998e23d7eaf9b13ff81126f`。本地只讀候選副本是 `D:\26H-remake\calibration_complete_12_30.json`。
- 樹莓派目前正式工作區使用的 `best/algorithm/no_m0/calibration_output/roi_128x640/dynamic_calibration_no_m0.json`、本地 Raspberry 鏡像及 Support 的 `Data/Calibration/active` 仍是 14–30°九樣本，`geometry_id=b5db7d686fc483d125f523499dbbdb9bc71a2d9a2b7f9709992a53b8174de5ad`。新版除新增 12°外，原有九個樣本逐項相同。
- 現存 2405 組訓練資料（含 12°組）的 `capture_session.json` 記錄舊 `geometry_id=b5db…`；只替換正式 JSON 會改變 12–14°的展開輸入，不能假定現有 HEF 與它完全對齊。
- 樹莓派現行 `config.toml` 和本地 Raspberry 鏡像的粗 ROI 均為 `(129,422,1143,124)`，兩份標定 JSON 記錄 `(128,425,1141,121)`。實機目前能運行的原因尚需對照實際啟動參數和運行路徑，不要按推測修改配置。

**目前決定：保持樹莓派現行工作區、本地正式鏡像的 active JSON、模型及視覺參數不變。**本地運行鏡像可整理不參與正式命令的文檔與配置分組。有空時先核實現行命令究竟讀取哪份配置、對比 12–14°的圖像效果及訓練幾何，再決定是否把完整標定提升為 active；不得僅憑檔名直接覆蓋。
