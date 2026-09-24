# Diagnostics｜採集與分析

診斷工具在正式視覺之外採集和分析數據，不改識別或下位機控制邏輯。Windows 執行串口採集和離線分析；Pi 的 vision probe 使用同一正式 **best/run.py**，額外寫逐幀 CSV。

| **APP/** 入口 | 平台 | 用途 |
|---|---|---|
| **capture_mcu_csv.py** | Windows | 採集 USART6 的 **vision** 或 **control** 行，附主機時間 |
| **capture_vision_csv.sh** | 樹莓派，按需部署 | 啟動正式視覺並打開 probe；也可直接使用命令手冊的正式命令 |
| **analyze_vision_probe.py** | Windows | 單份 probe 的幀率、valid、更新間隔與座標事件 |
| **analyze_vision.py** | Windows | 對齊 Pi probe 與 STM32 vision CSV |
| **initialize_zero.py** | Windows | 發送 **task init** 設定下位機零點 |
| **run_task1.py**、**analyze_task1.py** | Windows | 啟動／記錄及分析 Task1 |

**capture_mcu_csv.py** 的 **--mode** 決定是否順便發 **ba 22**／**task 1**；**--firmware-csv** 決定下位機打印 **vision**、**control** 或關閉。兩者互不等價。固件啟動默認為 **control**；切到 **vision** 後，Task1 前要切回 **control**。

**control** 與 **vision** 固件 CSV 均按 5 ms 打印。probe 則是樹莓派每處理完一幀所寫的觀測，記錄耗時、bbox／球位置、valid 與角度；它不是串口收包，也不表示逐幀發包。比較 probe、下位機 vision 與 control，才能區分識別、傳輸和控制端的問題。

完整命令見 [COMMANDS.md](../Docs/COMMANDS.md)，逐列定義見 [DATA_FORMAT.md](../Docs/DATA_FORMAT.md)。**Core/** 和 **IO/** 是入口依賴，不直接運行。清理後 **~/vision_workspace/diagnostics** 可在下次 probe 採集前重新建立。
