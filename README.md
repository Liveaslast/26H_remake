# 26H_Remake｜钢球平衡系统

Pi负责视觉与通信，STM32负责估计、任务和电机控制，Support负责资料制作与分析。

| 阅读目的 | 唯一入口 |
|---|---|
| Pi代码与运行 | [Pi README](26H_Remake_Raspderry/README.md) |
| MCU代码与调试 | [MCU README](26H_Remake_DJC/README.md) |
| 标定、采集与分析 | [Support README](26H_Remake_Support/README.md) |
| 跨工程修改边界 | [ARCHITECTURE](ARCHITECTURE.md) |

开发协作遵守 `AGENTS.md`。各工程README可独立阅读，函数细节看源码注释；协议、数据格式和标定步骤按需查阅，不要求读完其它工程。

**实机注意：Pi退出或采集结束不会自动停止MCU。** 历史实验及原始数据不按新实现改写。
