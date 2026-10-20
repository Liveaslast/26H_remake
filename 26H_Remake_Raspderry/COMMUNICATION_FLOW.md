# 上位机通信链路：分层与调用图

核对日期：2026-10-20。按当前源码绘制，仅整理说明，不修改运行代码。

## 阅读约定

- **图 1 看层次，不看执行先后。** 它只说明模块归属、上下层如何连接。
- **图 2～4 看调用。** 每张图只讲一个过程，不把发送与返回混在同一张图中。
- 图中路径相对于 `D:/26H-remake/26H_Remake_Raspderry/ballbeam/`。
- 箭头区分“调用”“队列交接”“读取已保存数据”，不要都理解成串口发送。
- `app` 是应用协调目录，不是“所有非通信代码”。视觉在 `vision/`，记录在 `recording/`。

## 图 1：先认层，再认模块

这张图是模块地图，箭头表示上层使用下层，**不是一次发送依次经过所有节点**。

```mermaid
flowchart TB
    subgraph A["① 应用协调与业务组件"]
        MAIN["app/main.py · run() / handle_result()<br/>连接命令行、视觉、任务、记录器"]
        COMPONENTS["arguments.py：parse_runtime_args → args<br/>tracking.py：run_tracking_loop → result<br/>task_startup.py：TaskRunner<br/>recording/capture.py：CaptureSession"]
        MAIN --- COMPONENTS
    end
    subgraph B["② 统一通信入口"]
        CLIENT["communication/client.py · McuSerialClient<br/>对外操作接口；最新遥测；记录回调"]
    end
    subgraph C["③ 通信调度与状态"]
        COORD["communication/session.py · CommunicationSession<br/>线程、操作队列、接收分发"]
        STATE["同一文件内的协作组件<br/>ModeRequest：模式请求及确认<br/>DataStream：周期帧数据<br/>FrameSender：组帧与统一写出"]
        COORD --- STATE
    end
    subgraph D["④ 设备访问"]
        TRANSPORT["communication/transport.py · SerialTransport<br/>打开 / 关闭 / 读取字节 / 写入字节"]
    end
    MAIN -->|"通过客户端接口使用通信"| CLIENT
    CLIENT -->|"提交操作与视觉；接收内部通知"| COORD
    STATE -->|"FrameSender 写；Session 读"| TRANSPORT
    TRANSPORT -->|"串口连接"| MCU["STM32"]
```

`communication/protocol.py` 是通信层使用的**协议工具模块**，不是额外的串口层：
- FrameSender 调用 `pack_mode_request / pack_run / pack_tuning` 得到 bytes。
- Session 调用 `FrameDecoder.feed()`，得到解码后的模式应答或遥测。
- 打包器不写串口，解码器不自己读取串口。

### 同一份 session.py 内，谁保存什么

| 对象 | 保存什么 | 不负责什么 |
|---|---|---|
| `session.mode: ModeRequest` | current_mode、target_mode、seq、reply、deadline | 不组帧、不读写串口 |
| `session.stream: DataStream` | 最新视觉邮箱、task_id、request_seq、parameters、revision、packet_seq | 不决定发送周期、不组帧、不写串口 |
| `session.sender: FrameSender` | period、next_send_at、发送错误和失败计数 | 不决定具体任务的业务行为 |
| `session: CommunicationSession` | thread、inbox、操作分发表 | 不直接打包、不直接写串口 |

## 图 2：模式请求怎样发出去

只看发送方向。该过程**发送一次**，不是周期发送。

```mermaid
flowchart TB
    subgraph A["应用调用侧 · app/main.py"]
        A1["run()<br/>client.select_mode(mode)"]
    end
    subgraph B["客户端 · communication/client.py"]
        B1["McuSerialClient.select_mode()<br/>session.call('mode', (mode, timeout))"]
    end
    subgraph C["线程交接 · session.py"]
        C1["CommunicationSession.call() → submit()<br/>inbox 放入 operation、data、reply"]
        C2["通信线程 _run() → _process_operation()<br/>取出 mode 操作 → _request_mode()"]
    end
    subgraph D["模式登记与发送 · session.py"]
        D1["ModeRequest.begin()<br/>分配模式请求号、保存确认状态"]
        D2["DataStream.reset()<br/>清除旧任务、参数和视觉"]
        D3["FrameSender.send_mode()<br/>调用 protocol.pack_mode_request()"]
        D4["FrameSender._write(frame)"]
    end
    E["transport.py · SerialTransport.write()<br/>写入 0x06 字节帧"]
    A1 --> B1 --> C1
    C1 -->|"操作队列交接；调用者等待 Future"| C2
    C2 --> D1 --> D2 --> D3 --> D4 --> E
```

应答返回链单独看：

`STM32 0x86 → transport.read_available → decoder.feed → session._receive_frames → mode.receive → reply.set_result → client.select_mode 返回`。

