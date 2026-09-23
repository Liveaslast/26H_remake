# 項目完整鏈路

```text
樹莓派實機 ROI/標定/採集
→ Windows bbox 標註、資料集整理與 YOLO 訓練
→ 本地虛擬機把 PT 轉成 Hailo HEF
→ 樹莓派 HailoRT 正式視覺
→ STM32 接收球狀態並完成估計與控制
→ Task1：必要時先回 0，再執行 0 → +5 → -5
```

## 工程邊界

- `26H_Remake_Support`：資料、標定/採集/訓練工具和 CSV 診斷。
- `26H_Remake_Raspderry`：部署到 `~/vision_workspace/workspace` 的正式視覺閉包。
- `26H_Remake_DJC`：下位機固件、狀態估計、電機控制與 Task1 狀態機。

## 資料鏈

1. 在樹莓派桌面用實際 `/dev/video0` 選 ROI。
2. 在實際機構上完整採集 12、14、16、18、20、22、24、26、28、30°標定樣本，生成 12–30°動態透視 JSON。現有歷史 JSON 缺少 12°樣本只作溯源記錄，不作新標定規範。
3. 在樹莓派以曝光值 10 採集 12、14、16、18、20、22、24、26、28、30°的 640×128 ROI。
4. 在 Windows 框選球 bbox；標籤格式是歸一化 `class center_x center_y width height`。
5. 對新採集、已標註的會話，校驗 geometry ID 和圖片/標籤配對，生成 train/val 和 `roi_ball.yaml`。
6. Windows 訓練輸出 `Data/Training/Models/best.pt`。
7. **記號：PT→HEF 在本地虛擬機完成，暫不關注且不在本倉庫展開命令。**輸出應為匹配的 `best.hef` 和 `metadata.yaml`。

## 正式視覺鏈

樹莓派只從 `~/vision_workspace/workspace` 啟動：

```bash
cd ~/vision_workspace/workspace
source ~/vision_workspace/.venv/bin/activate
python3 best/run.py \
  --port /dev/ttyUSB0 \
  --inference-backend hailort \
  --debug-page \
  --serial-read-timeout-ms 1 \
  --wifi-stream \
  --no-display
```

相機幀經固定 ROI、按下位機實際角度動態透視展開、640×128 Hailo 推理後，以 YOLO bbox 中心得到厘米位置。正式配置每幀推理、不使用霍夫圓、不啟用樹莓派 Kalman；RANSAC refinement 可能執行，但正式位置來源仍是 bbox。

## 上下位機責任

- 樹莓派負責相機、標定展開、Hailo 識別、球坐標和 valid。
- STM32 回傳實際角度供樹莓派選擇標定，並接收球狀態完成估計和電機控制。
- Task1 狀態機和參數屬於 STM32；Windows 只啟動、停止和記錄。

## Task1

MCU 復位或機械零點改變後，在 Windows 執行一次：

```powershell
cd D:\26H-remake\26H_Remake_Support
python Diagnostics\APP\initialize_zero.py --port COM26
```

啟動樹莓派正式視覺，並確保下位機 CSV 已處於 `control`，再執行：

```powershell
$task1Csv = "Data\TestRecords\task1_$(Get-Date -Format yyyyMMdd_HHmmss).csv"
python Diagnostics\APP\run_task1.py --port COM26 --output $task1Csv
python Diagnostics\APP\analyze_task1.py $task1Csv
```

`run_task1.py` 只發 `task 1`。如果球不在 0 附近，下位機先回到既有零點，再執行 +5 和 -5，退出時接收 `task stop`。

更細的設備命令見 `COMMANDS.md`，CSV 含義見 `DATA_FORMAT.md`。
