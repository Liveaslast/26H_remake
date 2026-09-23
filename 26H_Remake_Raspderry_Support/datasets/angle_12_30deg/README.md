# 12–30°視覺資料集

此目錄保存離線採集照片、標註與標定照片，不參與 `best/run.py` 正式運行。

```text
angle_12_30deg/
├─ raw/                 按角度保存原始照片
├─ calibration/         相機與梁體幾何標定照片
├─ annotations/         YOLO 或其他標註
├─ manifests/           每次採集的 CSV/JSON 清單
└─ README.md
```

`raw/` 下使用 `angle_12` 至 `angle_30`，每 1° 一個目錄；不要使用 `12-30` 這類無法直接排序的名稱。

建議圖片名：`YYYYMMDD_HHMMSS_mmm_frame000001.jpg`。

每次採集清單至少記錄：

- `timestamp_iso`
- `angle_deg`
- `image_path`
- `exposure`
- `gain`
- `purpose`（train、validation、camera_calibration、geometry_calibration）
- `notes`

原始照片只追加，不覆蓋。篩選、裁剪或標註結果放入其他子目錄，不直接修改 `raw/`。
