# 標定照片

```text
calibration/
├─ camera_intrinsics/   棋盤格或標定板原圖
├─ beam_geometry/       梁體在 12–30°的幾何標定圖
└─ roi_reference/       ROI 邊界與安裝位置參考圖
```

標定輸出 JSON 另行生成；不要用本目錄覆蓋正式運行使用的 `best/algorithm/no_m0/calibration_output`。
