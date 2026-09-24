# 26H Remake｜鋼球平衡系統

這個倉庫把「樹莓派視覺 → 下位機估計與控制 → 可重做的資料及診斷」分成三個責任明確的工程。第一次閱讀，按下表進入即可；不要把資料製作工具當成正式運行入口。

| 目錄 | 做甚麼 | 從哪裏開始 |
|---|---|
| [26H_Remake_Raspderry](26H_Remake_Raspderry/README.md) | 樹莓派正式視覺運行包：相機、動態標定展開、HailoRT、球坐標、串口與調試頁 | `best/run.py` |
| [26H_Remake_Support](26H_Remake_Support/README.md) | 標定、採圖、標註、訓練、CSV 採集與分析；保留可溯源的資料 | [工具索引](26H_Remake_Support/Docs/TOOL_INDEX.md) |
| [26H_Remake_DJC](26H_Remake_DJC/) | 下位機固件：接收球狀態、估計、電機控制與 Task1 | 工程內的固件入口與配置 |

## 一條鏈路

樹莓派實機選 ROI、標定、採圖 → Windows 框選 bbox、整理資料集與訓練 → 本地虛擬機將 PT 轉成 HEF（此步暫未收錄）→ 樹莓派以 HailoRT 運行 → 下位機接收球狀態並控制 → Windows 記錄與分析 CSV。具體平台、輸入輸出與命令見 [完整流程](26H_Remake_Support/Docs/PROJECT_WORKFLOW.md)及[命令手冊](26H_Remake_Support/Docs/COMMANDS.md)。

正式樹莓派命令只從 `~/vision_workspace/workspace` 啟動；把本地鏡像放在旁邊不會自動替換現行工作區：

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

## 復用時的邊界

- 相機與機構相關的 ROI、標定 JSON、HEF 及訓練資料必須成套核對；不能只憑「12–30°」檔名互換。當前未決的 12°幾何對齊問題見 [Support README](26H_Remake_Support/README.md#待處理12-標定與現行模型對齊)。
- `Support/Vision/APP` 是資料製作入口，`Support/Diagnostics/APP` 是測試入口，`Support/Data` 是資料；正式運行只依賴 Raspberry 包及樹莓派既有虛擬環境。
- 實機編譯/燒錄及 PT→HEF 轉換由項目持有人另行完成；本倉庫不把它們偽裝成可直接執行的步驟。

保留 2405 組 12–30°已標註樣本以便學習和復現。上傳前請按 [資料說明](26H_Remake_Support/Docs/DATA_FORMAT.md)核對內容、授權與倉庫容量；倉庫根目錄的原始鏡像備份和臨時下載不屬於正式工程。
