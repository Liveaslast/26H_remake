# 树莓派｜视觉与通信

Pi测量小球并发送最终状态，STM32完成状态估计和电机闭环。入口为 `best/run.py → app/main.py`。

## 代码入口与调用链

| 位置 | 主要接口与作用 |
|---|---|
| `app/main.py` | `run/handle_result` 创建组件、连接回调、交接结果 |
| `app/arguments.py`、`config.py` | 参数声明、配置合并及通用检查 |
| `app/task_startup.py` | `TASKS/TaskSpec` 定义任务；`TaskRunner` 管启动请求和确认 |
| `app/tracking.py`、`detector_setup.py` | 创建视觉组件，取图并调用逐帧处理 |
| `vision/angles.py`、`calibration.py` | 角度历史、图像时刻匹配、标定展开 |
| `vision/detection_runtime/`、`tracker.py` | 像素检测、候选选择、厘米换算和时序状态 |
| `vision/ball_state.py` | `BallStateBuilder` 生成最终发送状态 |
| `communication/client.py` | 应用唯一通信入口，保存遥测并交付回调 |
| `communication/session.py` | `ModeRequest` 管确认，`DataStream` 管内容，`FrameSender` 管发送，`CommunicationSession` 管线程与队列 |

~~~text
视觉：camera.read → 匹配角度 → 展开 → 检测 → 候选/跟踪
  → handle_result → BallStateBuilder → client.publish_ball_state
  → session最新视觉邮箱

请求：client.select_mode / request_task / set_velocity_parameters
  → session.call → submit → inbox → 通信线程_process_operation
  → 模式：ModeRequest.begin → sender.send_mode → pack_mode_request
  → 任务/参数：登记到DataStream，等待周期发送

周期发送：_run → sender.send_due → stream.snapshot
  → pack_run / pack_tuning → transport.write → 发包记录回调

接收：transport.read_available → FrameDecoder.feed
  → 模式应答：ModeRequest.receive完成Future
  → 遥测：client缓存 → AngleHistory.record / CSV回调
~~~

`publish_ball_state` 只更新状态；任务请求只等本地登记，模式选择等待MCU应答。结果查询读遥测缓存，不发送查询帧。角度历史由视觉随后查询，不主动启动视觉处理。

通信只有一个线程；相机采集和CSV写盘另有工作线程。回调快速返回，不能同步等待同一通信线程。`TaskRunner` 和具体业务任务是普通对象，不创建线程。

## 正式启动

在树莓派执行；工作空间为 `~/vision_workspace/workspace`，虚拟环境为 `~/vision_workspace/.venv`：

```bash
cd ~/vision_workspace/workspace
source ~/vision_workspace/.venv/bin/activate
python3 best/run.py \
  --port /dev/ttyUSB0 \
  --inference-backend hailort \
  --mode run \
  --task-id 1 \
  --wifi-stream \
  --no-display
```

这条命令启动视觉和通信，**不自动初始化或启动运动任务**。浏览器调试页可额外加 `--debug-page`，默认关闭；图传也不是通信必需组件。

要由终端交互启动任务，在命令末尾加 `--task-console`。流程为：

1. 人工把梁保持在机械零位并按 Enter。
2. 组装组件、打开串口、请求模式、开启周期通信并等待有效角度遥测。
3. 请求 task 0：设置编码器零点并下发当前 profile 的平衡角（当前为 21°）。
4. 执行所选任务的专属初始化；等待人工输入 `task 1`。
5. 开始相机视觉循环；有效且新鲜的视觉已写出后，提交所选任务请求。

task 0 的成功仅表示初始化命令已执行，不证明电机已到位。必须等待实物稳定。模式确认也不代表机械初始化、参数应用或视觉就绪。

未开启 `--task-console` 时不会自动请求 task 0 或运动任务；如需控制，应通过下位机相应接口另行初始化和启动，不能仅凭“视觉已运行”判断电机状态。

## 任务与采集

模式内任务号独立：两模式task 0初始化，RUN/task 1为正式任务，TUNING/task 1为球速阶跃。先确认参数再请求启动。线上请求号和确认规则统一见[协议约定](ballbeam/communication/README.md)。

