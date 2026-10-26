"""Run the actual MCU mode-specific executor with a fake motor controller."""

from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

class PiRequestHandlerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        compiler = shutil.which("g++")
        root = Path(__file__).resolve().parents[2] / "26H_Remake_DJC"
        if not compiler or not root.exists():
            raise unittest.SkipTest("Host g++ and MCU source required")
        cls.directory = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.directory.cleanup)
        folder = Path(cls.directory.name)
        (folder / "cmsis_os.h").write_text("typedef void* osMessageQueueId_t;\n")
        (folder / "stm32f4xx_hal.h").write_text(
            "#pragma once\n#include <cstdint>\ninline uint32_t HAL_GetTick() { return 100; }\n")
        (folder / "BallBeamController.h").write_text(r'''
#pragma once
class BallBeamController {
public:
    enum class CtrlType {AngleCtrl};
    bool enabled = false, started = false;
    float motor_angle = 0;
    int angle_commands = 0;
    float commanded_angle = 0;
    void enable() { enabled = true; }
    void start() {}
    float getBalanceAngle() const { return .4f; }
    void Ctrl(CtrlType, float value) { ++angle_commands; commanded_angle = value; }
    struct ControlInputSnapshot { unsigned tick_ms; float x_cm, vx_cm_s, target_v_cm_s; };
    bool getLastControlInput(ControlInputSnapshot*) const { return false; }
#define GETTER(name) float name() const { return 0; }
    GETTER(getBallTarget) GETTER(getBallAngleCommand)
#undef GETTER
};
''', encoding="utf-8")
        (folder / "BallBeamTasks.h").write_text(r'''
#pragma once
#include "BallBeamController.h"
#include "BallStateEstimate.h"
class BallBeamTasks {
public:
    enum class TaskId {Task1 = 1, VelocityStep = 2};
    TaskId last_started_task = TaskId::Task1;
    bool active = false, start_ok = true, config_ok = true;
    int starts = 0, configs = 0, inits = 0, stops = 0;
    BallBeamController& motor;
    explicit BallBeamTasks(BallBeamController& controller) : motor(controller) {}
    bool startTask(TaskId task, const BallStateEstimate_t&, const VisionData_t&, uint32_t) {
        last_started_task = task; ++starts; active = start_ok; return start_ok;
    }
    void initializeTask() { ++inits; active = false; }
    void stopTask() { ++stops; active = false; }
    void stopForModeChange() {
        if (!active) return;
        stopTask(); motor.Ctrl(BallBeamController::CtrlType::AngleCtrl, motor.getBalanceAngle());
    }
    bool isTaskActive() const { return active; }
    bool setVelocityTestConfig(float, float, float, float) {
        if (active || !config_ok) return false;
        ++configs; return true;
    }
    uint8_t getStage() const { return 0; }
};
''')
        harness = folder / "control.cpp"
        harness.write_text(r'''
#include "PiRequestHandler.h"
#include "AppTelemetry.h"
#include "CommunicationTask.h"
#include "BallBeamController.h"
#include "BallBeamTasks.h"
#include "BallStateEstimate.h"
#include <cassert>
#include <cmath>
#include <cstdlib>
#include <deque>
BallBeamController qd_controller;
BallBeamTasks ball_tasks(qd_controller);
BallStateEstimate_t estimate{};
bool has_estimate = false;
extern "C" uint8_t BallStateGetLatest(BallStateEstimate_t* state) {
    if (has_estimate) *state = estimate;
    return has_estimate;
}
PiExecutionRequest_t input = {};
std::deque<PiModeRequest_t> modes;
unsigned mode_replies = 0, last_mode_seq = 0, last_mode = 0, last_mode_result = 9;
unsigned mode_changes = 0;
bool fresh = true;
float vision_x_cm = 0;
bool has_input = true;
unsigned task_success = 99, config_success = 99;
extern "C" bool Communication_ReadExecutionRequest(PiExecutionRequest_t *r) {
    if (!has_input) return false;
    *r = input; return true;
}
extern "C" bool Communication_ReadModeRequest(PiModeRequest_t *r) {
    if (modes.empty()) return false;
    *r = modes.front(); return true;
}
extern "C" void Communication_SaveModeResult(const PiModeRequest_t* r, uint8_t result) {
    assert(!modes.empty() && modes.front().seq == r->seq);
    modes.pop_front();
    ++mode_changes;
    ++input.mode_generation; input.mode = r->mode; input.request_seq = PI_REQUEST_NONE;
    input.task_id = PI_TASK_INIT;
    has_input = false;
    ++mode_replies; last_mode_seq = r->seq; last_mode = r->mode; last_mode_result = result;
}
extern "C" bool Communication_ReadLatestVisionData(VisionData_t *v, uint32_t) {
    v->tracking_valid = fresh; v->x_cm = vision_x_cm; return fresh;
}
extern "C" void Communication_SaveExecutionResult(PiResultKind_t kind, uint16_t, bool success) {
    if (kind == PI_RESULT_PARAMETERS) config_success = success;
    else if (kind == PI_RESULT_TASK) task_success = success;
}
int main(int argc, char **argv) {
    if (argc != 2) return 2;
    BallBeamController motor;
    BallBeamTasks tasks(motor);
    PiRequestHandler executor(tasks);
    input.mode_generation = 1;
    input.mode = COMM_MODE_TUNING;
    input.kp = .5f; input.target_v_cm_s = 2;
    input.request_seq = 1;
    int scenario = std::atoi(argv[1]);
    if (scenario == 1) {
        input.task_id = PI_TUNING_TASK_VELOCITY; input.request_seq = PI_REQUEST_NONE;
        for (int i=0; i<100; ++i) executor.executePendingRequests();
        assert(tasks.configs == 1 && config_success == 1 && tasks.starts == 0);
    } else if (scenario == 2) {
        input.task_id = PI_TUNING_TASK_VELOCITY; input.request_seq = 1;
        for (int i=0; i<100; ++i) executor.executePendingRequests();
        assert(tasks.starts == 1 && tasks.configs == 1 && task_success == 1);
        assert(tasks.last_started_task == BallBeamTasks::TaskId::VelocityStep);
        tasks.active = false; input.request_seq = 2; executor.executePendingRequests();
        assert(tasks.starts == 2);
    } else if (scenario == 3) {
        input.mode = COMM_MODE_RUN; input.task_id = 0;
        for (int i=0; i<100; ++i) executor.executePendingRequests();
        assert(tasks.inits == 1 && tasks.configs == 0);
        input.mode_generation = 2; executor.executePendingRequests();
        assert(tasks.inits == 2);
    } else if (scenario == 4) {
        input.task_id = 2; executor.executePendingRequests();
        assert(tasks.starts == 0 && task_success == 0);
    } else if (scenario == 5) {
        input.task_id = PI_TUNING_TASK_VELOCITY; fresh = false; tasks.start_ok = false;
        executor.executePendingRequests();
        assert(tasks.starts == 1 && task_success == 0);
    } else if (scenario == 6) {
        input.kp = 9; input.task_id = PI_TUNING_TASK_VELOCITY; tasks.config_ok = false;
        executor.executePendingRequests();
        assert(tasks.configs == 0 && tasks.starts == 0 && config_success == 0 && task_success == 0);
    } else if (scenario == 7) {
        input.task_id = PI_TUNING_TASK_VELOCITY; input.request_seq = PI_REQUEST_NONE;
        executor.executePendingRequests();
        tasks.active = true; input.revision = 1; executor.executePendingRequests();
        assert(tasks.configs == 1 && config_success == 0);
        tasks.active = false; input.revision = 2; executor.executePendingRequests();
        assert(tasks.configs == 2 && config_success == 1);
    } else if (scenario == 8) {
        input.task_id = 0; input.request_seq = 0;
        for (int i=0; i<100; ++i) executor.executePendingRequests();
        assert(tasks.inits == 0 && tasks.starts == 0);
        input.mode = COMM_MODE_RUN; ++input.mode_generation;
        for (int i=0; i<100; ++i) executor.executePendingRequests();
        assert(tasks.inits == 0 && tasks.starts == 0);
    } else if (scenario == 9) {
        input.task_id = 0; input.request_seq = 65535;
        executor.executePendingRequests(); executor.executePendingRequests();
        assert(tasks.inits == 1);
        input.request_seq = 1;
        executor.executePendingRequests(); executor.executePendingRequests();
        assert(tasks.inits == 2);
    } else if (scenario == 10) {
        input.task_id = 15;
        executor.executePendingRequests();
        assert(tasks.inits == 0 && tasks.starts == 0 && task_success == 0);
    } else if (scenario == 11) {
        fresh = false; input.task_id = 0;
        executor.executePendingRequests(); executor.executePendingRequests();
        assert(tasks.inits == 1 && task_success == 1);
        input.mode = COMM_MODE_RUN; ++input.mode_generation;
        executor.executePendingRequests(); executor.executePendingRequests();
        assert(tasks.inits == 2 && task_success == 1);
    } else if (scenario == 12) {
        input.task_id = PI_TASK_INIT;
        executor.executePendingRequests();
        assert(tasks.inits == 1 && tasks.configs == 0 && config_success == 99);
        input.task_id = 7; input.request_seq = 2;
        executor.executePendingRequests();
        assert(tasks.configs == 0 && task_success == 0 && config_success == 99);
    } else if (scenario == 13) {
        input.task_id = PI_TUNING_TASK_VELOCITY; input.request_seq = PI_REQUEST_NONE;
        executor.executePendingRequests();
        assert(tasks.configs == 1 && tasks.starts == 0 && tasks.inits == 0);
        input.request_seq = 2;
        executor.executePendingRequests();
        assert(tasks.configs == 1 && tasks.starts == 1 && task_success == 1);
    } else if (scenario == 14) {
        input.mode = COMM_MODE_RUN; input.task_id = 1; input.kp = 9;
        executor.executePendingRequests();
        assert(tasks.starts == 1 && tasks.configs == 0 && task_success == 1 && config_success == 99);
        assert(tasks.last_started_task == BallBeamTasks::TaskId::Task1);
    } else if (scenario == 15) {
        tasks.active = true;
        modes.push_back({42, COMM_MODE_TUNING});
        executor.executePendingRequests(); executor.executePendingRequests();
        assert(tasks.stops == 1 && motor.angle_commands == 1 && motor.commanded_angle == .4f);
        assert(mode_replies == 1 && last_mode_seq == 42 && last_mode == COMM_MODE_TUNING);
        assert(last_mode_result == 0 && tasks.inits == 0 && tasks.starts == 0);
    } else if (scenario == 16) {
        modes.push_back({43, COMM_MODE_RUN});
        executor.executePendingRequests();
        assert(tasks.stops == 0 && motor.angle_commands == 0);
        assert(mode_replies == 1 && last_mode == COMM_MODE_RUN && last_mode_seq == 43);
    } else if (scenario == 17) {
        modes.push_back({44, COMM_MODE_TUNING});
        modes.push_back({45, COMM_MODE_RUN});
        executor.executePendingRequests(); executor.executePendingRequests();
        assert(mode_replies == 2 && last_mode == COMM_MODE_RUN && last_mode_seq == 45);
    } else if (scenario == 18) {
        input.task_id = PI_TUNING_TASK_VELOCITY; input.request_seq = 7;
        executor.executePendingRequests();
        modes.push_back({46, COMM_MODE_RUN});
        executor.executePendingRequests();
        has_input = true; input.task_id = 1; input.request_seq = 7;
        executor.executePendingRequests(); executor.executePendingRequests();
        assert(tasks.starts == 2 && tasks.stops == 1 && tasks.configs == 1);
        assert(tasks.last_started_task == BallBeamTasks::TaskId::Task1);
    } else if (scenario == 19) {
        input.mode = COMM_MODE_RUN; input.task_id = 1;
        tasks.start_ok = false;
        executor.executePendingRequests(); executor.executePendingRequests();
        assert(tasks.starts == 1 && !tasks.active && task_success == 0);
    } else if (scenario == 20) {
        qd_controller.enabled = qd_controller.started = true;
        qd_controller.motor_angle = 1;
        auto sample = CollectAppTelemetry(100);
        assert(sample.x_cm == 0 && sample.vx_cm_s == 0 && sample.vision_age_ms == 9999);
        assert(sample.status == 3 && sample.stm32_time_ms == 100);
        assert(std::fabs(sample.angle_deg - 57.2957795f) < .00001f);
        has_estimate = true; estimate.x_cm = 5; estimate.vx_cm_s = 6;
        estimate.vision_seq = 8; estimate.vision_age_ms = 7;
        sample = CollectAppTelemetry(110);
        assert(sample.x_cm == 5 && sample.vx_cm_s == 6 && sample.vision_seq == 8);
        assert(sample.vision_age_ms == 7 && sample.seq == 0 && sample.request_seq == 0);
    } else if (scenario == 21) {
        input.mode = COMM_MODE_RUN; input.task_id = 1;
        vision_x_cm = 11.01f;
        tasks.start_ok = false;
        executor.executePendingRequests();
        assert(tasks.starts == 1 && task_success == 0);
        vision_x_cm = 0; input.request_seq = 2; tasks.start_ok = true;
        executor.executePendingRequests();
        assert(tasks.starts == 2 && task_success == 1);
    }
}
''', encoding="utf-8")
        cls.executable = folder / "control.exe"
        result = subprocess.run([compiler, "-std=c++20", "-Wall", "-Wextra",
                                 "-I" + str(folder), "-I" + str(root / "APP/inc"), "-I" + str(root / "Application/Communication/inc"), "-I" + str(root / "Application/BallBeam/inc"),
                                 str(harness), str(root / "Application/Communication/src/PiRequestHandler.cpp"),
                                 str(root / "Application/Communication/src/AppTelemetry.cpp"),
                                 "-o", str(cls.executable)], capture_output=True, text=True)
        if result.returncode:
            raise AssertionError(result.stderr)

    def scenario(self, number):
        subprocess.run([str(self.executable), str(number)], check=True, capture_output=True)

    def test_repeated_parameters_are_applied_once(self): self.scenario(1)
    def test_repeated_request_starts_once_new_request_can_restart(self): self.scenario(2)
    def test_mode_entry_resets_request_history(self): self.scenario(3)
    def test_wrong_mode_task_is_rejected(self): self.scenario(4)
    def test_stale_vision_prevents_start(self): self.scenario(5)
    def test_invalid_parameters_prevent_start(self): self.scenario(6)
    def test_running_test_rejects_parameter_revision_without_reset(self): self.scenario(7)
    def test_data_only_packets_never_initialize_in_either_mode(self): self.scenario(8)
    def test_wrapped_nonzero_request_initializes_once(self): self.scenario(9)
    def test_task_15_is_no_longer_initialization(self): self.scenario(10)
    def test_task_zero_initializes_both_modes_without_vision(self): self.scenario(11)
    def test_initialization_and_unknown_tasks_do_not_apply_velocity_parameters(self): self.scenario(12)
    def test_parameter_only_packet_never_starts_motion_until_task_requested(self): self.scenario(13)
    def test_run_request_does_not_apply_tuning_packet_parameters(self): self.scenario(14)
    def test_mode_request_stops_active_task_before_reply(self): self.scenario(15)
    def test_mode_request_does_not_change_idle_motor_target(self): self.scenario(16)
    def test_mode_requests_are_processed_in_order(self): self.scenario(17)
    def test_new_mode_can_reuse_a_previous_request_number(self): self.scenario(18)
    def test_failed_app_start_is_reported_once(self): self.scenario(19)
    def test_app_telemetry_adapter_preserves_units_and_sources(self): self.scenario(20)
    def test_latest_out_of_range_vision_blocks_start_until_a_new_valid_request(self): self.scenario(21)

    def test_executor_does_not_own_business_rules(self):
        root = Path(__file__).resolve().parents[2] / "26H_Remake_DJC"
        header = (root / "Application/Communication/inc/PiRequestHandler.h").read_text(encoding="utf-8")
        source = (root / "Application/Communication/src/PiRequestHandler.cpp").read_text(encoding="utf-8")
        executor = source
        for business_detail in ("controller_.", "BallStateEstimator::", "std::fabs",
                                "request.kp >=", "requires_vision", "isTaskActive()"):
            self.assertNotIn(business_detail, executor)
        self.assertNotIn("BallBeamController&", header)
