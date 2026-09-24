# Raspberry Pi｜正式视觉运行包

本工程部署到树莓派 **/home/ikun/vision_workspace/workspace**。**best/run.py** 是唯一正式命令入口，调用 **ballbeam.app.main**；不另开第二套相机或识别流程。

| 位置 | 用途 |
|---|---|
| **ballbeam/app/** | 启动、逐帧处理、BALL_STATE 发送 |
| **ballbeam/vision/** | 标定、追踪、检测与 HailoRT 后端 |
| **ballbeam/hardware/** | 相机、串口与角度遥测 |
| **ballbeam/interfaces/** | DebugPage 与 Wi-Fi MJPEG |
| **ballbeam/control/** | 来源代码中的辅助逻辑；闭环控制在 STM32 |
| **config/runtime.toml** | 正式配置 |
| **assets/calibration/** | 生效的 12–30°标定 JSON |
| **assets/models/hailo/** | HEF 和模型 metadata |
| **tests/** | 不接设备的结构测试 |

**best/run.py** 经 **ballbeam/app/main.py** 启动；逐帧处理在 **ballbeam/app/tracking_setup.py** 与 **ballbeam/app/tracking_loop.py**。**ballbeam/vision/detection_runtime/ncnn_backend.py** 含 Hailo 后端共用的图像尺寸与 letterbox 辅助，不能只因正式命令选 Hailo 就删除。

正式配置采用 HailoRT 每帧推理，球坐标取 YOLO bbox 中心；不启用霍夫圆或树莓派 Kalman。代码中的 RANSAC refinement 路径可能执行，但正式球位置仍取 bbox。球状态估计、闭环控制和 Task1 在 STM32 完成。

原始文件映射与标定溯源见 [PROVENANCE.md](PROVENANCE.md)。资料制作和 CSV 工具在 Windows 的 [Support 工程](../26H_Remake_Support/README.md)，不是本包的运行依赖。

## 启动

在树莓派终端依序执行：

1. cd ~/vision_workspace/workspace
2. source ~/vision_workspace/.venv/bin/activate
3. python3 best/run.py --port /dev/ttyUSB0 --inference-backend hailort --debug-page --serial-read-timeout-ms 1 --wifi-stream --no-display

**(vision_ws)** 是提示符名称，实际虚拟环境是 **~/vision_workspace/.venv**。生效 JSON 有 12、14、…、30°十个标定样本，来源 ROI 为 **(128,425,1141,121)**。正式位置已实机启动，12–14°视觉已观察正常；补入 12°后尚未重新记录 Task1 验证。

## 部署检查

下面四行都在**树莓派终端**执行，不是在 Windows 或虚拟机。「包根目录」就是 **/home/ikun/vision_workspace/workspace**；检查所用的 **SHA256SUMS.txt** 和 **tests/** 都在这个目录内。

1. cd /home/ikun/vision_workspace/workspace
2. source /home/ikun/vision_workspace/.venv/bin/activate
3. sha256sum -c SHA256SUMS.txt
4. python3 -B -m unittest discover -s tests -v

第 3 行核对这份部署包的文件是否与清单一致；第 4 行运行不接设备的测试，检查模型、标定文件路径、ROI 和十个角度样本。两者都不能代替相机、Hailo 与串口的实机测试。模型几何 ID 的核对边界见 [PROVENANCE.md](PROVENANCE.md)。
