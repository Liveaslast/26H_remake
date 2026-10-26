"""Exercise the real MCU estimator/control code with only motor/RTOS access stubbed."""

from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


class BallBeamControllerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        compiler = shutil.which("g++")
        root = Path(__file__).resolve().parents[2] / "26H_Remake_DJC"
        if not compiler or not root.exists():
            raise unittest.SkipTest("Host g++ and MCU source required")
        cls.directory = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.directory.cleanup)
        folder = Path(cls.directory.name)
        for name in ("BallBeamController.h", "BallBeamController.cpp", "BallBeamTaskProfile.h",
                     "BallStateEstimator.h", "BallStateEstimator.cpp", "BallBeamTasks.h", "BallBeamTasks.cpp"):
            source_dir = "inc" if name.endswith(".h") else "src"
            shutil.copyfile(root / "Application/BallBeam" / source_dir / name, folder / name)
        (folder / "cmsis_os.h").write_text("#pragma once\ntypedef void* osMessageQueueId_t;\n")
        (folder / "FreeRTOS.h").write_text("#pragma once\n")
        (folder / "stm32f4xx_hal.h").write_text('#pragma once\n#include "task.h"\n')
        (folder / "task.h").write_text(
            "#pragma once\n#include <stdint.h>\nextern uint32_t now_ms;\n"
            "inline uint32_t HAL_GetTick() { return now_ms; }\n"
            "#define taskENTER_CRITICAL() ((void)0)\n"
            "#define taskEXIT_CRITICAL() ((void)0)\n")
        (folder / "QDMotorController.h").write_text(r'''
#pragma once
struct QD4310 {};
struct PID {};
class QDMotorController {
public:
    enum class CtrlType {AngleCtrl};
    QDMotorController(QD4310&, const PID&, const PID&, float, float) {}
    float commanded_angle = 0;
    float motor_angle = 0;
    bool enabled = false, started = false;
    bool zero_set = false;
    void Ctrl(CtrlType, float value) { commanded_angle = value; }
    void setZeroPoint() { zero_set = true; }
    void setAngleRateLimit(float) {}
    void enable() { enabled = true; }
    void start() { started = true; }
};
''')
        (folder / "check.cpp").write_text(r'''
#include "BallBeamController.h"
#include "BallStateEstimator.h"
#include "BallBeamTasks.h"
#include "PiRequestHandler.h"
#include "CommunicationTask.h"
#include <algorithm>
#include <cassert>
#include <cmath>
#include <cstdlib>
uint32_t now_ms = 100;
BallStateEstimate_t latest_estimate{};
VisionData_t latest_vision{};
QD4310 global_motor; PID global_pid;
BallBeamController qd_controller(global_motor, global_pid, global_pid, .001f, .3f);
BallBeamTasks ball_tasks(qd_controller);
PiExecutionRequest_t pi_request{};
int task_result = -1, parameter_result = -1;
extern "C" uint8_t BallStateGetLatest(BallStateEstimate_t* state) { *state = latest_estimate; return 1; }
extern "C" bool Communication_ReadExecutionRequest(PiExecutionRequest_t* request) {
    *request = pi_request; return true;
}
extern "C" bool Communication_ReadModeRequest(PiModeRequest_t*) { return false; }
extern "C" void Communication_SaveModeResult(const PiModeRequest_t*, uint8_t) {}
extern "C" bool Communication_ReadLatestVisionData(VisionData_t* value, uint32_t) {
    *value = latest_vision; return true;
}
extern "C" void Communication_SaveExecutionResult(PiResultKind_t kind, uint16_t, bool success) {
    if (kind == PI_RESULT_PARAMETERS) parameter_result = success;
    else task_result = success;
}
void Near(float actual, float expected) { assert(std::fabs(actual - expected) < 1e-5f); }
// Independent reference for the pre-refactor position/velocity equations.
struct ControlReference {
    float position_i = 0, velocity_i = 0, previous_v = 0, acceleration = 0;
    bool has_previous = false;
    float step(const BallBeamControlConfig& config, bool position, float target,
               const BallStateEstimate_t& state, float dt) {
        const auto& g = config.position_velocity;
        float error = position ? target - state.x_cm : 0;
        if (std::fabs(error) < config.x_deadband_cm) error = 0;
        float target_v = target;
        if (position) {
            const float p = g.position_kp_per_s * error;
            const float d = -g.position_kd * state.vx_cm_s;
            const float candidate_i = std::clamp(position_i + error * dt, -10.f, 10.f);
            const float candidate_v = p + d + g.position_ki_per_s2 * candidate_i;
            if (!((candidate_v > g.max_target_velocity_cm_s && error > 0) ||
                  (candidate_v < -g.max_target_velocity_cm_s && error < 0))) position_i = candidate_i;
            target_v = std::clamp(p + d + g.position_ki_per_s2 * position_i,
                                  -g.max_target_velocity_cm_s, g.max_target_velocity_cm_s);
        }
        float measured_acceleration = has_previous ? (state.vx_cm_s - previous_v) / dt : 0;
        previous_v = state.vx_cm_s; has_previous = true;
        acceleration = .75f * acceleration + .25f * measured_acceleration;
        const float p = g.velocity_kp_deg_per_cm_s * (target_v - state.vx_cm_s);
        const float d = -g.velocity_kd_deg_s_per_cm_s * acceleration;
        float correction;
        if (!position) {
            const float candidate_i = std::clamp(velocity_i + g.velocity_ki_deg_per_cm *
                                                 (target_v - state.vx_cm_s) * dt, -2.5f, 2.5f);
            if ((p + candidate_i + d <= 7 || target_v - state.vx_cm_s < 0) &&
                (p + candidate_i + d >= -7 || target_v - state.vx_cm_s > 0)) velocity_i = candidate_i;
            correction = std::clamp(p + velocity_i + d, -7.f, 7.f);
        } else {
            const float feedforward = target * (target >= 0 ? config.feedforward.positive : config.feedforward.negative);
            const float weight = error != 0 && (!g.integral_negative_target_only || target < 0)
                ? std::clamp((g.integral_zero_error_cm - std::fabs(error)) /
                             std::max(.001f, g.integral_zero_error_cm - g.integral_full_error_cm), 0.f, 1.f) *
                  std::clamp((g.integral_zero_speed_cm_s - std::fabs(state.vx_cm_s)) /
                             std::max(.001f, g.integral_zero_speed_cm_s - g.integral_full_speed_cm_s), 0.f, 1.f)
                : 0;
            if (weight == 0) velocity_i *= std::clamp(1 - g.integral_leak_per_s * dt, 0.f, 1.f);
            const float candidate_i = std::clamp(velocity_i + g.velocity_ki_deg_per_cm *
                (target_v - state.vx_cm_s) * weight * dt, -g.max_velocity_integral_deg, g.max_velocity_integral_deg);
            const float feedback = p + candidate_i + d;
            if (!((target_v - state.vx_cm_s > 0 && (feedback > g.max_feedback_angle_deg ||
                  feedforward + feedback > config.angle_command_limit_deg)) ||
                  (target_v - state.vx_cm_s < 0 && (feedback < -g.max_feedback_angle_deg ||
                  feedforward + feedback < -config.angle_command_limit_deg)))) velocity_i = candidate_i;
            correction = feedforward + std::clamp(p + velocity_i + d, -g.max_feedback_angle_deg, g.max_feedback_angle_deg);
        }
        return (config.balance_angle_deg + std::clamp(correction,
            -config.angle_command_limit_deg, config.angle_command_limit_deg)) * .017453292519943295f;
    }
};
BallStateEstimate_t Observe(BallStateEstimator& estimator, uint16_t seq, float x_cm) {
    VisionData_t vision_data{};
    vision_data.seq = seq; vision_data.tracking_valid = 1;
    vision_data.x_cm = x_cm; vision_data.rx_tick_ms = now_ms;
    latest_vision = vision_data;
    estimator.saveVisionMeasurement(vision_data);
    BallStateEstimate_t state{};
    assert(estimator.updateEstimate(now_ms, &state));
    latest_estimate = state;
    return state;
}
int main(int argc, char** argv) {
    if (argc != 2) return 2;
    QD4310 motor; PID pid;
    BallBeamController controller(motor, pid, pid, .001f, .3f);
    BallStateEstimator estimator;
    BallBeamTasks tasks(controller);
    latest_vision.tracking_valid = 1; latest_vision.rx_tick_ms = now_ms;
    int scenario = std::atoi(argv[1]);
    if (scenario == 1) {
        BallStateEstimate_t state{};
        assert(!estimator.updateEstimate(now_ms, &state));
        state = Observe(estimator, 1, 0);
        assert(state.valid && state.vision_seq == 1);
        now_ms = 120;
        state = Observe(estimator, 2, .1f);
        Near(state.x_cm, .035f); Near(state.vx_cm_s, .125f);
        now_ms = 130;
        assert(estimator.updateEstimate(now_ms, &state));
        Near(state.x_cm, .03625f); assert(state.vision_age_ms == 10);
        VisionData_t missing{};
        missing.seq = 3; missing.rx_tick_ms = 140;
        estimator.saveVisionMeasurement(missing);
        now_ms = 140;
        assert(estimator.updateEstimate(now_ms, &state));
        assert(state.valid && state.vision_seq == 2 && state.vision_age_ms == 20);
        now_ms = 221;
        assert(!estimator.updateEstimate(now_ms, &state));
        assert(!state.valid);
    } else if (scenario == 2) {
        Observe(estimator, 1, 0);
        assert(tasks.startTask(BallBeamTasks::TaskId::Task1, latest_estimate, latest_vision, now_ms));
        Near(controller.getBallTarget(), 5);
        BallStateEstimate_t state{}; state.valid = 1;
        tasks.runCurrentTask(state, now_ms);
        controller.updateBalanceControl(state, now_ms);
        BallBeamController::ControlInputSnapshot snapshot{};
        assert(controller.getLastControlInput(&snapshot));
        Near(snapshot.target_v_cm_s, 6);
        Near(controller.getBallAngleCommand(), 28.5f * .017453292519943295f);
        state.x_cm = 5; now_ms += 20;
        tasks.runCurrentTask(state, now_ms);
        controller.updateBalanceControl(state, now_ms);
        Near(controller.getBallTarget(), -5);
        assert(tasks.getStage() == 2);
        state.x_cm = -5; now_ms += 20;
        tasks.runCurrentTask(state, now_ms);
        controller.updateBalanceControl(state, now_ms);
        assert(tasks.getStage() == 0);
        assert(tasks.getActiveTask() == BallBeamTasks::TaskId::Task1);
        state.x_cm = 0; now_ms += 20;
        tasks.runCurrentTask(state, now_ms);
        Near(controller.getBallTarget(), -5);
        assert(!tasks.startTask(BallBeamTasks::TaskId::None, state, latest_vision, now_ms));
        assert(!tasks.startTask(BallBeamTasks::TaskId::VelocityStep, state, latest_vision, now_ms));
        assert(tasks.getActiveTask() == BallBeamTasks::TaskId::Task1);
        tasks.stopTask();
        assert(!tasks.isTaskActive());
        assert(!controller.getLastControlInput(&snapshot));
    } else if (scenario == 3) {
        Observe(estimator, 1, 0);
        tasks.setVelocityTestConfig(.5f, 0, 0, 2);
        assert(tasks.startTask(BallBeamTasks::TaskId::VelocityStep, latest_estimate, latest_vision, now_ms));
        BallStateEstimate_t state{}; state.valid = 1;
        tasks.runCurrentTask(state, now_ms);
        controller.updateBalanceControl(state, now_ms);
        BallBeamController::ControlInputSnapshot snapshot{};
        assert(controller.getLastControlInput(&snapshot));
        Near(snapshot.target_v_cm_s, 2);
        Near(controller.getBallAngleCommand(), 22.f * .017453292519943295f);
        state.x_cm = 6; now_ms += 20;
        tasks.runCurrentTask(state, now_ms);
        controller.updateBalanceControl(state, now_ms);
        assert(!tasks.isTaskActive());
        assert(tasks.getStage() == 12);
        Near(controller.commanded_angle, controller.getBalanceAngle());
        assert(tasks.startVelocityTarget(2, latest_estimate, latest_vision, now_ms));
        state.valid = 0; now_ms += 20;
        tasks.runCurrentTask(state, now_ms);
        controller.updateBalanceControl(state, now_ms);
        assert(!tasks.isTaskActive());
        assert(tasks.getStage() == 13);
    } else if (scenario == 4) {
        tasks.initializeTask();
        assert(controller.zero_set && !tasks.isTaskActive());
        Near(controller.commanded_angle, 21.f * .017453292519943295f);
        controller.setBallPositionPid(1, 0, 0);
        controller.setBallVelocityPid(.5f, 0, 0);
        controller.setBallFeedforwardSplit(0, 0);
        controller.setBallSpeedLimit(3);
        tasks.startPositionTarget(5);
        BallStateEstimate_t state{}; state.valid = 1;
        tasks.runCurrentTask(state, now_ms);
        controller.updateBalanceControl(state, now_ms);
        BallBeamController::ControlInputSnapshot snapshot{};
        assert(controller.getLastControlInput(&snapshot));
        Near(snapshot.target_v_cm_s, 3);
        // Manual setters apply to the current config, without hidden profile overrides.
        Near(controller.getBallAngleCommand(), 22.5f * .017453292519943295f);
    } else if (scenario == 5) {
        VisionData_t vision{};
        vision.tracking_valid = 1;
        vision.seq = 1; vision.x_cm = 11.01f; vision.rx_tick_ms = now_ms;
        assert(!IsVisionMeasurementUsable(vision));
        estimator.saveVisionMeasurement(vision);
        BallStateEstimate_t state{};
        assert(!estimator.updateEstimate(now_ms, &state));

        state = Observe(estimator, 2, -11.f);
        Near(state.raw_x_cm, -11.f);
        now_ms = 120;
        state = Observe(estimator, 3, 11.f);
        Near(state.raw_x_cm, 11.f);
        now_ms = 140;
        vision.seq = 4; vision.x_cm = -11.01f; vision.rx_tick_ms = now_ms;
        estimator.saveVisionMeasurement(vision);
        assert(estimator.updateEstimate(now_ms, &state));
        assert(state.vision_seq == 3 && state.vision_age_ms == 20);
        Near(state.raw_x_cm, 11.f);
        now_ms = 221;
        assert(!estimator.updateEstimate(now_ms, &state) && !state.valid);
    } else if (scenario == 6) {
        BallStateEstimate_t state{}; state.valid = 1;
        state.x_cm = -5; state.update_tick_ms = now_ms;
        assert(tasks.startTask(BallBeamTasks::TaskId::Task1, state, latest_vision, now_ms));
        Near(controller.getBallTarget(), 0);
        assert(tasks.getStage() == 0);
        state.x_cm = 0; now_ms += 20;
        tasks.runCurrentTask(state, now_ms);
        controller.updateBalanceControl(state, now_ms);
        Near(controller.getBallTarget(), 5);
        assert(tasks.getStage() == 1);
    } else if (scenario == 7) {
        BallStateEstimate_t state{}; state.valid = 1; state.update_tick_ms = now_ms;
        tasks.setVelocityTestConfig(.5f, 0, 0, -2);
        state.vision_age_ms = 101;
        assert(!tasks.startTask(BallBeamTasks::TaskId::VelocityStep, state, latest_vision, now_ms));
        state.vision_age_ms = 0;
        assert(tasks.startTask(BallBeamTasks::TaskId::VelocityStep, state, latest_vision, now_ms));
        now_ms += 8000;
        tasks.runCurrentTask(state, now_ms);
        assert(!tasks.isTaskActive() && tasks.getStage() == 13);
        Near(controller.commanded_angle, controller.getBalanceAngle());
    } else if (scenario == 8) {
        BallStateEstimate_t state{}; state.valid = 1; state.x_cm = -5;
        assert(tasks.startTask(BallBeamTasks::TaskId::Task1, state, latest_vision, now_ms));
        tasks.startPositionTarget(3);
        assert(!tasks.isTaskActive() && tasks.getStage() == 0);
        state.x_cm = 0;
        tasks.runCurrentTask(state, now_ms);
        controller.updateBalanceControl(state, now_ms);
        Near(controller.getBallTarget(), 3);
    } else if (scenario == 9) {
        Observe(estimator, 1, 0);
        PiRequestHandler executor(tasks);
        pi_request.mode_generation = 1;
        pi_request.mode = COMM_MODE_TUNING;
        pi_request.task_id = PI_TUNING_TASK_VELOCITY;
        pi_request.kp = .5f; pi_request.target_v_cm_s = 2; pi_request.revision = 1;
        executor.executePendingRequests();
        assert(parameter_result == 1 && task_result == -1 && !tasks.isTaskActive());
        pi_request.request_seq = 7;
        executor.executePendingRequests(); executor.executePendingRequests();
        assert(task_result == 1 && controller.enabled && controller.started);
        assert(tasks.getActiveTask() == BallBeamTasks::TaskId::VelocityStep);
        tasks.runCurrentTask(latest_estimate, now_ms);
        controller.updateBalanceControl(latest_estimate, now_ms);
        Near(controller.getBallAngleCommand(), 22.f * .017453292519943295f);
    } else if (scenario == 10) {
        assert(!estimator.updateEstimate(now_ms, nullptr));
        Observe(estimator, 1, 0);
        now_ms = 120;
        auto state = Observe(estimator, 2, .1f);
        assert(estimator.updateEstimate(now_ms, &state));
        Near(state.x_cm, .035f); Near(state.vx_cm_s, .125f);
        now_ms = 220;
        assert(estimator.updateEstimate(now_ms, &state));
        Near(state.x_cm, .039375f);
        Near(state.filtered_x_cm, state.x_cm);
        now_ms = 221;
        assert(!estimator.updateEstimate(now_ms, &state) && !state.valid);
        Near(state.x_cm, .039375f); Near(state.vx_cm_s, .125f);
        assert(state.vision_age_ms == 101 && state.update_tick_ms == now_ms);
        now_ms = 222;
        assert(!estimator.updateEstimate(now_ms, &state));
        Near(state.vx_cm_s, 0);
        now_ms = 240;
        state = Observe(estimator, 3, 1);
        Near(state.x_cm, 1); Near(state.vx_cm_s, 0);
        assert(state.vision_seq == 3 && state.vision_age_ms == 0);
    } else if (scenario == 11) {
        BallStateEstimator::Config config;
        config.alpha = 1; config.beta = .1f; config.measurement_deadband_cm = 0;
        assert(estimator.configure(config));
        Observe(estimator, 1, 0);
        now_ms = 102;
        auto state = Observe(estimator, 2, .1f);
        Near(state.vx_cm_s, 2);
        now_ms = 104;
        state = Observe(estimator, 3, .2f);
        Near(state.vx_cm_s, 4);
        now_ms = 106;
        state = Observe(estimator, 4, .3f);
        Near(state.vx_cm_s, 5.6666667f);
        now_ms = 108;
        state = Observe(estimator, 5, .4f);
        Near(state.vx_cm_s, 7.6666667f);
    } else if (scenario == 12) {
        PositionSequenceTask position_task(controller);
        BallStateEstimate_t state{};
        state.valid = 1; state.x_cm = -5; state.update_tick_ms = now_ms;
        assert(position_task.start(state, latest_vision, now_ms));
        assert(position_task.getStage() == 0);
        Near(controller.getBallTarget(), 0);
        state.x_cm = 0; now_ms += 20;
        assert(position_task.runCycle(state, now_ms));
        Near(controller.getBallTarget(), 5);
        state.x_cm = 5; now_ms += 20;
        assert(position_task.runCycle(state, now_ms));
        assert(position_task.getStage() == 2);
        Near(controller.getBallTarget(), -5);
        state.x_cm = -5; now_ms += 20;
        assert(position_task.runCycle(state, now_ms));
        assert(position_task.getStage() == 0);
        VelocityTestTask velocity_task(controller);
        velocity_task.configure(.5f, 0, 0, 2);
        state.x_cm = 0; state.update_tick_ms = now_ms;
        assert(velocity_task.start(state, latest_vision, now_ms));
        state.x_cm = 6; now_ms += 20;
        assert(!velocity_task.runCycle(state, now_ms));
        assert(velocity_task.getStage() == 12);
        assert(position_task.getStage() == 0);
        state.x_cm = 0; state.update_tick_ms = now_ms;
        assert(velocity_task.start(state, latest_vision, now_ms));
        state.valid = 0;
        assert(!velocity_task.runCycle(state, now_ms));
        assert(velocity_task.getStage() == 13);
    } else if (scenario == 13) {
        auto state = Observe(estimator, 1, 0);
        assert(!tasks.setVelocityTestConfig(9, 0, 0, 2));
        assert(!tasks.setVelocityTestConfig(.5f, 6, 0, 2));
        assert(!tasks.setVelocityTestConfig(.5f, 0, .3f, 2));
        assert(!tasks.setVelocityTestConfig(.5f, 0, 0, .5f));
        assert(!tasks.setVelocityTestConfig(.5f, 0, 0, NAN));
        assert(tasks.setVelocityTestConfig(.5f, 0, 0, 2));
        latest_vision.tracking_valid = 0;
        assert(!tasks.startTask(BallBeamTasks::TaskId::Task1, state, latest_vision, now_ms));
        assert(!controller.enabled && !controller.started);
        latest_vision.tracking_valid = 1; latest_vision.x_cm = 11.01f;
        assert(!tasks.startTask(BallBeamTasks::TaskId::VelocityStep, state, latest_vision, now_ms));
        latest_vision.x_cm = 0; latest_vision.rx_tick_ms = now_ms - 101U;
        assert(!tasks.startTask(BallBeamTasks::TaskId::Task1, state, latest_vision, now_ms));
        latest_vision.rx_tick_ms = now_ms;
        assert(tasks.startTask(BallBeamTasks::TaskId::VelocityStep, state, latest_vision, now_ms));
        assert(controller.enabled && controller.started);
        assert(!tasks.setVelocityTestConfig(.5f, 0, 0, 3));
        tasks.stopForModeChange();
        assert(!tasks.isTaskActive() && tasks.getStage() == 0);
        Near(controller.commanded_angle, controller.getBalanceAngle());
        tasks.startPositionTarget(3);
        const float angle = controller.commanded_angle;
        tasks.stopForModeChange();
        Near(controller.commanded_angle, angle);
    } else if (scenario == 14) {
        auto state = Observe(estimator, 1, 0);
        assert(tasks.startTask(BallBeamTasks::TaskId::Task1, state, latest_vision, now_ms));
        controller.updateBalanceControl(state, now_ms);
        tasks.stopTask();
        // Saving tuning parameters does not alter the current controller settings.
        assert(tasks.setVelocityTestConfig(2, 0, 0, 2));
        controller.startVelocityControl(2);
        controller.updateBalanceControl(state, now_ms);
        Near(controller.getBallAngleCommand(), 22.048f * .017453292519943295f);
        controller.disableBalance();
        assert(tasks.startTask(BallBeamTasks::TaskId::VelocityStep, state, latest_vision, now_ms));
        controller.updateBalanceControl(state, now_ms);
        Near(controller.getBallAngleCommand(), 25.f * .017453292519943295f);
        tasks.stopForModeChange();
        // Formal task reloads its own gains, not the tuning gains.
        assert(tasks.startTask(BallBeamTasks::TaskId::Task1, state, latest_vision, now_ms));
        controller.updateBalanceControl(state, now_ms);
        Near(controller.getBallAngleCommand(), 28.5f * .017453292519943295f);
        tasks.stopTask();
        // The speed-test task still owns its saved parameters after a formal run.
        assert(tasks.startTask(BallBeamTasks::TaskId::VelocityStep, state, latest_vision, now_ms));
        controller.updateBalanceControl(state, now_ms);
        Near(controller.getBallAngleCommand(), 25.f * .017453292519943295f);
    } else if (scenario == 15) {
        controller.applyControlConfig(BallBeamTaskProfiles::Task1.control);
        controller.setBallVelocityPid(.5f, 0, 0);
        controller.startVelocityControl(0);
        BallStateEstimate_t state{}; state.valid = 1; state.x_cm = 5; state.vx_cm_s = 1;
        controller.updateBalanceControl(state, now_ms);
        Near(controller.getBallAngleCommand(), 20.5f * .017453292519943295f);
        BallBeamController::ControlInputSnapshot before{}, after{};
        assert(controller.getLastControlInput(&before));
        Near(before.target_v_cm_s, 0);
        now_ms += 1;
        state.vx_cm_s = 3;
        controller.updateBalanceControl(state, now_ms);
        assert(controller.getLastControlInput(&after));
        assert(after.tick_ms == before.tick_ms);
        state.valid = 0; now_ms += 20;
        controller.updateBalanceControl(state, now_ms);
        Near(controller.commanded_angle, 20.5f * .017453292519943295f);
        controller.holdBalance();
        assert(!controller.isControlUpdateDue(now_ms));
        Near(controller.commanded_angle, controller.getBalanceAngle());
        assert(controller.getLastControlInput(&after));
        assert(after.tick_ms == before.tick_ms);
        Near(after.vx_cm_s, before.vx_cm_s);
        controller.startVelocityControl(0);
        assert(!controller.getLastControlInput(&after));
    } else if (scenario == 16) {
        for (int policy = 0; policy < 3; ++policy) {
        for (bool position : {false, true}) {
            for (float target : {-5.f, -.5f, .5f, 5.f}) {
                auto config = BallBeamTaskProfiles::Task1.control;
                config.position_velocity.position_ki_per_s2 = .1f;
                config.position_velocity.position_kd = .2f;
                config.position_velocity.velocity_kp_deg_per_cm_s = .75f;
                config.position_velocity.velocity_ki_deg_per_cm = .8f;
                config.position_velocity.velocity_kd_deg_s_per_cm_s = .03f;
                if (policy == 1) {
                    config.position_velocity.integral_negative_target_only = false;
                    config.position_velocity.max_velocity_integral_deg = .3f;
                    config.position_velocity.max_feedback_angle_deg = 2.5f;
                    config.angle_command_limit_deg = 3;
                    config.feedforward = {1.5f, .8f};
                } else if (policy == 2) {
                    config.position_velocity.integral_leak_per_s = 0;
                    config.position_velocity.integral_full_error_cm = .5f;
                    config.position_velocity.integral_zero_error_cm = 2;
                    config.angle_command_limit_deg = 6;
                    config.feedforward = {-.9f, -.45f};
                }
                controller.applyControlConfig(config);
                if (position) controller.startPositionTarget(target);
                else controller.startVelocityControl(target);
                ControlReference reference;
                for (int i = 0; i < 300; ++i) {
                    const uint32_t interval = i % 2 ? 40 : 20;
                    now_ms += interval;
                    BallStateEstimate_t state{}; state.valid = 1;
                    state.x_cm = 6.f * std::sin(i * .09f);
                    state.vx_cm_s = 10.f * std::cos(i * .07f);
                    controller.updateBalanceControl(state, now_ms);
                    const float dt = i == 0 ? .02f : interval * .001f;
                    Near(controller.getBallAngleCommand(), reference.step(config, position, target, state, dt));
                }
            }
        }
        }
    } else return 2;
}
''')
        cls.executable = folder / "check.exe"
        result = subprocess.run([
            compiler, "-std=c++20", "-Wall", "-Wextra", "-Werror",
            "-I" + str(folder), "-I" + str(root / "APP/inc"), "-I" + str(root / "Application/Communication/inc"), "-I" + str(root / "Application/BallBeam/inc"),
            str(folder / "check.cpp"), str(folder / "BallBeamController.cpp"),
            str(folder / "BallStateEstimator.cpp"), str(folder / "BallBeamTasks.cpp"),
            str(root / "Application/Communication/src/PiRequestHandler.cpp"),
            "-o", str(cls.executable),
        ], capture_output=True, text=True)
        if result.returncode:
            raise AssertionError(result.stderr)

    def test_existing_estimator_control_and_task_paths(self):
        for scenario in range(1, 17):
            with self.subTest(scenario=scenario):
                result = subprocess.run([str(self.executable), str(scenario)],
                                        capture_output=True, text=True, timeout=15)
                self.assertEqual(result.returncode, 0, result.stderr)

    def test_controller_does_not_own_estimator_or_task_state(self):
        root = Path(__file__).resolve().parents[2] / "26H_Remake_DJC"
        header = (root / "Application/BallBeam/inc/BallBeamController.h").read_text(encoding="utf-8")
        for old_owner in ("TaskId", "active_task", "ball_sequence", "vision_seq",
                          "vision_x_alpha", "saveVisionMeasurement", "updateBallStateEstimator",
                          "estimated_ball_x_cm", "startTask("):
            self.assertNotIn(old_owner, header)
        task_source = (root / "APP/src/BallStateTask.cpp").read_text(encoding="utf-8")
        for old_dependency in ("BallBeamController", "qd_controller", "BallStateQueue"):
            self.assertNotIn(old_dependency, task_source)
