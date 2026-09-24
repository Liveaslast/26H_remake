# Raspberry Pi｜正式視覺運行包

本工程部署到樹莓派 **/home/ikun/vision_workspace/workspace**。**best/run.py** 是唯一正式命令入口，調用 **ballbeam.app.main**；不另開第二套相機或識別流程。

| 位置 | 用途 |
|---|---|
| **ballbeam/app/** | 啟動、逐幀處理、BALL_STATE 發送 |
| **ballbeam/vision/** | 標定、追蹤、檢測與 HailoRT 後端 |
| **ballbeam/hardware/** | 相機、串口與角度遙測 |
| **ballbeam/interfaces/** | DebugPage 與 Wi-Fi MJPEG |
| **ballbeam/control/** | 來源代碼中的輔助邏輯；閉環控制在 STM32 |
| **config/runtime.toml** | 正式配置 |
| **assets/calibration/** | 生效的 12–30°標定 JSON |
| **assets/models/hailo/** | HEF 和模型 metadata |
| **tests/** | 不接設備的結構測試 |

模組與依賴見 [PROJECT_STRUCTURE.md](PROJECT_STRUCTURE.md)；原始文件映射與標定溯源見 [PROVENANCE.md](PROVENANCE.md)。資料製作和 CSV 工具在 Windows 的 [Support 工程](../26H_Remake_Support/README.md)，不是本包的運行依賴。

## 啟動

在樹莓派終端依序執行：

1. cd ~/vision_workspace/workspace
2. source ~/vision_workspace/.venv/bin/activate
3. python3 best/run.py --port /dev/ttyUSB0 --inference-backend hailort --debug-page --serial-read-timeout-ms 1 --wifi-stream --no-display

**(vision_ws)** 是提示符名稱，實際虛擬環境是 **~/vision_workspace/.venv**。生效 JSON 有 12、14、…、30°十個標定樣本，來源 ROI 為 **(128,425,1141,121)**。正式位置已實機啟動，12–14°視覺已觀察正常；補入 12°後尚未重新記錄 Task1 驗證。

## 部署檢查

下面四行都在**樹莓派終端**執行，不是在 Windows 或虛擬機。「包根目錄」就是 **/home/ikun/vision_workspace/workspace**；檢查所用的 **SHA256SUMS.txt** 和 **tests/** 都在這個目錄內。

1. cd /home/ikun/vision_workspace/workspace
2. source /home/ikun/vision_workspace/.venv/bin/activate
3. sha256sum -c SHA256SUMS.txt
4. python3 -B -m unittest discover -s tests -v

第 3 行核對這份部署包的文件是否與清單一致；第 4 行運行不接設備的測試，檢查模型、標定文件路徑、ROI 和十個角度樣本。兩者都不能代替相機、Hailo 與串口的實機測試。模型幾何 ID 的核對邊界見 [PROVENANCE.md](PROVENANCE.md)。
