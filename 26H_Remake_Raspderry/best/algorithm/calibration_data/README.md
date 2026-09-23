# 標定資料

此目錄只保存正式運行載入的標定結果。

## active

`active/roi_128x640/dynamic_calibration_12_30deg.json` 是 `best/run.py` 正式命令實際載入的標定文件。

JSON 的 `samples` 內已保存各角度的 `source_corners_px` 與 `position_mapping`；透視與幾何資訊也在同一 JSON 中。原始來源沒有獨立的點位 TXT，因此沒有額外製造一份可能與正式 JSON 不一致的文件。

標定時的來源圖和展開圖位於本地 `26H_Remake_Support/Data/Calibration/angle_12_30deg`。重新標定必須在連接實際相機與機構的樹莓派上完成；新 JSON 經核對後才可替換本目錄的 active 文件。
