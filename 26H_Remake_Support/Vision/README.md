# Vision｜视觉资料工具

这些脚本制作 ROI、标定与 YOLO 资料；不替代树莓派正式 **best/run.py**。Windows 保存完整 Support，树莓派需要采图时才按 [命令手册](../Docs/COMMANDS.md)部署 **Vision/**。

| **APP/** 入口 | 执行位置 | 输入 → 结果 |
|---|---|---|
| **select_roi.py** | 树莓派桌面 | USB 相机 → ROI 数值与预览图 |
| **calibrate_geometry.py** | 树莓派桌面 | 角度、轨道角点及位置点 → 动态标定 JSON／检查图 |
| **capture_training_data.py** | 树莓派 | 生效 JSON、相机、角度 → 640×128 图片及会话记录 |
| **annotate_ball.py** | Windows／树莓派桌面 | 未标注图片 → 同名 YOLO bbox TXT |
| **build_yolo_dataset.py** | Windows | 已标注会话 → train/val、**roi_ball.yaml** |
| **train_yolo.py** | Windows | 资料集与基础 PT → **Data/Training/Models/best.pt** |
| **rename_dataset_files.py** | Windows | 成对改名预览；只有 **--apply** 才修改 |

**Config/vision_tools.toml** 保存工具默认值；**Config/config.py** 校验配置，**Config/paths.py** 统一路径。**Core/** 实现几何、采集与资料集流程，**IO/** 提供相机、遥测和人工角度输入；它们不是独立入口。

工具默认标定角度为 12、14、…、30°，相机来源 ROI 与正式 JSON 一致。人工角度输入只用于标定／采图，不进入正式闭环。实际命令、文件位置及 SCP 见 [COMMANDS.md](../Docs/COMMANDS.md)；资料和标注格式见 [DATA_FORMAT.md](../Docs/DATA_FORMAT.md)。

模型存放规则见 [Data/Training/Models/README.md](../Data/Training/Models/README.md)：PT 是训练产物，HEF 才是树莓派 HailoRT 的正式输入；不要因为原始工程另有 NCNN 模型，就把它当作这条正式链路的必要文件。
