# Raspberry Pi｜正式视觉运行包

## 固定球速短行程测试（本地代码，需配套固件）

沿用 `best/run.py`、`--task-console`、`--task1-csv` 和 `--vision-probe-csv`。统一输入 `task 1` 运行球速阶跃；`--velocity-test` 后手动给带符号目标速度，绝对值 1–5 cm/s（例如 `2` 或 `-5`）。Pi 先选择调参模式并确认；task init 后，通过周期 0x08 一并提供视觉、目标速度和 --velocity-kp/ki/kd。参数应用结果由 0x85 携带，拒绝或超时不启动测试。该配置只用于独立球速阶跃任务，不覆盖 Task1 双环参数。启动时 MCU 要求估计球位在 ±1 cm 内且速度绝对值不超过 0.7 cm/s，否则不确认请求。

阶跃期间目标速度保持常数，不生成制动段；从中部出发，估计位置沿目标方向到达 `+6` 或 `−6 cm` 后撤销球速控制并命令平衡角。反方向触及边界、速度达到 12 cm/s、视觉失效或 8 s 安全超时属于异常退出。回平衡角不等于主动刹停小球，球可能继续滑行，操作者必须确认实物余量并准备物理停机。球速 PID 为独立参数，反馈角限幅 ±7°、总角限幅 ±8°，外环约 20 ms。使用 44 字节 0x85 调参遥测及 `--task1-csv`，`seq_stage` 10/12/13 分别表示阶跃/完成/保护退出；按 `control_ms` 去重比较 `target_v` 和 `control_v`。同目录的 `velocity_settings.json` 记录请求参数、`pid_write_success=true` 和 `pid_applied_telemetry=true`，应用确认来自调参遥测，而非本地写入或遥测 toggle。此版本尚未同步、烧录或实机验证。

球速阶跃与 Task1 均保持 `--task1-capture-s` 默认 5 秒。CSV 到时只停止写盘，不负责停机；MCU 的 8 秒时限是异常兜底，不是预期测试时长。

本工程部署到 `/home/ikun/vision_workspace/workspace`。`best/run.py` 是唯一启动入口；资料制作和 CSV 分析在 [Support 工程](../26H_Remake_Support/README.md)。

## 启动

```bash
cd ~/vision_workspace/workspace
source ~/vision_workspace/.venv/bin/activate
python3 best/run.py --port /dev/ttyUSB0 --inference-backend hailort --debug-page --serial-read-timeout-ms 1 --wifi-stream --no-display
```

`(vision_ws)` 只是终端提示名称，实际虚拟环境是 `~/vision_workspace/.venv`。

## 目录

| 位置 | 内容 |
|---|---|
| `ballbeam/app/` | 入口、参数、组件组装、任务启动和逐帧流程；调用通信接口提交最新视觉数据 |
| `ballbeam/vision/` | 标定、追踪、检测与 HailoRT 后端 |
| `ballbeam/hardware/camera.py` | 相机参数、设备设置与最新帧采集 |
| `ballbeam/hardware/serial_config.py` | 串口端口、波特率和读写超时参数 |
| `ballbeam/communication/protocol.py` | 六种帧的定义、CRC、打包和解包；独立 FrameDecoder 类负责半帧累积、粘帧拆分和重新定位 |
| `ballbeam/communication/client.py` | 对外接口、组件启停、遥测订阅与日志交付，不包含发送调度 |
| `ballbeam/communication/session.py` | CommunicationSession 管唯一通信线程；ModeRequest 管模式确认；DataStream 管周期帧数据；FrameSender 统一组帧和串口写出 |
| `ballbeam/communication/transport.py` | 纯串口设备读写，不创建线程、不解析帧 |
| `ballbeam/vision/angles.py` | AngleHistory 保存和插值角度；FrameAngleSource 为图像匹配角度；都不创建客户端 |
| `ballbeam/vision/metrics.py` | 纯视觉频率和耗时统计，不管理展示或通信 |
| `ballbeam/recording/` | 采集窗口、CSV 行格式和共用后台写盘 |
| `ballbeam/app/task_startup.py` | 启动前诊断检查和 task init 流程 |
| `ballbeam/errors.py` | 应用与设备共同使用的运行异常 |
| `ballbeam/interfaces/` | presentation.py 提供本地画面及报告接口；子目录提供 DebugPage 与 Wi-Fi MJPEG |
| `config/runtime.toml` | 正式配置 |
| `assets/calibration/` | 生效的 12–30°标定 JSON |
| `assets/models/hailo/` | 正式 HEF 与模型 metadata |
| `assets/models/ncnn_model/` | 历史 128×640 NCNN 模型；只用于明确选择的无 Hailo 对照 |
| `ballbeam/vision/detection_runtime/cpp/` | 历史原生 NCNN 后端源码和离线依赖包；构建产物仍归检测模块 |