无匹配应答时，由 `_run → mode.check_timeout()` 返回失败；写出失败则 `_request_mode → mode.fail()`。不自动重发。

## 图 3：任务和视觉在哪里汇合，在哪里周期发送

这张图只看 RUN/TUNING 周期帧。任务操作和视觉更新最终汇入**同一个 DataStream**，发送由通信循环单独驱动。

```mermaid
flowchart TB
    subgraph A["① 应用组件"]
        TASK["app/task_startup.py · TaskRunner.start_if_ready()<br/>client.request_task(task_id)"]
        VISION["app/main.py · handle_result()<br/>BallStateBuilder.update(result) → state<br/>client.publish_ball_state(state...)"]
    end
    subgraph B["② 客户端 · communication/client.py"]
        CT["McuSerialClient.request_task()<br/>session.call('task', task_id)"]
        CV["McuSerialClient.publish_ball_state()<br/>session.publish_ball(...)"]
    end
    subgraph C["③ 通信内部 · communication/session.py"]
        QT["CommunicationSession<br/>call → submit → inbox<br/>_run → _process_operation"]
        QV["CommunicationSession.publish_ball()<br/>stream.publish_vision(...)"]
        DATA["同一个 DataStream<br/>request_task() 保存任务号、请求号<br/>publish_vision() 更新最新视觉邮箱"]
        LOOP["_run() 每轮调用<br/>sender.send_due(current_mode, stream, now)"]
        SEND["FrameSender.send_due()<br/>模式已确认、周期已开启、且到发送时间<br/>→ send_data()"]
        SNAP["DataStream.snapshot()<br/>读取视觉、任务、参数及编号<br/>返回 fields，不发送"]
        PACK["FrameSender.send_data()<br/>RUN：protocol.pack_run(**fields)<br/>TUNING：protocol.pack_tuning(**fields)"]
        WRITE["FrameSender._write(frame)"]
    end
    OUT["④ communication/transport.py<br/>SerialTransport.write(frame)<br/>0x07 或 0x08 → STM32"]
    TASK --> CT --> QT
    QT -->|"登记任务，不立即发帧"| DATA
    VISION --> CV --> QV --> DATA
    LOOP --> SEND --> SNAP
    DATA -.->|"snapshot 读取已保存的数据"| SNAP
    SNAP --> PACK --> WRITE --> OUT
```

**两条线不要混淆：**
1. `request_task()` 登记内容并返回请求号；不直接启动一次串口发送。
2. `_run → send_due → send_data` 到期后取快照、打包、写串口。它读取的正是刚才登记的数据。

周期由 `main.run → client.start_stream(period) → session.call('stream', period) → sender.set_period(period)` 开启。没有任务请求时也能传视觉，request_seq=0 表示无任务动作。

TUNING 参数走：
`task_startup.initialize_velocity_test → client.set_velocity_parameters → session.call('parameters', (task_id, parameters)) → DataStream.set_parameters`，保存所属任务号、参数及版本，并将线上 request_seq 置0。它只配置参数、不触发运动；内部任务请求计数器继续保留，随后 request_task 分配新的非零请求号。TUNING 球速任务使用编号1，两端分别以协议常量维护，测试会检查一致性。

视觉出口在 main 中显式指定为 `BallStateBuilder(state_source=measurement_state)`。当前 source 选择测量位置（缺失时回退跟踪位置）和跟踪速度，不额外滤波。未来处理函数返回最终 BallState 后，Builder 不会再读取原始测量覆盖它，client 接口不变。

## 图 4：收到遥测后，怎样回到客户端和应用组件

只看 MCU 返回方向，不画反向发送箭头。

```mermaid
flowchart TB
    U["STM32 发回 0x84 / 0x85 遥测"]
    subgraph T["① 字节读取 · communication/transport.py"]
        READ["SerialTransport.read_available()<br/>返回字节，可能半帧或多帧"]
    end
    subgraph S["② 接收处理 · communication/session.py"]
        DECODE["_receive_frames() 调用<br/>protocol.FrameDecoder.feed(bytes)<br/>拆帧、校验、解码"]
        MATCH["与 current_mode 一致的遥测<br/>调用 on_telemetry(frame, time)"]
    end
    subgraph C["③ 客户端 · communication/client.py"]
        CALLBACK["McuSerialClient._publish_telemetry()<br/>latest_telemetry = decoded"]
    end
    subgraph A["④ 应用使用结果"]
        ANGLE["vision/angles.py · AngleHistory.record()<br/>保存角度及 Pi 接收时刻"]
        CSV["recording/csv_recorders.py<br/>Task1CsvLogger.publish(sample)"]
        QUERY["client.task_result(request_seq) 读取缓存<br/>TaskRunner.check_result() 使用结果"]
    end
    U --> READ --> DECODE --> MATCH --> CALLBACK
    CALLBACK -->|"record_actual_angle 回调"| ANGLE
    CALLBACK -->|"record_control_sample 回调"| CSV
    CALLBACK -.->|"缓存供上层查询，不是发送查询包"| QUERY
```

