# 运行包来源与校验边界

正式入口保持 **python3 best/run.py**，主流程现位于 **ballbeam/app/main.py**。本地来源采集 **_pi_raw_new** 曾与树莓派正式来源逐档核对；原机 Python/HailoRT 环境记录在 **RUNTIME_ENVIRONMENT_RASPBERRY_PI.txt**。

| 来源位置 | 现行位置 |
|---|---|
| **best/algorithm/formal/track_ball.py** | **ballbeam/app/main.py** |
| **best/algorithm/{app,core,io,control}/** | **ballbeam/{app,vision,hardware,control}/** |
| **ball_detection_common/**、**ball_detection_runtime/** | **ballbeam/vision/detection_common/**、**detection_runtime/** |
| **best/debug_page/**、**best/WIFI_test/** | **ballbeam/interfaces/debug_page/**、**wifi_stream/** |
| **best/algorithm/config.toml** | **config/runtime.toml** |
| **best/algorithm/calibration_data/** | **assets/calibration/** |
| **best/algorithm/hailo_model/** | **assets/models/hailo/** |

正式命令的处理流程、HEF 与模型原始 metadata 未因目录整理而更换。配置中的来源 ROI 已对齐标定 JSON 的 **(128,425,1141,121)**，并恢复相等检查；旧配置曾写 **(129,422,1143,124)**，但实际裁切一直由 JSON 决定。这是历史差异，不是要使用两套 ROI。

## 12–30°标定

生效 **assets/calibration/dynamic_calibration_12_30deg.json** 来自树莓派原始标定输出，**samples** 实际包含 12、14、…、30°十个角度，**geometry_id=8a5cd731dad6021704fb36f25fd423fa7ecd1634c998e23d7eaf9b13ff81126f**。补入 12°时，14–30°九个原样本及 ROI 均未变；12°采用本身样本，12–14°之间插值。Windows Support 保存相同 JSON 的参考副本和十组来源／展开图。

封存的 2405 组训练资料记录采集时的 **geometry_id=b5db7d686fc483d125f523499dbbdb9bc71a2d9a2b7f9709992a53b8174de5ad**，未回写。HEF 未重新编译，模型包也没有 **deployment.json** 可自动核对几何 ID；不能只凭 ID 差异推断模型好坏。

## 已验证与未验证

- 树莓派：部署包 49 项 SHA-256、5 项离线测试通过；12–14°测试工作区视觉及正式 **workspace** 视觉由使用者确认正常。
- Task1：在补入 12°标定前曾跑通；本次修改后未重跑。实际 Task1 电机不进入 12°，但不应把先前结果记作修改后的新测试。
- 模型几何：缺 **deployment.json**，只能靠实机图像、坐标及 valid 验证，不能宣称自动匹配。
