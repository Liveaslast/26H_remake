# 26H Remake Support

本目錄只保存「資料製作、離線分析與測試」內容，與正式工程並列。Windows 本地完整保存 Support；樹莓派正式視覺只需 `/home/ikun/vision_workspace/workspace` 和頂層 `.venv`，**不依賴樹莓派上長期存放 Support**。需要重新拍攝 ROI、標定或訓練圖片時，再把 `Vision/` 工具部署到樹莓派。

- `26H_Remake_DJC`：下位機正式工程。
- `26H_Remake_Raspderry`：樹莓派正式運行鏡像；2026-09-24 已由使用者部署到 `~/vision_workspace/workspace`，由 `best/run.py` 啟動。
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

## 生效 12–30° 標定與實機核對

2026-09-24 核對並更新本地鏡像，後由使用者部署、實機驗證：

- 完整標定原先取自樹莓派 `/home/ikun/vision_workspace/workspace_26h_remake/calibration/output/roi_128x640/dynamic_calibration.json`；舊目錄可清理，生效副本現於正式 `~/vision_workspace/workspace/assets/calibration/dynamic_calibration_12_30deg.json`，Windows Support 保有 `Data/Calibration/active/dynamic_calibration_12_30deg.json`。含 12、14、…、30° 十個實測樣本，`geometry_id=8a5cd731dad6021704fb36f25fd423fa7ecd1634c998e23d7eaf9b13ff81126f`。
- 此前九樣本版本的 `geometry_id=b5db7d686fc483d125f523499dbbdb9bc71a2d9a2b7f9709992a53b8174de5ad`。新舊 JSON 的粗 ROI 及 14–30°九個樣本相同；新 JSON 在 12°真正選取 12°樣本，12–14°之間按兩個樣本插值。
- Windows 封存的 2405 組訓練資料（含 12°組）的 `capture_session.json` 仍記錄舊幾何 ID；HEF 未重新編譯，模型缺少 `deployment.json`，無法自動核對。使用者已在樹莓派測試工作區實測 12–14°視覺正常，正式 `workspace` 視覺亦正常；補標定後未重跑 Task1。
- 舊樹莓派工作區 TOML 的粗 ROI 是 `(129,422,1143,124)`，標定 JSON 記錄 `(128,425,1141,121)`。舊代碼相等檢查錯放於 `return` 後，實際裁切始終使用 JSON ROI；新版正式 `workspace` 的 TOML 已與 JSON 對齊並恢復檢查。

正式工作區與支持工具分開管理：原始標定、訓練圖和歷史 CSV 的可復用副本在 Windows 本目錄；樹莓派上的舊工作區或臨時 Support 副本不是正式視覺運行條件。實機操作與數據回收見 `Docs/COMMANDS.md`。
