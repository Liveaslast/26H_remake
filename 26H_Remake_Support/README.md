# Support｜资料制作与测试

Support 是 Windows 上的可复用工具与资料库，不参与树莓派正式视觉进程。正式运行包是同级 [26H_Remake_Raspderry](../26H_Remake_Raspderry/README.md)；下位机代码在 [26H_Remake_DJC](../26H_Remake_DJC/)。

| 位置 | 用途 |
|---|---|
| **Vision/APP/** | ROI、标定、采图、框选、资料集整理与训练入口 |
| **Vision/Config、Core、IO/** | 视觉工具的配置与实现 |
| **Diagnostics/APP/** | CSV 采集、Task1 测试与分析入口 |
| **Diagnostics/Core、IO/** | 诊断工具的实现 |
| **Data/Calibration/** | 生效标定参考副本、来源图与展开图 |
| **Data/Training/** | 12–30°图片、YOLO 标签和采集记录 |
| **Data/Training/Models/** | 训练所得 PT；HEF 不放在这里 |
| **Data/TestRecords/** | 视觉／控制测试 CSV |
| **Docs/** | 命令、字段、流程与来源 |

## 工作顺序与入口

树莓派选 ROI、标定并采图 → Windows Support 框选、整理资料集、训练 PT → 本地虚拟机转换 HEF → 树莓派正式视觉与 STM32 任务 → Windows CSV 诊断。

树莓派只负责识别并发送球状态；STM32 负责估计、电机控制和 Task1。Windows 采集的下位机 CSV 与树莓派逐帧 probe 可用于区分识别、传输和控制问题。

视觉工具见 [Vision/README.md](Vision/README.md)，CSV 与 Task1 工具见 [Diagnostics/README.md](Diagnostics/README.md)。按步执行见 [COMMANDS.md](Docs/COMMANDS.md)，数据字段见 [DATA_FORMAT.md](Docs/DATA_FORMAT.md)；来源与取舍见 [PROVENANCE.md](Docs/PROVENANCE.md)。

## 资料与部署边界

- 正式标定在树莓派 **~/vision_workspace/workspace/assets/calibration/dynamic_calibration_12_30deg.json**；本目录 **Data/Calibration/active** 是内容相同的 Windows 参考副本。JSON 实际包含 12、14、…、30°十个样本。
- **Data/Training/steel_ball_12_30deg_exp10** 封存 2405 组 640×128 图片与同名 YOLO 标签。原始 **capture_session.json** 保留采集时的几何 ID，不为匹配现行 JSON 而改写。
- 需要在树莓派重新选 ROI、标定或拍摄时，从 Windows 按需部署 **Vision/**；平时正式运行只需 **workspace**、顶层 **.venv** 及设备／驱动。
- PT→HEF 在本地虚拟机完成；固件编译和烧录由项目持有人完成，这两步不在 Support 脚本中。
- 已有的 **best.pt** 保存在 **Data/Training/Models/**，与树莓派正式运行的 **26H_Remake_Raspderry/assets/models/hailo/best.hef** 分开。NCNN 只在需要验证该后端时才导出。

来源文件及整理取舍见 [PROVENANCE.md](Docs/PROVENANCE.md)。
