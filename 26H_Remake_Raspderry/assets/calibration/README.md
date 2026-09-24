# 生效標定

**dynamic_calibration_12_30deg.json** 是正式 **best/run.py** 載入的標定文件；實際含 12、14、…、30°十個角度，來源 ROI 為 **(128,425,1141,121)**。每個樣本的四角點與位置映射係數已在 JSON 中，沒有另外製造點位 TXT。

Windows [Support 標定資料](../../../26H_Remake_Support/Data/Calibration/) 保留相同 JSON 的參考副本、十張來源圖和十張展開圖。重新標定應在連接實際相機與機構的樹莓派上完成；新結果先作為獨立資料驗證，不會自動替換本文件。來源與幾何 ID 見 [PROVENANCE.md](../../PROVENANCE.md)。
