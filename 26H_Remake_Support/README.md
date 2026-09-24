# Support｜資料製作與測試

Support 是 Windows 上的可復用工具與資料庫，不參與樹莓派正式視覺進程。正式運行包是同級 [26H_Remake_Raspderry](../26H_Remake_Raspderry/README.md)；下位機代碼在 [26H_Remake_DJC](../26H_Remake_DJC/)。

```text
Vision/APP/           ROI、標定、採圖、框選、資料集整理與訓練入口
Vision/{Config,Core,IO}/  上述入口的配置與實現
Diagnostics/APP/      CSV 採集、Task1 測試與分析入口
Diagnostics/{Core,IO}/  診斷入口的實現
Data/Calibration/     生效標定參考副本、來源圖與展開圖
Data/Training/        12–30°圖片、YOLO 標籤和採集記錄
Data/TestRecords/     視覺／控制測試 CSV
Docs/                 命令、字段、流程與來源
```

要找工具，先看 [TOOL_INDEX.md](Docs/TOOL_INDEX.md)；按步操作看 [COMMANDS.md](Docs/COMMANDS.md)，完整鏈路看 [PROJECT_WORKFLOW.md](Docs/PROJECT_WORKFLOW.md)，字段看 [DATA_FORMAT.md](Docs/DATA_FORMAT.md)。

## 資料與部署邊界

- 正式標定在樹莓派 `~/vision_workspace/workspace/assets/calibration/dynamic_calibration_12_30deg.json`；本目錄 `Data/Calibration/active` 是內容相同的 Windows 參考副本。JSON 實際包含 12、14、…、30°十個樣本。
- `Data/Training/steel_ball_12_30deg_exp10` 封存 2405 組 640×128 圖片與同名 YOLO 標籤。原始 `capture_session.json` 保留採集時的幾何 ID，不為匹配現行 JSON 而改寫。
- 需要在樹莓派重新選 ROI、標定或拍攝時，從 Windows 按需部署 `Vision/`；平時正式運行只需 `workspace`、頂層 `.venv` 及設備／驅動。
- PT→HEF 在本地虛擬機完成；固件編譯和燒錄由項目持有人完成，這兩步不在 Support 腳本中。

來源文件及整理取捨見 [PROVENANCE.md](Docs/PROVENANCE.md)。
