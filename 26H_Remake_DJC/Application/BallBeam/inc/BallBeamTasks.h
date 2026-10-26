#ifndef BALL_BEAM_TASKS_H
#define BALL_BEAM_TASKS_H

#include "BallBeamController.h"
#include "VisionData.h"

// 具体任务的共同入口；普通函数调用，不创建RTOS任务，不做PID计算。
class BallBeamTask {
public:
    virtual ~BallBeamTask() = default;
    virtual bool start(const BallStateEstimate_t& state, const VisionData_t& vision, uint32_t now_ms) = 0;
    // 执行本轮任务逻辑；true表示继续运行，false表示已结束。
    virtual bool runCycle(const BallStateEstimate_t& state, uint32_t now_ms) = 0;
    virtual uint8_t getStage() const = 0;
};

// 正式任务：必要时先回中心，再执行+5cm、-5cm，最后保持目标位置。
class PositionSequenceTask final : public BallBeamTask {
public:
    explicit PositionSequenceTask(BallBeamController& controller) : controller_(controller) {}
    bool start(const BallStateEstimate_t& state, const VisionData_t& vision, uint32_t now_ms) override;
    bool runCycle(const BallStateEstimate_t& state, uint32_t now_ms) override;
    uint8_t getStage() const override;

private:
    enum class Phase : uint8_t { ReturningToCenter, FirstTarget, SecondTarget, HoldingPosition };
    BallBeamController& controller_;
    Phase phase_{Phase::HoldingPosition};
};

// 速度测试：保存测试参数，检查启动条件，并负责测试边界、超时及退出。
class VelocityTestTask final : public BallBeamTask {
public:
    explicit VelocityTestTask(BallBeamController& controller) : controller_(controller) {}
    bool start(const BallStateEstimate_t& state, const VisionData_t& vision, uint32_t now_ms) override;
    bool runCycle(const BallStateEstimate_t& state, uint32_t now_ms) override;
    uint8_t getStage() const override;
    bool setTargetVelocity(float target_v_cm_s);
    bool configure(float kp, float ki, float kd, float target_v_cm_s);

private:
    void finish(bool aborted);
    enum class Phase : uint8_t { Running = 10U, Finished = 12U, Aborted = 13U };
    BallBeamController& controller_;
    Phase phase_{Phase::Finished};
    float target_velocity_cm_s_{0.0f};
    float velocity_kp_{0.5f};
    float velocity_ki_{0.0f};
    float velocity_kd_{0.0f};
    uint32_t start_ms_{0U};
};

// 选择、启动和停止当前任务；具体阶段与退出规则由对应任务对象负责。
class BallBeamTasks {
public:
    enum class TaskId : uint8_t { None = 0U, Task1 = 1U, VelocityStep = 2U };

    explicit BallBeamTasks(BallBeamController& controller)
        : controller_(controller), position_task_(controller), velocity_task_(controller) {}
    bool startTask(TaskId task, const BallStateEstimate_t& state, const VisionData_t& vision, uint32_t now_ms);
    void initializeTask();
    void stopTask();
    // 切换通信模式时结束活动任务并下达平衡角；不等待机械到位。
    void stopForModeChange();
    // GimbalTask周期调用，统一运行当前任务；调用者不判断具体任务阶段。
    void runCurrentTask(const BallStateEstimate_t& state, uint32_t now_ms);
    void startPositionTarget(float target_x_cm);
    bool startVelocityTarget(float target_v_cm_s, const BallStateEstimate_t& state,
                             const VisionData_t& vision, uint32_t now_ms);
    bool setVelocityTestConfig(float kp, float ki, float kd, float target_v_cm_s);
    TaskId getActiveTask() const { return active_task_; }
    bool isTaskActive() const { return active_task_ != TaskId::None; }
    uint8_t getStage() const;

private:
    BallBeamController& controller_;
    PositionSequenceTask position_task_;
    VelocityTestTask velocity_task_;
    // 结束后保留对象以查询最终阶段；active_task_为None时不再运行。
    BallBeamTask* selected_task_{nullptr};
    TaskId active_task_{TaskId::None};
    bool profile_loaded_{false};
};

#endif
