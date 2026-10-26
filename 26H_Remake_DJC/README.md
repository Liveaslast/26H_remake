# STM32｜状态估计、任务与电机控制

Pi发送视觉数据和请求；STM32接收、估计、执行任务并回传遥测。本文说明源码，不代表设备已烧录同版本。

## 目录边界

| 目录（均配套inc、src） | 职责 |
|---|---|
| `APP/` | RTOS任务、硬件回调与任务间交接 |
| `Application/Communication/` | PiProtocol协议、PiRequestHandler请求处理、AppTelemetry遥测出口 |
| `Application/BallBeam/` | 估计器、任务对象、闭环控制、配置及数据定义 |
| `Application/MotorTest/` | 可选裸机电机测试，由 `APP/inc/BuildMode.h` 选择 |
| `UserLib/` | PID、QDMotorController等底层组件，不引用球杆业务头 |
| `Devices/`、`Hardware/` | 设备与硬件访问 |
| `Core/`、`Drivers/`、`Middlewares/`、`cmake/` | 平台初始化、HAL、中间件与构建 |

不保留旧路径的重复实现或兼容转发头。函数作用直接看对应源码注释。

## 运行链

~~~text
USART1回调 → PiProtocol提取完整帧 → 接收队列
  → CommunicationTask解码、保存：
      视觉数据 → BallStateTask → BallStateEstimator → 最新估计结果
      模式/任务/参数请求 → GimbalTask中的PiRequestHandler
        → BallBeamTasks → 具体任务设置目标
  → GimbalTask用估计结果和目标调用BallBeamController
    → QDMotorController → 电机

AppTelemetry读取业务状态 → CommunicationTask追加请求结果
  → PiProtocol打包 → USART1 DMA回传
~~~

GimbalTask每轮顺序为：执行调试命令 → 运行球杆任务与闭环 → 执行Pi请求 → 电机控制。父类 `Ctrl_ISR()` 在此是普通函数调用，不是中断。

## 通信模块的接口与执行位置

| 文件 | 负责什么 |
|---|---|
| `Application/Communication/PiProtocol` | 帧提取、检查、编解码，不依赖HAL/RTOS |
| `APP/CommunicationTask` | USART1/DMA、收帧队列、模式/数据/结果交接及发送调度 |
| `Application/Communication/PiRequestHandler` | 在GimbalTask中按 `kPiTaskBindings` 路由、去重并调用任务，交回执行结果 |
| `Application/Communication/AppTelemetry` | 只读整理估计、任务、电机及控制输入，不执行请求 |

表中业务文件位于各组的 `inc/`、`src/`。通信任务不执行PID或具体任务规则。

`CommunicationTask.h` 提供五个交接接口：

| 接口 | 用途 |
|---|---|
| `Communication_ReadModeRequest` | 读取待处理模式请求 |
| `Communication_ReadExecutionRequest` | 读取最新任务及参数请求 |
| `Communication_ReadLatestVisionData` | 读取最新视觉数据，可检查年龄 |
| `Communication_SaveModeResult` | 保存模式处理结果，之后发送应答 |
| `Communication_SaveExecutionResult` | 保存任务/参数处理结果，之后随遥测发送 |

读取不删除数据，也不代表数据有效。模式结果与执行结果只由GimbalTask中的唯一请求处理器同步提交。

- 模式请求经APP处理后发送一次应答；模式交接状态为 `Idle → Requested → ReplyReady → Idle`。
- 模式应答优先；两模式遥测均每20ms尝试发送。DMA忙时不覆盖发送缓冲，不积压补发遥测。
- 通信保存当前模式下收到的视觉；估计器与任务决定能否采用。最新值交接可能跳过中间帧，不是历史队列。
- 视觉可用条件为跟踪有效且位置在±11cm内；运动任务另检查100ms时效。无效视觉不刷新估计器上一有效测量时间，估计超时后无效。
- `mode_generation` 是内部模式切换次数，用于重置请求去重，不在线上传输。队列不代替共享结构体复制时的短临界区。
- 完整帧定义不在调度层维护，见下文协议约定。

## 任务执行

