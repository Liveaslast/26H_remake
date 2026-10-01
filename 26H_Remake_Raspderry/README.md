# Raspberry Pi｜正式视觉运行包

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
| `ballbeam/app/` | 启动、逐帧处理和 BALL_STATE 发送 |
| `ballbeam/vision/` | 标定、追踪、检测与 HailoRT 后端 |
| `ballbeam/hardware/` | 相机、串口与角度遥测 |
| `ballbeam/interfaces/` | DebugPage 与 Wi-Fi MJPEG |
| `config/runtime.toml` | 正式配置 |
| `assets/calibration/` | 生效的 12–30°标定 JSON |
| `assets/models/hailo/` | 正式 HEF 与模型 metadata |

正式配置使用 HailoRT，球位置取 YOLO bbox 中心；不启用霍夫圆或 Pi Kalman。状态估计、闭环控制和 Task1 均在 STM32 完成。`ncnn_backend.py` 仍包含 Hailo 共用的图像尺寸与 letterbox 代码，不能因正式后端是 Hailo 就删除。

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
