# 26H_Remake｜钢球平衡系统

相机在树莓派上测量球位置，STM32 估计状态并控制电机，Windows Support 负责标定、训练和测试。

| 工程 | 内容 |
|---|---|
| [26H_Remake_Raspderry](26H_Remake_Raspderry/README.md) | 树莓派正式视觉运行包 |
| [26H_Remake_DJC](26H_Remake_DJC/README.md) | STM32 状态估计与控制 |
| [26H_Remake_Support](26H_Remake_Support/README.md) | Windows 资料制作、采集与分析 |

## Markdown 文件说明

不需要按顺序读完。先看与你当前任务对应的“入口”；参考和记录只在需要时打开。

| 类型 | 文件 | 什么时候看 |
|---|---|---|
| 总入口 | `README.md`（本页） | 了解三工程分工、正式启动和文件放置 |
| 工程入口 | [Raspberry README](26H_Remake_Raspderry/README.md) | 部署或运行树莓派视觉，检查标定、模型和验证边界 |
| 工程入口 | [DJC README](26H_Remake_DJC/README.md) | 查找 STM32 通信、估计、控制和调试代码 |
| 工程入口 | [Support README](26H_Remake_Support/README.md) | 做 ROI、标定、训练、Task1 或视觉诊断；操作命令都从这里开始 |
| 兼容跳转 | [Vision README](26H_Remake_Support/Vision/README.md) | 仅提醒视觉工具统一看 Support README，不含另一套说明 |
| 字段参考 | [DATA_FORMAT.md](26H_Remake_Support/Docs/DATA_FORMAT.md) | 不理解 control、vision 或 probe CSV 某一列时查看 |
| 来源档案 | [PROVENANCE.md](26H_Remake_Support/Docs/PROVENANCE.md) | 追溯标定、训练资料和测试记录从哪里来；不是操作说明 |
| 数据说明 | [训练资料 README](26H_Remake_Support/Data/Training/steel_ball_12_30deg_exp10/README.md) | 核对 2405 组图片、标签和历史 geometry ID |
| 数据说明 | [模型 README](26H_Remake_Support/Data/Training/Models/README.md) | 区分 PT、HEF、训练产物和部署模型 |
| 实验记录 | [Task1 调参复盘](26H_Remake_Support/Data/TestRecords/TASK1_TUNING_20260927.md) | 复查 2026-09-27 的具体调参证据；不是日常操作前置阅读 |
| 实验记录 | [暗场视觉分析](26H_Remake_Support/Data/TestRecords/vision_quality_exp10_20260921_094539/vision_quality_summary.md) | 查看 1 ms 暗场视觉质量基线 |
| 实验记录 | [亮光视觉分析](26H_Remake_Support/Data/TestRecords/vision_quality_exp10_bright_20260921_100725/analysis_summary.md) | 查看提高照明后的对比结果 |

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