RUN/task 1是位置序列，TUNING/task 1是速度测试，task 0设置零点并下达平衡角。线上编号、请求去重和结果语义由[协议约定](../26H_Remake_Raspderry/ballbeam/communication/README.md)维护。

速度测试配置由任务自己保存，启动时才应用；正式任务重新加载自己的配置。切模式时结束旧活动任务并下达平衡角，不等待机械到位。

## 球杆组件的职责与入口

| 组件 | 职责与入口 |
|---|---|
| `BallStateTask` | 按2ms节拍读取视觉、调用估计器，交接配置并保存最新结果 |
| `BallStateEstimator` | `saveVisionMeasurement/updateEstimate`：测量准入、a-b修正、有限预测与100ms超时；持有算法历史，不操作电机 |
| `BallBeamTasks` | `initializeTask/startTask/runCurrentTask/stopTask`：选择、启停和周期调用任务对象 |
| `PositionSequenceTask / VelocityTestTask` | 各自拥有阶段、启动条件和退出规则；不是RTOS线程 |
| `BallBeamController` | 根据估计状态和目标计算位置/速度环、前馈、积分约束及目标角度，不拥有任务阶段 |
| `BallBeamTaskProfile.h` | 集中定义控制配置和任务目标序列；控制器只接收control配置 |

估计输入/输出为cm、cm/s、MCU毫秒。`BallStateGetLatest()` 只表示取得记录，必须另看 `state.valid`。控制器共享速度PID，位置控制单独决定前馈及积分规则；实际电机角度输出使用rad。算法细节见源码注释。

当前平衡角21°是本机装配值。task 0或任务启动加载配置；手工setter只改当前配置，不跨任务隐式保留。速度测试目标绝对值1–5cm/s，启动要求位置±1cm内、速度不超过0.7cm/s且视觉新鲜；到±6cm退出，高速12cm/s、视觉异常、反向触边或8秒超时为保护退出。回平衡角不等于主动刹停。

`holdBalance()` 下达平衡角，不改写上次真实控制输入；`disableBalance()` 停止小球闭环但不主动停电机。原始视觉、估计结果和控制输入记录不是同一份数据，遥测字段也不保证同一时刻采样。

## USART6 调试口

USART1用二进制协议；USART6用文本命令和CSV。

| 分组 | 命令 |
|---|---|
| 电机PID | `motor pid-speed KP KI KD`、`motor pid-angle KP KI KD` |
| 电机目标 | `motor target-current A`、`motor target-speed RPM`、`motor target-angle DEG`、`motor target-step DEG` |
| 电机运行 | `motor enable/disable/start/stop` |
| 电机限制 | `motor limit-current A`、`motor limit-angle MIN MAX`、`motor limit-angle-off`、`motor limit-rate DEG_S`、`motor deadband-angle DEG` |
| 球杆PID | `ball pid-position KP KI KD`、`ball pid-velocity KP KI KD` |
| 球杆目标 | `ball target-position CM`、`ball target-speed CM_S` |
| 球杆配置 | `ball enable/disable`、`ball balance-angle DEG`、`ball limit-angle DEG`、`ball limit-speed CM_S`、`ball feedforward POS NEG`、`ball rate MS`、`ball deadband-position CM` |
| 估计器 | `vision ab ALPHA BETA`、`vision deadband CM`、`vision limit MAX_V_CM_S MAX_STEP_CM`、`vision predict HOLD_MS MAX_STEP_CM` |
| 任务与零点 | `task init`、`task 1`、`task stop`、`task status`、`zero set`、`zero clear` |
| 打印 | `csv control`、`csv vision`、`csv sysid`、`csv off` |

DebugTask解析命令并入队，GimbalTask执行动作；CSV模式不夹杂诊断文本，目标打印周期5ms。旧BBP/BPUSH及 `ba` 命令不再支持。列定义见[数据格式](../26H_Remake_Support/Docs/DATA_FORMAT.md)。

## 构建与安全

需安装ARM GCC、CMake与Ninja，在本目录执行：

~~~bash
cmake --preset Debug
cmake --build --preset Debug
~~~

未授权不烧录或启动电机。模式确认、task 0成功和回平衡角均不证明机械已到位；Pi退出或CSV到时不停止MCU。编译与离线测试不替代实机时序和安全验证。
