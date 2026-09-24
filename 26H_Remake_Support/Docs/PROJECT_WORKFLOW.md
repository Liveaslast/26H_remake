# 從 ROI 到 Task1

| 階段 | 執行位置 | 輸入 → 產出 |
|---|---|---|
| ROI 與幾何標定 | 樹莓派桌面，按需部署 **Vision/** | 實際相機、12–30°角度與點選位置 → 動態標定 JSON／檢查圖 |
| 訓練圖片採集 | 樹莓派 | 生效 JSON、實際機構 → 640×128 會話圖片與 metadata |
| 框選、整理、訓練 | Windows Support | 圖片 → 同名 YOLO bbox TXT → train/val → **best.pt** |
| PT→HEF | 本地虛擬機 | 編譯與模型配置；此倉庫不提供轉換命令 |
| 正式視覺 | 樹莓派 **~/vision_workspace/workspace** | 相機＋角度遙測 → Hailo 識別 → 球位置與 valid → STM32 |
| 估計、控制與 Task1 | STM32 | 球狀態 → 電機控制；Task1 由下位機狀態機執行 |
| 採集與分析 | Windows，必要時配合 Pi probe | 5 ms MCU CSV＋逐幀 probe → 延遲、valid、座標與控制分析 |

全部可執行命令、SCP 和文件落點集中在 [COMMANDS.md](COMMANDS.md)；各個工具按 [TOOL_INDEX.md](TOOL_INDEX.md) 尋找，字段見 [DATA_FORMAT.md](DATA_FORMAT.md)。固件編譯與燒錄由項目持有人完成。

## 現行系統的責任

正式視覺按下位機回傳的實際桿角度，從十樣本 12–30° JSON 動態透視展開；使用 HailoRT 每幀識別，以 bbox 球心形成厘米坐標，不啟用霍夫圓或樹莓派 Kalman。來源中的 RANSAC refinement 可執行，但正式坐標仍取 bbox。樹莓派把位置與 valid 發給 STM32；狀態估計、電機和 Task1 控制在 STM32。

正式包與工具包分離：樹莓派常駐 **workspace** 和頂層 **.venv**，不需要長期保留 Support、訓練圖或舊視覺工作區。Windows Support 保存標定、訓練與測試資料，以便重做鏈路。
