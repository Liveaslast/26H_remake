# 模型训练产物

这里保存 Windows 训练所得的 PyTorch 权重，不参与树莓派正式运行。

| 文件或目录 | 用途 |
|---|---|
| **best.pt** | 最佳训练权重；交给本地虚拟机转成 HEF |
| **best.pt.geometry.json** | 新版训练脚本生成的几何旁车文件；现有旧 PT 没有，勿臆造 |
| **last.pt** | 下次训练生成时保存最后一轮权重；目前没有 |
| **Runs/** | 下次训练生成的日志与结果 |
| **ncnn_model/** | 仅在实际导出、测试 NCNN 时才建立 |

现有 **best.pt** 复制自 **D:\Linux_system\VM_share\best.pt**，其内部训练资料路径指向 **roi_ball_128x640_angle12/roi_ball.yaml**。旧镜像 NCNN 部署记录也指向该资料集，其 **geometry_id** 为 **b5db7d68…74de5ad**；这是来源线索，并非从此 PT 直接读到的 ID。现行树莓派标定 ID 不同，不要为消除警告而补写不实的模型几何 ID。

转换完成的正式模型位于兄弟工程 **26H_Remake_Raspderry/assets/models/hailo/best.hef**。树莓派正式工作空间只需要 HEF，不需要这里的 PT、训练日志或 NCNN。
