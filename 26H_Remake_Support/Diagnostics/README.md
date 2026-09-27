# Diagnostics｜采集与分析

诊断工具在正式视觉之外采集和分析数据，不改识别或下位机控制逻辑。Windows 执行串口采集和离线分析；Pi 的 vision probe 使用同一正式 **best/run.py**，额外写逐帧 CSV。

| **APP/** 入口 | 平台 | 用途 |
|---|---|---|
| **capture_mcu_csv.py** | Windows | 采集 USART6 的 **vision** 或 **control** 行，附主机时间 |
| **capture_vision_csv.sh** | 树莓派，按需部署 | 启动正式视觉并打开 probe；也可直接使用命令手册的正式命令 |
| **capture_vision_quality.sh** | 树莓派，按需部署 | 依次采集当前正式视觉的10 s静止与20 s自然运动probe，曝光可显式覆盖，结果集中写入diagnostics |
| **capture_motion_quality.sh** | 树莓派，按需部署 | 只采集自然运动probe，适合光照或曝光单项复测 |
| **analyze_vision_probe.py** | Windows | 单份 probe 的帧率、valid、更新间隔与座标事件 |
| **analyze_vision.py** | Windows | 对齐 Pi probe 与 STM32 vision CSV |
| **initialize_zero.py** | Windows | 发送 **task init** 设定下位机零点 |
| **run_task1.py**、**analyze_task1.py** | Windows | 启动／记录及按约5 ms数据分析Task1；支持通过已有串口命令临时覆盖BBP/BPUSH |

**capture_mcu_csv.py** 的 **--mode** 决定是否顺便发 **ba 22**／**task 1**；**--firmware-csv** 决定下位机打印 **vision**、**control** 或关闭。两者互不等价。固件启动默认为 **control**；切到 **vision** 后，Task1 前要切回 **control**。

**control** 与 **vision** 固件 CSV 均按 5 ms 打印。probe 则是树莓派每处理完一帧所写的观测，记录耗时、bbox／球位置、valid 与角度；它不是串口收包，也不表示逐帧发包。比较 probe、下位机 vision 与 control，才能区分识别、传输和控制端的问题。

完整命令见 [COMMANDS.md](../Docs/COMMANDS.md)，逐列定义见 [DATA_FORMAT.md](../Docs/DATA_FORMAT.md)。**Core/** 和 **IO/** 是入口依赖，不直接运行。清理后 **~/vision_workspace/diagnostics** 可在下次 probe 采集前重新建立。

`capture_vision_quality.sh`默认保持正式配置的数值10。可用环境变量显式设置：

```bash
EXPOSURE_TIME_ABSOLUTE=20 STATIC_DURATION=10 MOTION_DURATION=20 bash /home/ikun/vision_workspace/capture_vision_quality.sh
```

本摄像头已核实该控件单位为100 us，因此10是1 ms、20是2 ms。脚本把数值写入session，并将结果目录命名为`vision_quality_exp20_<时间戳>`。静态和动态CSV都用同一个`analyze_vision_probe.py`分析。

Task1本轮的逐步定位、失败试验、最终临时参数和剩余边界见 [TASK1_TUNING_EXPERIENCE.md](TASK1_TUNING_EXPERIENCE.md)。特别注意：串口覆盖不会自动写回固件默认profile。
