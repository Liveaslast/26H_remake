# 12–30°钢球 YOLO 资料

**by_angle/angle_\*** 分成 12、14、…、30°十组，共 2405 张 640×128 PNG 和 2405 个同名标签；采集曝光值为 10，类别是 **0 steel_ball**。

| 位置 | 内容 |
|---|---|
| **by_angle/&lt;角度&gt;/images/** | 已选用的训练图片 |
| **by_angle/&lt;角度&gt;/labels/** | 同名 YOLO TXT，每行 **class_id center_x center_y width height**，座标归一化 |
| **by_angle/&lt;角度&gt;/source_records/** | 原始会话与逐帧 metadata，用于溯源，不回写 |

TXT 保存 bbox 的中心与宽高，并非四个顶点。资料由树莓派采集、在 Windows 标注；正式 Pi 视觉只载入已编译的 HEF，不读这些 PNG／TXT。

**Vision/APP/build_yolo_dataset.py** 可直接把各个 **by_angle/angle_\*** 目录作为 **--source**。脚本优先读会话根目录的 **session.json**，否则读封存的 **source_records/capture_session.json**；既有采集记录的 geometry ID 保持原样。2405 组配对与内部几何一致性已核对，但这不等于模型与现行十样本 JSON 能靠 ID 自动匹配。命令见 [COMMANDS.md](../../../Docs/COMMANDS.md)，来源见 [PROVENANCE.md](../../../Docs/PROVENANCE.md)。
