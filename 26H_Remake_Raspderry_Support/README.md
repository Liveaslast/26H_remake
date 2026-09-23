# 樹莓派採集與資料支援目錄

本目錄與 `26H_Remake_Raspderry` 正式運行包並列，避免採集照片、CSV 和工具污染可部署運行核心。

本地與樹莓派的對應關係：

```text
D:\26H-remake\26H_Remake_Raspderry\
    -> ~/vision_workspace/workspace/

D:\26H-remake\26H_Remake_Raspderry_Support\tools\
    -> ~/vision_workspace/tools/

D:\26H-remake\26H_Remake_Raspderry_Support\datasets\
    -> ~/vision_workspace/datasets/
```

不要把 `datasets` 放進 `workspace/best/algorithm`，也不要放入運行時的 `calibration_output`。

上傳命令由使用者手動執行：

```powershell
scp -r "D:\26H-remake\26H_Remake_Raspderry_Support\tools" "ikun@192.168.137.2:/home/ikun/vision_workspace/"
scp -r "D:\26H-remake\26H_Remake_Raspderry_Support\datasets" "ikun@192.168.137.2:/home/ikun/vision_workspace/"
```