正式配置使用 HailoRT，球位置取 YOLO bbox 中心；不启用霍夫圆或 Pi Kalman。状态估计、闭环控制和 Task1 均在 STM32 完成。Hailo 与 NCNN 共用的尺寸、letterbox 预处理位于 `vision/detection_runtime/preprocessing.py`，不再从 NCNN 后端导入私有函数。

应用文件职责与学习顺序见 [应用说明](ballbeam/app/README.md)。本次 task 0 初始化及请求号约定改变了两端语义，虽然帧布局未变，仍需配套更新 Pi 并重新烧录 MCU。

入口：best/run.py → app/main.py::main() → run(args)。通信只创建一个线程，视觉推理不在该线程执行；CSV 记录回调只整理并入队，启用文件采集时共用一个后台写盘线程。main 分别创建 client 和 AngleHistory，用角度回调连接，不相互创建。

通信固定为两种业务模式：先用 0x06 请求、0x86 确认，之后运行模式只交换 0x07/0x84，调参模式只交换 0x08/0x85。0x07 为 21 字节，0x08 为 39 字节；0x84 为 42 字节/20 ms，0x85 为 44 字节/5 ms。原 0x09、通用命令 ACK、任务归零和 handshake.py 已删除。任务和参数通过请求号/版本号去重，执行结果随遥测返回。详细布局、API 和学习入口见 [通信说明](ballbeam/communication/README.md)。

历史两模式协议要求配套 MCU，不能混用旧固件。本次初始化改为 task 0，需重新烧录配套固件。部署时同步完整 `ballbeam/`、`tests/` 与 `SHA256SUMS.txt`，并清理已迁移的旧模块；只用 scp 覆盖不会删除旧文件。现在可显式使用 `--mode run --task-id 1` 或 `--mode tuning --task-id 1`；省略它们时兼容旧命令：--velocity-test 选择调参模式，否则选择运行模式。模式切换只停止正在运行的旧任务，不会自动启动新的运动任务。

## 通过视觉串口触发 Task1

树莓派与下位机更新到配套版本后，在正式视觉命令末尾加 `--task-console`。程序先提示把梁放在机械零位；按 Enter 后经视觉串口请求下位机执行已有的 `task init`（`set_zeropoint` + 当前地面测试 profile 的 `ba 21`），收到确认后才提示输入 `task 1`。确认杆角稳定，输入 `task 1` 并回车，才启动相机和视觉；首个有效视觉反馈就绪时再发送 Task1 请求。运行时打印周期沿用原配置，不再强制放慢。按 `Ctrl+C` 只立即结束树莓派进程，**不会再向下位机发送任何命令**；下位机仍可能继续控制，必须由操作者手动复位，异常时用物理急停。正式运行默认不生成诊断 CSV；纯视觉质量 CSV 采集脚本不自动重设零点。不要另开程序抢占 `/dev/ttyUSB0`。

模式确认后开始周期数据通信。两种模式均用 task 0 初始化；RUN/task 1 是正式任务，TUNING/task 1 是球速阶跃，两者独立解释；request_seq=0 才表示没有任务请求。初始化请求和运动请求都使用非零请求号，回绕时跳过 0。真实任务请求号只在提交新任务时分配；参数配置时 request_seq 置0且不启动动作；之后的新任务请求继续独立计数，不复用初始化请求号。参数版本只在设置参数时改变，相同版本不会每帧重置积分。运行中的速度测试拒绝新参数版本，并在 0x85 中返回失败；结束后需要提交新版本。任务/参数结果查询基于遥测，不再返回通用命令 Future。

