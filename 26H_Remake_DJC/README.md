# STM32｜狀態估計與控制

下位機接收樹莓派發送的球位置與有效標誌，結合電機／桿角度進行狀態估計和控制；Task1 的目標序列也在此工程中。樹莓派負責提供視覺坐標，不在上位機重複閉環控制。

| 目錄 | 職責 |
|---|---|
| `APP/inc`、`APP/src` | 通信、球狀態估計、電機任務與調試任務入口 |
| `UserLib/` | 鋼球控制器、電機控制器與任務參數 |
| `Devices/` | QD4310 電機設備封裝 |
| `Hardware/` | LED、串口等板級封裝 |
| `Core/`、`Drivers/`、`Middlewares/` | STM32 平台初始化、HAL 與中間件 |
| `CMakeLists.txt`、`CMakePresets.json`、`cmake/` | 工程構建配置 |

運行鏈路是 `CommunicationTask` 接收視覺包 → `BallStateTask` 估計球狀態 → `GimbalTask` 執行電機控制；`DebugTask` 從 USART6 提供命令與 5 ms CSV 診斷。`DebugCommand.h`、`VisionFrame.h` 定義對應的命令與視覺資料格式。Task1 和機械零點的操控由 Windows [Support 命令手冊](../26H_Remake_Support/Docs/COMMANDS.md)提供；CSV 各列見 [資料格式](../26H_Remake_Support/Docs/DATA_FORMAT.md)。

本 README 只導航代碼責任。固件編譯與燒錄由項目持有人完成，不在這裏提供可能與實際硬件環境不符的通用指令。
