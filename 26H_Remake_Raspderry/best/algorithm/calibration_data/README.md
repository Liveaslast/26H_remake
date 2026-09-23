# 標定資料

此目錄把「正式運行載入的結果」和「生成結果時使用的照片」分開保存。

## active

`active/roi_128x640/dynamic_calibration_12_30deg.json` 是 `best/run.py` 正式命令實際載入的標定文件。

JSON 的 `samples` 內已保存各角度的 `source_corners_px` 與 `position_mapping`；透視與幾何資訊也在同一 JSON 中。原始來源沒有獨立的點位 TXT，因此沒有額外製造一份可能與正式 JSON 不一致的文件。

## source_capture

`source_capture/angle_12_30deg/source_images` 保存相機粗 ROI 標定照片；`rectified_images` 保存對應的展開結果。兩者只用於人工核對及日後重建標定，不被正式運行進程讀取。
