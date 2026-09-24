# 26H_Remake｜钢球平衡系统

相机在树莓派上产生球坐标，STM32 接收后估计状态、控制电机，Windows 工具负责资料制作与测试记录。三部分分开维护，正式运行不依赖训练图片或诊断脚本。

| 工程 | 职责 | 阅读入口 |
|---|---|---|
| [26H_Remake_Raspderry](26H_Remake_Raspderry/README.md) | 树莓派相机、12–30°动态标定、HailoRT 识别、串口发送小球坐标与速度 | [运行说明](26H_Remake_Raspderry/README.md) |
| [26H_Remake_DJC](26H_Remake_DJC/README.md) | STM32 α-β滤波、电机控制、回传电机角度 | [下位机模组导航](26H_Remake_DJC/README.md)；编译与烧录由项目持有人完成 |
| [26H_Remake_Support](26H_Remake_Support/README.md) | ROI／标定／训练资料制作，以及 CSV 采集与分析 | [工具与资料入口](26H_Remake_Support/README.md) |

## 运行

树莓派正式部署目录是 **/home/ikun/vision_workspace/workspace**，Python 虚拟环境独立位于 **/home/ikun/vision_workspace/.venv**。**(vision_ws)** 只是终端提示名称。

在树莓派终端依序执行以下三行：

1. cd ~/vision_workspace/workspace
2. source ~/vision_workspace/.venv/bin/activate
3. python3 best/run.py --port /dev/ttyUSB0 --inference-backend hailort --debug-page --serial-read-timeout-ms 1 --wifi-stream --no-display

模型缺少可自动核对几何 ID 的 **deployment.json**；详见 [来源与验证边界](26H_Remake_Raspderry/PROVENANCE.md)。

## 按任务阅读

- 从 ROI、采图走到模型与 Task1：[Support 总览](26H_Remake_Support/README.md)与[操作命令](26H_Remake_Support/Docs/COMMANDS.md)。
- 执行命令、平台和输出路径：[命令手册](26H_Remake_Support/Docs/COMMANDS.md)。
- CSV 每列的含义：[资料格式](26H_Remake_Support/Docs/DATA_FORMAT.md)。
- 想复用架构：先看 [树莓派工程](26H_Remake_Raspderry/README.md) 与 [下位机工程](26H_Remake_DJC/README.md)，再按新机构替换 ROI、标定、模型及串口配置；不要把本机构的 JSON／HEF 直接当通用模板。

PT→HEF 在本地虚拟机完成，本仓库不提供该步命令。固件编译与烧录也由项目持有人完成。Windows Support 保存 2405 组 12–30°已标注图片及可追溯的标定资料；树莓派正式运行不需要这些原始资料。
