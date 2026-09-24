# 生效标定

**dynamic_calibration_12_30deg.json** 是正式 **best/run.py** 载入的标定文件；实际含 12、14、…、30°十个角度，来源 ROI 为 **(128,425,1141,121)**。每个样本的四角点与位置映射系数已在 JSON 中，没有另外制造点位 TXT。

Windows [Support 标定资料](../../../26H_Remake_Support/Data/Calibration/) 保留相同 JSON 的参考副本、十张来源图和十张展开图。重新标定应在连接实际相机与机构的树莓派上完成；新结果先作为独立资料验证，不会自动替换本文件。来源与几何 ID 见 [PROVENANCE.md](../../PROVENANCE.md)。
