# 两模式通信

## 完整流程

```text
client.start()：打开串口，启动唯一通信线程
    ↓
select_mode(RUN / TUNING)：发 0x06，等待 0x86 成功应答
    ↓
start_stream(period)：开始周期数据通信
    ├─ 运行模式：0x07 → MCU → 0x84
    └─ 调参模式：0x08 → MCU → 0x85
```

尚未确认模式时不发送周期数据；两端只接受当前模式的数据类型。模式切换超时或失败，Pi 不继续发送数据，也不自动重试。模式切换不是运动启动；切换前若旧球任务正在运行，MCU 停止旧任务并回到平衡角，否则不改变当前电机目标。模式确认不代表机械动作已稳定。

## 只有六种帧

| 方向 | 帧 | 字节数 | 用途 |
|---|---|---:|---|
| Pi→MCU | 0x06 | 6 | 模式请求：A5 06 seq16 mode CRC |
| MCU→Pi | 0x86 | 7 | 模式应答：5A 86 seq16 mode result CRC |
| Pi→MCU | 0x07 | 21 | 运行模式：视觉数据、任务 ID、任务请求号 |
| MCU→Pi | 0x84 | 42 | 任务遥测：控制数据、任务执行结果 |
| Pi→MCU | 0x08 | 39 | 调参模式：视觉、测试指令、PID/目标速度及参数版本 |
| MCU→Pi | 0x85 | 44 | 调参遥测：控制数据、任务结果、参数应用结果 |

mode：1=任务，2=调参。result：0=成功，1=失败。所有多字节字段为小端，位置/速度/角度乘 100，PID 乘 10000，时间戳为毫秒。详细布局以 protocol.py 的 struct 定义为准。0x09 和通用命令 ACK 已删除。

两种遥测保留相同控制 CSV 字段，运行模式 20 ms，调参模式 5 ms。115200 8N1 下，调参遥测单向约 8800 B/s，占理论带宽约 76%；实机仍需检查丢帧和时序。

## 周期包不重复执行动作

包序号 seq 每次成功写入递增，只用于追踪传输。任务请求号 request_seq 只在调用 request_task() 时递增，随后重复携带同一个请求；MCU 对同一请求号只尝试执行一次。request_seq=0 保留为没有任务请求，真实请求使用 1..65535，回绕时跳过 0。任务 ID 相同但请求号改变，才是一次新的请求；不需要归零握手，也不单独发任务 ACK。

- 运行模式：task 1 正式任务，task 0 初始化。
- 调参模式：task 1 速度阶跃，task 0 初始化。
- task_id=0 且 request_seq=0：只提供视觉数据，不初始化；request_task(0) 会生成非零请求号，才执行初始化。
- task 15 不再初始化，当前两端均未登记该任务。

参数 revision 只在 set_velocity_parameters() 时改变；MCU 同一版本只应用一次，不会每帧重置积分。运行中的速度测试拒绝新参数版本并在遥测中报告失败；结束后需要提交新的版本。新模式确认后，MCU 清除请求/版本历史。

task_result(request_number) 和 parameters_result(revision) 查询遥测中的结果：None=没有对应请求号/版本的遥测，True=成功位为 1，False=成功位为 0（未确认成功）。这里没有新增应答帧，也没有在串口中增加“等待中”结果码。启动成功不代表整个运动结束。

## 最小调用

```python
client.start()
if not client.select_mode(Mode.TUNING):
    raise RuntimeError("mode not confirmed")
client.start_stream(0.01)
revision = client.set_velocity_parameters(0.5, 0.0, 0.0, 2.0)
# Camera results continuously update the data mailbox:
client.publish_ball_state(x_cm, v_cm_s, valid)
# Once vision and parameters are ready:
request_number = client.request_task(2)
# Poll telemetry in the application; never block the vision callback:
result = client.task_result(request_number)
# On exit:
client.stop()
```

正式 main.py 还负责人工安全确认、task 0 初始化、角度历史、相机启动和日志，这些不属于串口协议本身。应用任务定义与启动流程统一归 app/task_startup.py，但保留独立的函数、类和配置边界；MCU 动作映射归 PiControl.cpp。未收到执行结果不能断言 MCU 没执行；应排查并复位后重试，不能把这个框架理解为跨断线的恰好一次保证。

## 文件职责

| 文件 | 负责 |
|---|---|
| protocol.py | 模式和数据类型、结构、编码解码、CRC；独立的 FrameDecoder 类处理字节流拆帧与重新定位 |
| transport.py | 设备开关、串口字节读写 |
| session.py | ModeRequest 管模式请求及确认；DataStream 管完整周期帧数据；FrameSender 统一组帧、写出与周期发送；CommunicationSession 管线程、操作协调与接收分发 |
| client.py | 外部接口、组装与启停、遥测交付 |
| vision/angles.py | 电机角度历史、插值及按图像时刻匹配，不管理串口 |
| MCU PiControl.cpp | 同模式内任务、参数的一次性执行 |