球速阶跃示例：正向 2 cm/s，默认采集 5 秒。示例目录仅供本次实验使用，重复实验请换独立目录：

```bash
cd ~/vision_workspace/workspace
source ~/vision_workspace/.venv/bin/activate
mkdir -p output/tuning_velocity/run_001
python3 best/run.py \
  --port /dev/ttyUSB0 \
  --inference-backend hailort \
  --mode tuning \
  --task-id 1 \
  --velocity-test 2 \
  --velocity-kp 0.5 \
  --velocity-ki 0 \
  --velocity-kd 0 \
  --task-console \
  --task1-csv output/tuning_velocity/run_001/control.csv \
  --vision-probe-csv output/tuning_velocity/run_001/vision.csv \
  --task1-capture-s 5 \
  --no-display
```

该命令请求+2cm/s速度测试；任务范围与保护由MCU任务实现，不由Pi决定。

采集目录包含控制 CSV、`ball_state_tx.csv`、可选视觉 CSV；球速任务额外保存 `velocity_settings.json`。`--task1-csv` 是保留的通用控制采集选项名，不表示只允许 RUN/task 1 使用。

**采集窗口到时只停止记录，不停止电机控制。** `--task-console` 下 Ctrl+C 使用立即退出，仅结束 Pi，不保证日志排空，也不会向 MCU 发送停机指令；操作者需要手动复位 MCU 或物理急停。回平衡角也不等于小球被主动刹停。

## 当前视觉与时间约定

正式配置 `config/runtime.toml` 默认 HailoRT、每帧模型检测、bbox 中心、关闭圆拟合；Pi Kalman 的命令行开关默认关闭。最终状态来源明确为 `measurement_state`，不额外滤波。已有可选估计实现不代表默认启用。MCU 自身估计器不在此调整。

图像时间是 Pi 读取图像完成时刻；角度历史使用 Pi 收到遥测的时刻，两者不是硬件同步。按图像时刻减相机延迟估计值查询角度。发送时超过 100 ms 的视觉会清除有效位；MCU 另有自身超时和 ±11 cm 有效位置范围检查。

## 部署与验证

Pi与MCU必须使用配套协议和任务语义，不支持旧布局。同步完整正式目录，不能只覆盖个别文件；SCP覆盖不会删除已移除的旧模块。不要同时运行两个程序抢占串口或相机。格式以[通信说明](ballbeam/communication/README.md)为准。

部署后的离线检查：

```bash
cd ~/vision_workspace/workspace
source ~/vision_workspace/.venv/bin/activate
sha256sum -c SHA256SUMS.txt
python3 -B -m unittest discover -s tests -q
```

校验清单检查文件一致性，测试检查已覆盖行为；两者不代替相机、模型、串口时序和控制安全的实机验证。

## 模型与标定边界

- 生效标定：`assets/calibration/dynamic_calibration_12_30deg.json`，粗 ROI `(128,425,1141,121)`，样本角度 12、14、…、30°。
- 当前标定 `geometry_id=8a5cd731dad6021704fb36f25fd423fa7ecd1634c998e23d7eaf9b13ff81126f`。
- 历史 NCNN 模型和 2405 组封存训练资料对应 `geometry_id=b5db7d686fc483d125f523499dbbdb9bc71a2d9a2b7f9709992a53b8174de5ad`，不能回写成新几何。
- Hailo HEF 缺少 `deployment.json`，不能自动证明与当前标定匹配，仍需实机检查。
- 只有已核对的历史 NCNN/标定组合可以显式加 `--allow-historical-ncnn-geometry`；此选项不代表其它不匹配组合可用。对照参数可用 `--inference-backend ncnn --ncnn-backend cpp`，并单独明确实验曝光配置。
- 原生 NCNN 构建入口为 `ballbeam/vision/detection_runtime/cpp/build.sh`，需要 CMake、Ninja、pybind11；默认正式 Hailo 运行不需要为此改算法链。

树莓派原机环境记录见 `RUNTIME_ENVIRONMENT_RASPBERRY_PI.txt`。历史实验结果不能自动作为当前架构、相机或模型的验证结果。
