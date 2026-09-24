# 標定資料

此目錄只保存正式運行載入的標定結果。

`dynamic_calibration_12_30deg.json` 是 `best/run.py` 正式命令實際載入的標定文件。它的 `samples` 確實包含 12、14、…、30°十個角度；不是只有檔名寫 12–30°。來源 ROI 為 `(128,425,1141,121)`。

JSON 的 `samples` 內已保存各角度的 `source_corners_px` 與 `position_mapping`；透視與幾何資訊也在同一 JSON 中。原始來源沒有獨立的點位 TXT，因此沒有額外製造一份可能與正式 JSON 不一致的文件。

標定時的來源圖和展開圖位於 Windows 本地 `26H_Remake_Support/Data/Calibration/angle_12_30deg`。重新標定必須在連接實際相機與機構的樹莓派上完成；產出的新 JSON 先在獨立測試目錄核對角度、ROI 和實機圖像，確認後才更新本文件。不要將 Support 的資料採集輸出直接當作正式進程生效配置。