没有 ack.py、handshake.py 或独立发送/接收线程。本地操作队列只用于让通信线程拥有通信状态；Future 仅在内部交接操作结果及等待模式应答，不向任务/参数 API 暴露通用应答框架。

### client 到串口的内部路径

`session.py` 内的组件留在同一个文件，不按代码片段继续拆文件：

- `ModeRequest`：保存目标模式、模式请求序号和等待结果，管理 0x06/0x86 匹配、确认和超时；不组帧、不写串口。
- `DataStream`：保存最新视觉、任务、参数及编号，`snapshot()` 整理发送快照并检查视觉时效；不组帧、不写串口。
- `FrameSender`：`send_mode()` 单次发送模式请求；`send_due()` 按周期发送 RUN/TUNING 数据；统一调用协议打包器，串口写入只有 `_write()` 一处。
- `CommunicationSession`：管理一个通信线程，接收客户端操作并分发，读取串口后交给协议解码器，再将模式应答或遥测交给相应接口。

模式请求走 `client.select_mode → session.call → mode.begin → sender.send_mode → sender._write → transport.write`，等收到匹配应答或超时后返回，不自动重试。任务请求走 `client.request_task → session.call → stream.request_task`，只登记字段并返回请求号。视觉更新走 `client.publish_ball_state → session.publish_ball → stream.publish_vision`，只覆盖最新样本。周期发送走 `sender.send_due → stream.snapshot → pack_run/pack_tuning → sender._write → transport.write`。新增同布局任务不需要修改这些调度组件。

MCU 的 CommunicationTask.cpp 只做接收、模式匹配、视觉发布、遥测和模式应答；GimbalTask 在模式切换时处理旧任务，PiControlExecutor 在控制任务中应用参数、启动动作并发布结果。估计器不解释模式协议。

视觉只更新容量为 1 的最新状态邮箱；图像时间距发送时刻超过 100 ms 时，重复包会清除视觉有效位，避免旧数据永久伪装成新视觉。MCU 保留 ±11 cm 范围检查和自身视觉超时保护。通信循环不是硬实时保证；相机、图传、日志线程不属于通信线程。

记录回调仍由通信线程调用，但配套记录器只整理行并非阻塞入队；三个文件共享一个后台 CSV 写盘线程。慢磁盘不会让这些回调等待文件写入，队列满会报告错误和丢行计数。正常关闭排空日志；task-console 的立即退出不保证排空。
发包记录接口为 `record_sent_frame(packet, sent_at)`，`packet` 来自协议解码器，客户端不再读取字节偏移或自行拆有效位。只供测试使用的单次 `ball` 操作已从正式通信操作表移除。

## 配套部署

本次帧长度不变，但初始化改为 task 0，且 request_seq=0 明确不执行任务，因此必须配套更新 Pi 并重新构建、烧录 MCU，不能混用旧版本。Pi 应同步完整 ballbeam/ 目录及配套 tests/、SHA256SUMS.txt；仅 scp 覆盖不会删除旧文件，应清理已迁移的旧模块。mode.py 和 framing.py 已合并移除，不保留转发文件；旧 ack.py、handshake.py、sender.py 也不应继续导入。

Support/Vision/IO/camera_telemetry.py 的角度读取也已适配两种新遥测。它先确认运行模式以读取角度，但不发送运动任务，仍用于视觉前置工具。控制 CSV 旧列保留，发包日志新增 request_seq/mode，capture_requested 兼容列现在表示是否调参模式。Task1 CSV 从 0x84 采样，不再要求切到 0x85。启动命令不变，有 --velocity-test 就选择调参模式，否则选择运行模式。

离线测试包括实际通信线程、两种模式的 main 启动流程、MCU 原始拆帧函数，以及实际 PiControlExecutor 的重复请求/参数保护。主机测试和 ARM 语法检查不能代替完整固件构建、DMA/RTOS 或实机验证。

status 第4位（1<<3）直接表示当前任务请求已成功执行，第5位（1<<4）直接表示当前参数版本已成功应用；对应位为0表示未确认成功。已删除 task_result/config_result 两个线字段，接收端只检查 status 的位值，并用请求号/版本防止读到上一次操作的成功标志。模式应答的 result 字段不变。VelocityParameters 只保存、检查和缩放参数；scaled() 返回整数元组，由 pack_tuning() 组帧，客户端负责交给通信线程发送。

## 参数所属任务

`set_velocity_parameters()` 提交 `(TUNING_TASK_VELOCITY, VelocityParameters)`。DataStream 保存所属 task_id、参数和新 revision，并将线上 request_seq 置为0，表示配置而非启动。内部请求计数器不归零，下一次 request_task 仍分配新的非零编号。MCU 的 PiControl.cpp 在 TaskBinding 中登记专用 apply_parameters 函数；初始化任务和未登记任务不会自动应用球速 PID。使用该参数的任务必须匹配参数所属任务及版本且确认应用成功，才能启动。帧布局不变，但此语义与任务编号要求 Pi 和 MCU 配套更新。
