# 26H_Remake｜钢球平衡系统

相机在树莓派上测量球位置，STM32 估计状态并控制电机，Windows Support 负责标定、训练和测试。

| 工程 | 内容 |
|---|---|
| [26H_Remake_Raspderry](26H_Remake_Raspderry/README.md) | 树莓派正式视觉运行包 |
| [26H_Remake_DJC](26H_Remake_DJC/README.md) | STM32 状态估计与控制 |
| [26H_Remake_Support](26H_Remake_Support/README.md) | Windows 资料制作、采集与分析 |

## 当前问题

- 控制方案尚未完成系统的数据对比。
- Hailo 成本较高，视觉方案仍有优化空间。
- 视觉数据质量分析仍需补充。

## 正式启动

在树莓派执行：

```bash
cd ~/vision_workspace/workspace
source ~/vision_workspace/.venv/bin/activate
python3 best/run.py --port /dev/ttyUSB0 --inference-backend hailort --debug-page --serial-read-timeout-ms 1 --wifi-stream --no-display
```

## 文件放置

- 树莓派运行代码、配置、生效标定和 HEF：`26H_Remake_Raspderry/`。
- STM32 代码和构建配置：`26H_Remake_DJC/`。
- ROI、标定、训练、CSV 采集和离线分析：`26H_Remake_Support/`。
- 被 `.gitignore` 排除的本机目录不是现行工程；临时文件不要放仓库根目录。

PT→HEF、固件编译和烧录由项目持有人完成，本仓库不提供通用命令。
