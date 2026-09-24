# STM32｜状态估计与控制

下位机接收树莓派发送的球位置与有效标志，结合电机／杆角度进行状态估计和控制；Task1 的目标序列也在此工程中。树莓派负责提供视觉坐标，不在上位机重复闭环控制。

| 目录 | 职责 |
|---|---|
| **APP/inc**、**APP/src** | 通信、球状态估计、电机任务与调试任务入口 |
| **UserLib/** | 钢球控制器、电机控制器与任务参数 |
| **Devices/** | QD4310 电机设备封装 |
| **Hardware/** | LED、串口等板级封装 |
| **Core/**、**Drivers/**、**Middlewares/** | STM32 平台初始化、HAL 与中间件 |
| **CMakeLists.txt**、**CMakePresets.json**、**cmake/** | 工程构建配置 |

运行链路是 **CommunicationTask** 接收视觉包 → **BallStateTask** 估计球状态 → **GimbalTask** 执行电机控制；**DebugTask** 从 USART6 提供命令与 5 ms CSV 诊断。**DebugCommand.h**、**VisionFrame.h** 定义对应的命令与视觉资料格式。Task1 和机械零点的操控由 Windows [Support 命令手册](../26H_Remake_Support/Docs/COMMANDS.md)提供；CSV 各列见 [资料格式](../26H_Remake_Support/Docs/DATA_FORMAT.md)。

本 README 只导航代码责任。固件编译与烧录由项目持有人完成，不在这里提供可能与实际硬件环境不符的通用指令。
