# 26H_Remake｜鋼球平衡系統

相機在樹莓派上產生球坐標，STM32 接收後估計狀態、控制電機，Windows 工具負責資料製作與測試記錄。三部分分開維護，正式運行不依賴訓練圖片或診斷腳本。

| 工程 | 職責 | 閱讀入口 |
|---|---|---|
| [26H_Remake_Raspderry](26H_Remake_Raspderry/README.md) | 樹莓派相機、12–30°動態標定、HailoRT 識別、串口發送小球坐標與速度 | [運行架構](26H_Remake_Raspderry/PROJECT_STRUCTURE.md) |
| [26H_Remake_DJC](26H_Remake_DJC/README.md) | STM32 α-β濾波、電機控制、回傳電機角度 | [下位機模組導航](26H_Remake_DJC/README.md)；編譯與燒錄由項目持有人完成 |
| [26H_Remake_Support](26H_Remake_Support/README.md) | ROI／標定／訓練資料製作，以及 CSV 採集與分析 | [工具索引](26H_Remake_Support/Docs/TOOL_INDEX.md) |

## 運行

樹莓派正式部署目錄是 `/home/ikun/vision_workspace/workspace`，Python 虛擬環境獨立位於 `/home/ikun/vision_workspace/.venv`。`(vision_ws)` 只是終端提示名稱。

在樹莓派終端依序執行以下三行：

1. cd ~/vision_workspace/workspace
2. source ~/vision_workspace/.venv/bin/activate
3. python3 best/run.py --port /dev/ttyUSB0 --inference-backend hailort --debug-page --serial-read-timeout-ms 1 --wifi-stream --no-display

模型缺少可自動核對幾何 ID 的 `deployment.json`；詳見 [來源與驗證邊界](26H_Remake_Raspderry/PROVENANCE.md)。

## 按任務閱讀

- 從 ROI、採圖走到模型與 Task1：[完整流程](26H_Remake_Support/Docs/PROJECT_WORKFLOW.md)。
- 執行命令、平台和輸出路徑：[命令手冊](26H_Remake_Support/Docs/COMMANDS.md)。
- CSV 每列的含義：[資料格式](26H_Remake_Support/Docs/DATA_FORMAT.md)。
- 想復用架構：先看兩個工程 [26H_Remake_Raspderry] 、 [26H_Remake_DJC]的 README，再按新機構替換 ROI、標定、模型及串口配置；不要把本機構的 JSON／HEF 直接當通用模板。

PT→HEF 在本地虛擬機完成，本倉庫不提供該步命令。固件編譯與燒錄也由項目持有人完成。Windows Support 保存 2405 組 12–30°已標註圖片及可追溯的標定資料；樹莓派正式運行不需要這些原始資料。
