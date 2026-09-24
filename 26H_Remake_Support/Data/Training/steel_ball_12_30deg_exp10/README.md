# 12–30°鋼球 YOLO 資料

`by_angle/angle_*` 分成 12、14、…、30°十組，共 2405 張 640×128 PNG 和 2405 個同名標籤；採集曝光值為 10，類別是 `0 steel_ball`。

| 位置 | 內容 |
|---|---|
| `by_angle/<角度>/images/` | 已選用的訓練圖片 |
| `by_angle/<角度>/labels/` | 同名 YOLO TXT，每行 `class_id center_x center_y width height`，座標歸一化 |
| `by_angle/<角度>/source_records/` | 原始會話與逐幀 metadata，用於溯源，不回寫 |

TXT 保存 bbox 的中心與寬高，並非四個頂點。資料由樹莓派採集、在 Windows 標註；正式 Pi 視覺只載入已編譯的 HEF，不讀這些 PNG／TXT。

`Vision/APP/build_yolo_dataset.py` 可直接把各個 `by_angle/angle_*` 目錄作為 `--source`。腳本優先讀會話根目錄的 `session.json`，否則讀封存的 `source_records/capture_session.json`；既有採集記錄的 geometry ID 保持原樣。2405 組配對與內部幾何一致性已核對，但這不等於模型與現行十樣本 JSON 能靠 ID 自動匹配。命令見 [COMMANDS.md](../../../Docs/COMMANDS.md)，來源見 [PROVENANCE.md](../../../Docs/PROVENANCE.md)。