这三条支路用途不同：
- **角度反馈给视觉：** `FrameAngleSource.for_frame(image_time) → AngleHistory.angle_at() → tracking.process_frame()`。
- **控制数据记录：** `Task1CsvLogger.publish → CsvWriter.write → CsvWriteWorker.submit`，由 CSV 后台线程写盘。
- **任务确认：** `task_result()` 核对请求号及 status 的任务成功位。参数确认则用 `parameters_result(revision)` 核对版本及参数应用成功位。均不发送额外查询包。

`0x86` 模式应答在 Session 内交给 ModeRequest，**不经过**客户端的遥测回调。

## 应用如何连接这些模块

这些连接在 `app/main.py · run()`，不是各组件相互创建彼此：

| 连接代码 | 作用 |
|---|---|
| `client = McuSerialClient(...)` | 创建统一通信入口 |
| `angles = AngleHistory(...)` | 创建角度历史组件 |
| `client.record_actual_angle = angles.record` | 收到角度后交给角度历史 |
| `capture = CaptureSession(...)` | 创建可选记录器协调器 |
| `client.record_control_sample = capture.control.publish` | 将控制遥测交给记录器 |
| `client.record_sent_frame = capture.sent.publish` | 将实际成功写出的周期包交给记录器 |
| `tasks = TaskRunner(client, ...)` | 任务启动管理器通过同一个客户端提交和查询 |
| `result_handler=handle_result` | 视觉循环将 result 交给 main 的协调函数 |
| `angle_for_frame=frame_angles.for_frame` | 视觉循环通过角度接口获得图像对应角度 |

命令行组件生成 args，不直接操作串口。记录器接收回调或视觉结果，不直接调用串口。TaskRunner 当前类名仍是 TaskRunner；它是启动请求管理器，不在 Pi 上执行 MCU 控制任务。

## 单独理解发包日志

这条通知与“MCU 已收到”不是一回事：

`FrameSender.send_data → _write 成功 → stream.mark_sent → client._record_sent_frame → record_sent_frame → BallStateTxLogger.publish`。

客户端会据此更新 `visual_state_sent`。它表示本地最近一次成功写出的周期包视觉是否有效，不是 MCU 接收 ACK。

`capture.record_vision(result, state)` 记录的是视觉结果及提交给通信的状态；发包日志记录的是实际写出的周期包。这两者分开，才能排查提交与发送之间的问题。

## 从图定位源码

| 文件 | 建议先找的入口 |
|---|---|
| [app/main.py](D:/26H-remake/26H_Remake_Raspderry/ballbeam/app/main.py) | run、handle_result、回调赋值 |
| [app/arguments.py](D:/26H-remake/26H_Remake_Raspderry/ballbeam/app/arguments.py) | parse_runtime_args；配置合并在 config.py |
| [app/task_startup.py](D:/26H-remake/26H_Remake_Raspderry/ballbeam/app/task_startup.py) | initialize_task_startup、TaskRunner |
| [communication/client.py](D:/26H-remake/26H_Remake_Raspderry/ballbeam/communication/client.py) | start、select_mode、request_task、publish_ball_state |
| [communication/session.py](D:/26H-remake/26H_Remake_Raspderry/ballbeam/communication/session.py) | _run、_process_operation、_request_mode、FrameSender |
| [communication/protocol.py](D:/26H-remake/26H_Remake_Raspderry/ballbeam/communication/protocol.py) | pack_*、FrameDecoder |
| [communication/transport.py](D:/26H-remake/26H_Remake_Raspderry/ballbeam/communication/transport.py) | read_available、write |
| [app/tracking.py](D:/26H-remake/26H_Remake_Raspderry/ballbeam/app/tracking.py) | TrackingComponents 保存组件；build_tracking_components 创建组件；process_frame、run_tracking_loop 组织逐帧运行 |
| [vision/angles.py](D:/26H-remake/26H_Remake_Raspderry/ballbeam/vision/angles.py) | AngleHistory、FrameAngleSource |
| [recording/capture.py](D:/26H-remake/26H_Remake_Raspderry/ballbeam/recording/capture.py) | open、start、record_vision、close |

## 线程边界

- 调用侧运行配置解析、视觉循环、TaskRunner；call/submit 用操作队列交给通信线程。call 等待结果，但不占用通信线程执行等待。
- publish_ball 直接更新线程安全的最新视觉邮箱，不等待通信线程或 MCU。
- McuCommunication 线程组织串口读写、请求处理、模式确认及周期发送，也调用客户端和记录回调。
- 配套记录器快速入队，CSV 写盘由共享 CsvWriteWorker 后台线程完成。
- client.start 打开串口并启动线程；普通退出先停止发送和通信，再关闭记录文件。task-console 的 Ctrl+C 当前使用 os._exit(130)，不保证清理和排空日志，需手动复位 MCU。
