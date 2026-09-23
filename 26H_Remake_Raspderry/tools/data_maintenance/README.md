# 視覺資料命名工具

`rename_visual_assets.py` 只處理已整理出的標定照片、訓練圖片和配對標註，不修改 Python 視覺算法、Hailo 模型、標定 JSON 或控制配置。

先預覽：

```powershell
python tools/data_maintenance/rename_visual_assets.py
```

確認預覽後執行：

```powershell
python tools/data_maintenance/rename_visual_assets.py --apply
```

執行時會生成 `VISUAL_ASSET_RENAME_MANIFEST.csv`，記錄每個文件的原名稱、新名稱和改名前 SHA-256；原始 `source_records` 不改寫。完成後會自動核對 2405 組圖片/標註並重建頂層 `SHA256SUMS.txt`。
