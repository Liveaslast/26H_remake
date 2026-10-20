# 视觉工作链

正式入口由 app/tracking.py 组装和运行，视觉模块不访问串口，也不负责电机闭环控制。未使用的 Pi control/balance.py 和 control/__init__.py 已删除。

## 按处理节点阅读

```text
相机图像 + 图像时刻 + 对应电机角度
    → DynamicCalibration.rectify()：展开图像及坐标映射
    → detector.detect()：输出像素检测结果
    → CandidateSelector.select()：筛选目标并换算厘米坐标
    → TrackingState.observe()：更新确认、丢失和已有可选估计状态
    → DynamicTrackingResult：视觉结果及诊断数据
    → BallStateBuilder.update()：按明确来源生成最终 BallState
    → app/main.py 调用 client.publish_ball_state()
```

DynamicBallTracker.process() 只组织前四个节点及结果交付。图像获取、角度匹配属于 app/tracking.py 的循环调用，不由 tracker 自己取图或读串口。

## 检测节点：只处理像素空间

文件：detection_runtime/detector.py。

| 组件 | 输入及输出 | 状态归属 |
|---|---|---|
| ModelInference.predict | 展开图像 → 模型候选框及推理耗时 | 加载的模型后端 |
| OpticalFlowTracker.track | 展开图像 → 光流追踪框及质量 | 前帧图像、特征点、跟踪框 |
| CircleRefinementCache.refine | 图像、候选框 → 可选的拟合中心/半径及缓存复用结果 | 拟合结果与关联缓存 |
| AdaptiveBallDetector.detect | 按配置选择推理帧或光流帧，返回 AdaptiveFrameDetection | 帧计数与是否要求重新检测 |

上层通过 detect(frame) 使用检测节点，不需要知道 HailoRT、NCNN 或光流细节。默认构造不变；替换算法时可显式传入 inference、flow、refinement 组件，不需要修改 detect() 的调度流程。组件接口分别是 predict、reset/initialize/track、reset/refine。

这些组件仍放在同一文件，避免按代码片段增加文件。模型选择和部署检查仍在 app/detector_setup.py，后端实现仍在各自 backend 模块，共享预处理仍归 preprocessing.py。

## 跟踪节点：物理测量和时序状态分开

文件：tracker.py。

| 组件 | 责任 | 明确不做 |
|---|---|---|
| CandidateSelector | 置信度、中心带、半径、物理范围、关联门限筛选；像素到厘米换算 | 不拥有滤波器、连续命中或丢失历史 |
| BallMeasurement | 保存所选目标、物理位置、评分及像素几何信息 | 不运行算法 |
| TrackingState | 确认次数、丢失历史、时间顺序；管理原有可选 Kalman/低通 | 不展开图像、不调用检测器、不画图 |
| TrackingStatus | 保存本帧位置、速度、有效性、丢失时间及原因 | 不包含图像处理逻辑 |
| DynamicBallTracker | 调用标定、检测、筛选、状态接口，组装 DynamicTrackingResult | 不包含候选筛选细节、绘图或串口逻辑 |

CandidateSelector.select() 的预测位置和丢失时间是显式输入。它不读取 TrackingState 内部对象。没有启用 Kalman 时，TrackingState 不创建 Kalman 和速度低通对象，位置仍采用测量值、速度仍保持原来默认输出0；不是本轮新增速度估计或滤波。

DynamicBallTracker 保留 process、process_missing_angle、reset 对外接口，也可以通过 selector、state 构造参数替换对应节点。默认配置、候选规则和有效性规则未改变。

## 数据与绘图出口

- DynamicTrackingResult 保留测量、跟踪输出、图像与耗时等诊断字段。
- ball_state.py 的 measurement_state 明确选择当前测量来源；BallStateBuilder 可替换 state_source，且不重新读取原始字段覆盖处理后的输出。
- 最终控制输入是 BallState(position_cm, velocity_cm_s, valid, measured_at)，通信层不需要理解检测器或滤波器。
- draw_tracking_overlay 已移到 interfaces/presentation.py，TrackingDisplay 调用它。tracker.py 不再导入 cv2 或包含绘图函数，vision 包也不再导出绘图接口。
- 控制闭环仍在 STM32，本次没有改下位机固件或通信协议。

## 以后修改应落在哪里

| 修改需求 | 主要修改节点 |
|---|---|
| 更换推理模型后端 | ModelInference/对应后端及 detector_setup 的组装 |
| 修改光流算法 | OpticalFlowTracker 或替换 flow 实例 |
| 修改圆心拟合和复用 | CircleRefinementCache 或替换 refinement 实例 |
| 修改目标筛选、关联评分 | CandidateSelector |
| 修改确认与丢失规则、已有状态估计 | TrackingState |
| 添加最终发送前的视觉处理 | ball_state.py 中的 state_source，保持 BallState 含义不变 |
| 修改画面叠加 | interfaces/presentation.py |

新增一种算法不等于保证零配置修改，但不应因此修改 client、session、transport 或 MCU 帧解析。
