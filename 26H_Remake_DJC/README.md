# STM32｜状态估计与控制

球速阶跃统一使用 `task 1`，带符号目标速度由 Pi 启动参数手动指定，绝对值 1–5 cm/s；初始化使用 task 0（携带非零请求号）。Pi 先用 0x06/0x86 确认调参模式，再通过周期 39 字节 0x08 提供视觉、测试指令和 PID/目标速度；参数和任务的执行结果随 0x85 返回，不另发命令 ACK。阶跃期间目标球速恒定，不由位置误差生成，不设置制动阶段；估计位置沿目标方向到达 `+6/−6 cm` 时回平衡角。反方向边界、高速、视觉异常和 8 s 超时只作为保护。回平衡角不是主动刹停。过程使用 44 字节 0x85 调参遥测；Task1 双环参数不由此包修改。详见 [Pi README](../26H_Remake_Raspderry/README.md#固定球速短行程测试本地代码需配套固件)。当前为本地实现，尚未同步、烧录或实机验证。

下位机接收树莓派发送的球位置与有效标志，结合电机／杆角度进行状态估计和控制；Task1 的目标序列也在此工程中。树莓派负责提供视觉坐标，不在上位机重复闭环控制。

| 目录 | 职责 |
|---|---|
| **APP/inc**、**APP/src** | 通信、球状态估计、电机任务与调试任务入口 |
| **UserLib/** | 钢球控制器、电机控制器与任务参数 |
| **Devices/** | QD4310 电机设备封装 |
| **Hardware/** | LED、串口等板级封装 |
| **Core/**、**Drivers/**、**Middlewares/** | STM32 平台初始化、HAL 与中间件 |
| **CMakeLists.txt**、**CMakePresets.json**、**cmake/** | 工程构建配置 |

运行链路是 **CommunicationTask** 接收视觉包 → **BallStateTask** 估计球状态 → **GimbalTask** 执行电机控制；**DebugTask** 从 USART6 提供命令与 5 ms CSV 诊断。**DebugCommand.h**、**VisionFrame.h** 定义对应的命令与视觉资料格式。Task1、机械零点和数据分析见 Windows [Support README](../26H_Remake_Support/README.md)；CSV 各列见 [资料格式](../26H_Remake_Support/Docs/DATA_FORMAT.md)。

Task1 默认参数在 `UserLib/BallBeamTaskProfile.h`。当前使用位置→速度双环：位置环根据位置误差生成限幅目标速度，速度环根据速度误差生成限幅角度修正。默认位置 `Kp=1.2, Ki=0, Kd=0`；默认速度 `Kp=0.5, Ki=1.2, Kd=0`，其中 Task1 速度积分仍受原有位置/速度门控、泄放与抗饱和约束。调试串口显式下发新参数时，位置 I/D 和速度 D 才参与计算；速度阶跃与 Task1 共用下发的速度 PID 参数，但两种运行模式的积分门控策略不同。平衡角默认 21°，位置目标生成的速度限幅 ±6 cm/s，总角度修正限幅 ±8°，外环周期 20 ms。旧 BBP/BPUSH 控制分支已从控制更新路径移除；原诊断帧字段仍保留并填 0，以兼容现有 CSV 解析。

## 两模式通信

0x06 请求模式，0x86 回应模式选择（0 成功，1 失败），确认后才发送对应周期数据。运行模式固定 0x07/0x84，调参模式固定 0x08/0x85。独立 0x09 和通用命令 ACK 已移除。切换时若旧球任务正在运行，停止旧任务并回平衡角；否则保留当前电机目标。模式确认不代表机械动作已稳定，也不会启动新的运动任务。

| 帧 | 长度 | 内容 |
|---|---:|---|
| 0x06 | 6 | A5 06 seq16 mode CRC |
| 0x86 | 7 | 5A 86 seq16 mode result CRC |
| 0x07 | 21 | 运行模式的视觉数据、任务 ID、任务请求号 |
| 0x08 | 39 | 调参模式的视觉、测试指令、PID/目标速度和参数版本 |
| 0x84 | 42 | 任务控制遥测、任务执行结果，20 ms |
| 0x85 | 44 | 调参控制遥测、任务结果、参数应用结果，5 ms |

mode 1=任务，2=调参。两种模式均用 task 0 初始化；运行模式登记 task 1=Task1，调参模式登记 task 1=球速阶跃。动作映射集中在 PiControl.cpp 的 kTasks，编号按模式解释。request_seq=0 表示没有运动任务请求，不执行初始化或启动动作，但仍可按所属任务应用参数；真实请求使用 1..65535，同一请求不重复执行。task 15 不再初始化。本次编号/空闲语义修改需要配套更新 Pi 并重新烧录固件，虽然帧长度不变。所有数值单位和原控制 CSV 列保持，flags 仅位 0 表示视觉有效；status 位 3/4 直接表示当前任务请求执行成功/参数应用成功，位为 0 表示未确认成功。

CommunicationTask.cpp 负责串口拆帧、模式匹配、视觉发布及回传；GimbalTask 处理模式切换，PiControlExecutor 在控制任务中按请求号/版本号执行一次动作和参数更新，不会每帧重启任务或清空积分。运行中的测试拒绝新参数版本并回报失败，测试结束后提交新版本。结果随遥测返回，任务启动成功不代表整个运动完成。估计器不解释业务模式，保留 ±11 cm 有效位置范围和 100 ms 视觉超时。Pi 停止更新时，重复数据包不再永久保持有效位。

0x84/0x85 都保留 control_ms/control_x/control_v/target_v 等控制 CSV 字段，可沿用分析脚本，但 Task1 采样周期改为 20 ms，调参为 5 ms。115200 8N1 下调参遥测约 8800 B/s，占单向理论带宽约 76%；尚未实测丢帧和控制时序。必须配套更新 Pi 与固件，包括新增 PiControl.cpp/h。完整格式与调用见 [通信说明](../26H_Remake_Raspderry/ballbeam/communication/README.md)。Ctrl+C 仅结束 Pi，操作者仍需手动复位 MCU，异常时物理急停。

USART6 文本命令现按功能分组，数值必须为有限值，且参数个数需完全匹配：

| 分组 | 命令 | 单位/说明 |
| --- | --- | --- |
| 电机 | `motor pid-speed KP KI KD`、`motor pid-angle KP KI KD` | 电机 PID |
| 电机 | `motor target-current A`、`motor target-speed RPM`、`motor target-angle DEG`、`motor target-step DEG` | 电机目标；角度为度 |
| 电机 | `motor enable/disable/start/stop`、`motor limit-current A`、`motor limit-angle MIN MAX`、`motor limit-angle-off`、`motor limit-rate DEG_S`、`motor deadband-angle DEG` | 电机运行和保护 |
| 球杆 | `ball pid-position KP KI KD`、`ball pid-velocity KP KI KD` | 位置环和速度环；覆盖值在随后启动 Task1 时继续有效 |
| 球杆 | `ball target-position CM`、`ball target-speed CM_S` | 前者启动位置双环；后者启动无制动速度阶跃，要求视觉新鲜且小球在中心附近 |
| 球杆 | `ball enable/disable`、`ball balance-angle DEG`、`ball limit-angle DEG`、`ball limit-speed CM_S`、`ball feedforward POS NEG`、`ball rate MS`、`ball deadband-position CM` | 运行、限幅和前馈 |
| 视觉估计 | `vision ab ALPHA BETA`、`vision deadband CM`、`vision limit MAX_V_CM_S MAX_STEP_CM`、`vision predict HOLD_MS MAX_STEP_CM` | 只调整下位机当前实际使用的估计参数 |
| 诊断/任务 | `task init/1/stop/status`、`zero set/clear`、`csv vision/control/sysid/off` | 保留采集与维护入口 |

旧 `bbp*`、`bpush*`、`bgain`、`vf2`、`vv`、`vablim` 等 USART6 文本命令已删除；历史采集记录仍按原格式保存。这里的树莓派候选球筛选和发帧前跳变过滤不由 USART6 调节。

本 README 只导航代码责任。固件编译与烧录由项目持有人完成，不在这里提供可能与实际硬件环境不符的通用指令。
