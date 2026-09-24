# Vision｜視覺資料工具

這些腳本製作 ROI、標定與 YOLO 資料；不替代樹莓派正式 **best/run.py**。Windows 保存完整 Support，樹莓派需要採圖時才按 [命令手冊](../Docs/COMMANDS.md)部署 **Vision/**。

| **APP/** 入口 | 執行位置 | 輸入 → 結果 |
|---|---|---|
| **select_roi.py** | 樹莓派桌面 | USB 相機 → ROI 數值與預覽圖 |
| **calibrate_geometry.py** | 樹莓派桌面 | 角度、軌道角點及位置點 → 動態標定 JSON／檢查圖 |
| **capture_training_data.py** | 樹莓派 | 生效 JSON、相機、角度 → 640×128 圖片及會話記錄 |
| **annotate_ball.py** | Windows／樹莓派桌面 | 未標註圖片 → 同名 YOLO bbox TXT |
| **build_yolo_dataset.py** | Windows | 已標註會話 → train/val、**roi_ball.yaml** |
| **train_yolo.py** | Windows | 資料集與基礎 PT → **Data/Training/Models/best.pt** |
| **rename_dataset_files.py** | Windows | 成對改名預覽；只有 **--apply** 才修改 |

**Config/vision_tools.toml** 保存工具默認值；**Config/config.py** 校驗配置，**Config/paths.py** 統一路徑。**Core/** 實現幾何、採集與資料集流程，**IO/** 提供相機、遙測和人工角度輸入；它們不是獨立入口。

工具默認標定角度為 12、14、…、30°，相機來源 ROI 與正式 JSON 一致。人工角度輸入只用於標定／採圖，不進入正式閉環。實際命令、文件位置及 SCP 見 [COMMANDS.md](../Docs/COMMANDS.md)；資料和標註格式見 [DATA_FORMAT.md](../Docs/DATA_FORMAT.md)。

模型存放規則見 [Data/Training/Models/README.md](../Data/Training/Models/README.md)：PT 是訓練產物，HEF 才是樹莓派 HailoRT 的正式輸入；不要因為原始工程另有 NCNN 模型，就把它當作這條正式鏈路的必要文件。
