# 模型訓練產物

這裡保存 Windows 訓練所得的 PyTorch 權重，不參與樹莓派正式運行。

| 文件或目錄 | 用途 |
|---|---|
| **best.pt** | 最佳訓練權重；交給本地虛擬機轉成 HEF |
| **best.pt.geometry.json** | 新版訓練腳本生成的幾何旁車文件；現有舊 PT 沒有，勿臆造 |
| **last.pt** | 下次訓練生成時保存最後一輪權重；目前沒有 |
| **Runs/** | 下次訓練生成的日誌與結果 |
| **ncnn_model/** | 僅在實際導出、測試 NCNN 時才建立 |

現有 **best.pt** 複製自 **D:\Linux_system\VM_share\best.pt**，其內部訓練資料路徑指向 **roi_ball_128x640_angle12/roi_ball.yaml**。舊鏡像 NCNN 部署記錄也指向該資料集，其 **geometry_id** 為 **b5db7d68…74de5ad**；這是來源線索，並非從此 PT 直接讀到的 ID。現行樹莓派標定 ID 不同，不要為消除警告而補寫不實的模型幾何 ID。

轉換完成的正式模型位於兄弟工程 **26H_Remake_Raspderry/assets/models/hailo/best.hef**。樹莓派正式工作空間只需要 HEF，不需要這裡的 PT、訓練日誌或 NCNN。