需要采集时保留 --task1-csv、--vision-probe-csv 和 --task1-capture-s。Task1 从 0x84（20 ms）记录控制 CSV，速度测试从 0x85（5 ms）记录；不为采集切换业务模式。CSV 旧列保留，发包日志增加 request_seq/mode。采集窗口默认 5 秒，到时仅停写文件，控制仍继续；Ctrl+C 仅退出 Pi，请手动复位 MCU。按 control_ms 去重分析外环更新；vision_seq 仍是传输包序号，不能当作相机测量帧号。所有包的数值单位保持不变，旧历史 CSV 不修改。

下位机仅接受 `[-11,+11] cm` 内的有效位置。越界包被丢弃，不刷新有效视觉时间戳；短暂异常时估计器沿上一有效状态预测，超过原有 100 ms 视觉时限后按失效处理。门限是绝对位置保护，不会把越界值夹到边界，也不会拦截范围内的异常跳变。

## 历史 NCNN 对照

`assets/models/ncnn_model/` 原样取自本地 `_pi_raw/best/model/ncnn_model/`，保留其 `deployment.json` 和真实 `geometry_id=b5db7d686fc4…`。它与生效标定 `8a5cd731dad6…` 不同；重新导出同一份旧 PT 不会改变训练几何。默认仍拒绝这种不一致。仅对这组已核对的历史模型与标定，可在试验命令中显式加 `--allow-historical-ncnn-geometry`；该开关不接受其他 ID 组合，也不修改模型记录。先验证视觉坐标，再考虑 Task1。

原生后端从 `ballbeam/vision/detection_runtime/cpp/` 的历史源码与离线 `ncnn.tar.gz` 构建。树莓派的视觉虚拟环境需要 `pybind11`，并需要系统已有的 CMake 和 Ninja；在 `cpp/` 中运行 `bash build.sh`，生成的 `_ncnn_cpp*.so` 放在上一级 `detection_runtime/`。正式 Hailo 后端仍为默认。当前 `config/runtime.toml` 中 `measurement_center="bbox"` 且 `disable_circle_refinement=true`：Hailo 与 NCNN 均直接取检测框中心，不执行后台圆拟合或复用圆心。NCNN 试验时显式使用 `--inference-backend ncnn --ncnn-backend cpp --allow-historical-ncnn-geometry --exposure-time-absolute 80`。本轮保持 `detection_interval=1`（每帧 YOLO）；OpenCV 光流跟踪留待两种逐帧基线完成后，再单独用 `--detection-interval 2` 对照。

## 部署检查

```bash
cd /home/ikun/vision_workspace/workspace
source /home/ikun/vision_workspace/.venv/bin/activate
sha256sum -c SHA256SUMS.txt
python3 -B -m unittest discover -s tests -v
```

这两项只检查文件和结构，不能代替相机、Hailo 与串口实机测试。

## 标定与验证边界

- 生效 JSON 的 ROI 为 `(128,425,1141,121)`，包含 12、14、…、30°十个样本，`geometry_id=8a5cd731dad6021704fb36f25fd423fa7ecd1634c998e23d7eaf9b13ff81126f`。
- 2405 组封存训练资料记录的是旧 `geometry_id=b5db7d686fc483d125f523499dbbdb9bc71a2d9a2b7f9709992a53b8174de5ad`；历史记录没有被回写。
- HEF 缺少 `deployment.json`，不能自动证明模型与现行标定匹配，只能靠实机图像、坐标和 valid 验证。
- 12–14°视觉已观察正常；补入 12°后尚未重新记录 Task1，不能把修改前结果当作修改后验证。

当前目录由旧 `best/algorithm/`、`ball_detection_*`、DebugPage 和 Wi-Fi 模块按职责整理而来；正式处理流程、HEF 和原始模型 metadata 未因目录整理而更换。原机环境记录在 `RUNTIME_ENVIRONMENT_RASPBERRY_PI.txt`。
