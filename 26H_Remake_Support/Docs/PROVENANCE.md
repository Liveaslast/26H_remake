# Support 资料来源

## 资料

| 现行位置 | 可追溯来源 |
|---|---|
| **Data/Calibration/active/dynamic_calibration_12_30deg.json** | 与 Raspberry **assets/calibration/dynamic_calibration_12_30deg.json** 内容相同，实际含 12、14、…、30°十样本 |
| **Data/Calibration/angle_12_30deg/** | 从树莓派标定输出保存的十张来源图及十张展开图 |
| **Data/Training/steel_ball_12_30deg_exp10/** | 最初整理自本机历史快照 **_pi_raw/best/algorithm/no_m0/roi_dataset_128x640**；现行目录已自带 2405 张图片、2405 个同名标签及来源记录，不依赖该快照继续存在 |
| **Data/TestRecords/** | 视觉延迟、有效率、座标跳变及 Task1 的实际测试 CSV |

采集 session、逐帧 metadata 与标注原文均保留，不为对齐现行标定而回写历史 geometry ID。资料集脚本可读 **source_records/capture_session.json**，不要求搬动封存文件。生效标定的几何差异与实机验证边界见 [Raspberry PROVENANCE](../../26H_Remake_Raspderry/PROVENANCE.md)。

工具用途不在本文重复维护：视觉入口见 [Vision README](../Vision/README.md)，采集与分析入口见 [Diagnostics README](../Diagnostics/README.md)。可执行入口只在 **APP/**；**Core/**、**IO/**、**Config/** 是内部实现。正式视觉代码由 Raspberry 包单独维护。
