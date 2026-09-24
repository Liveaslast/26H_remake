# 12–30°鋼球檢測訓練資料

來源：`D:\26H-remake\_pi_raw\best\algorithm\no_m0\roi_dataset_128x640`。

- 相機曝光值：10
- 角度組：12、14、16、18、20、22、24、26、28、30°
- 訓練圖片：2405 張 PNG，尺寸 640×128
- YOLO 標註：2405 個 TXT，與圖片檔名一一配對
- 類別：`0 steel_ball`

每行標註格式為 `class_id center_x center_y width height`，四個浮點數是歸一化的中心座標和框寬高，不是四個頂點座標。

`by_angle/<angle>/images` 與 `labels` 是實際訓練對；`source_records` 保留原始采集 session 和逐幀 metadata，用於溯源。metadata 也記錄了原始未標註圖及中間圖路徑，但那些文件未混入本訓練資料集。

`Vision/APP/build_yolo_dataset.py` 可直接讀取這十個 `by_angle/angle_*` 目錄：若根目錄沒有 `session.json`，就從 `source_records/capture_session.json` 取得原有 `geometry_id`，不修改封存資料。已逐一校驗 2405 組圖片/標註和單一幾何 ID；這只證明資料格式一致，**不表示**它與目前生效的十樣本標定或 HEF 自動匹配。完整命令見 `../../../Docs/COMMANDS.md`。

原圖是在連接實際相機與機構的樹莓派上採集；框選、資料集整理和 YOLO 訓練在 Windows 完成。正式樹莓派進程不讀取本目錄，而是載入已編譯的 `best.hef`。
