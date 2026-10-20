"""Run the actual MCU mode-specific executor with a fake motor controller."""

from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


class PiControlTests(unittest.TestCase):
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
        (folder / "BallBeamController.h").write_text(r'''
#pragma once
class BallBeamController {
public:
    enum class TaskId {Task1 = 1, VelocityStep = 2};
    bool active = false, enabled = false;
    int starts = 0, configs = 0, inits = 0;
    bool isTaskActive() const { return active; }
    void enable() { enabled = true; }
    void start() {}
    void setVelocityTestConfig(float, float, float, float) { ++configs; }
    void initializeTask() { ++inits; active = false; }
    bool startTask(TaskId) { ++starts; active = true; return true; }
};
''', encoding="utf-8")
        harness = folder / "control.cpp"
        harness.write_text(r'''
#include "PiControl.h"
#include <cassert>
#include <cstdlib>
PiControlRequest_t input = {};
bool fresh = true;
unsigned task_success = 99, config_success = 99;
extern "C" bool Communication_GetControlRequest(PiControlRequest_t *r) { *r = input; return true; }
extern "C" bool Communication_GetLatestVisionFrame(VisionFrame_t *v, uint32_t) {
    v->tracking_valid = fresh; return fresh;
}
extern "C" void Communication_ReportSuccess(uint32_t, bool parameters, uint16_t, bool success) {
    if (parameters) config_success = success; else task_success = success;
}
int main(int argc, char **argv) {
    if (argc != 2) return 2;
    BallBeamController motor;
    PiControlExecutor executor(motor);
    input.generation = 1;
    input.mode = COMM_MODE_TUNING;
    input.kp = .5f; input.target_v_cm_s = 2;
    input.request_seq = 1;
    int scenario = std::atoi(argv[1]);
    if (scenario == 1) {
        input.task_id = PI_TUNING_TASK_VELOCITY; input.request_seq = PI_REQUEST_NONE;
        for (int i=0; i<100; ++i) executor.process();
        assert(motor.configs == 1 && config_success == 1 && motor.starts == 0);
    } else if (scenario == 2) {
        input.task_id = PI_TUNING_TASK_VELOCITY; input.request_seq = 1;
        for (int i=0; i<100; ++i) executor.process();
        assert(motor.starts == 1 && motor.configs == 1 && task_success == 1);
        motor.active = false; input.request_seq = 2; executor.process();
        assert(motor.starts == 2);
    } else if (scenario == 3) {
        input.mode = COMM_MODE_RUN; input.task_id = 0;
        for (int i=0; i<100; ++i) executor.process();
        assert(motor.inits == 1 && motor.configs == 0);
        input.generation = 2; executor.process();
        assert(motor.inits == 2);
    } else if (scenario == 4) {
        input.task_id = 2; executor.process();
        assert(motor.starts == 0 && task_success == 0);
    } else if (scenario == 5) {
        input.task_id = PI_TUNING_TASK_VELOCITY; fresh = false; executor.process();
        assert(motor.starts == 0 && task_success == 0);
    } else if (scenario == 6) {
        input.kp = 9; input.task_id = PI_TUNING_TASK_VELOCITY; executor.process();
        assert(motor.configs == 0 && motor.starts == 0 && config_success == 0 && task_success == 0);
    } else if (scenario == 7) {
        input.task_id = PI_TUNING_TASK_VELOCITY; input.request_seq = PI_REQUEST_NONE;
        executor.process();
        motor.active = true; input.revision = 1; executor.process();
        assert(motor.configs == 1 && config_success == 0);
        motor.active = false; input.revision = 2; executor.process();
        assert(motor.configs == 2 && config_success == 1);
    } else if (scenario == 8) {
        input.task_id = 0; input.request_seq = 0;
        for (int i=0; i<100; ++i) executor.process();
        assert(motor.inits == 0 && motor.starts == 0);
        input.mode = COMM_MODE_RUN; ++input.generation;
        for (int i=0; i<100; ++i) executor.process();
        assert(motor.inits == 0 && motor.starts == 0);
    } else if (scenario == 9) {
        input.task_id = 0; input.request_seq = 65535;
        executor.process(); executor.process();
        assert(motor.inits == 1);
        input.request_seq = 1;
        executor.process(); executor.process();
        assert(motor.inits == 2);
    } else if (scenario == 10) {
        input.task_id = 15;
        executor.process();
        assert(motor.inits == 0 && motor.starts == 0 && task_success == 0);
    } else if (scenario == 11) {
        fresh = false; input.task_id = 0;
        executor.process(); executor.process();
        assert(motor.inits == 1 && task_success == 1);
        input.mode = COMM_MODE_RUN; ++input.generation;
        executor.process(); executor.process();
        assert(motor.inits == 2 && task_success == 1);
    } else if (scenario == 12) {
        input.task_id = PI_TASK_INIT;
        executor.process();
        assert(motor.inits == 1 && motor.configs == 0 && config_success == 99);
        input.task_id = 7; input.request_seq = 2;
        executor.process();
        assert(motor.configs == 0 && task_success == 0 && config_success == 99);
    } else if (scenario == 13) {
        input.task_id = PI_TUNING_TASK_VELOCITY; input.request_seq = PI_REQUEST_NONE;
        executor.process();
        assert(motor.configs == 1 && motor.starts == 0 && motor.inits == 0);
        input.request_seq = 2;
        executor.process();
        assert(motor.configs == 1 && motor.starts == 1 && task_success == 1);
    } else if (scenario == 14) {
        input.mode = COMM_MODE_RUN; input.task_id = 1; input.kp = 9;
        executor.process();
        assert(motor.starts == 1 && motor.configs == 0 && task_success == 1 && config_success == 99);
    }
}
''', encoding="utf-8")
        cls.executable = folder / "control.exe"
        result = subprocess.run([compiler, "-std=c++20", "-Wall", "-Wextra",
                                 "-I" + str(folder), "-I" + str(root / "APP/inc"),
                                 str(harness), str(root / "APP/src/PiControl.cpp"),
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
    def test_run_task_one_does_not_use_tuning_task_one_parameters(self): self.scenario(14)
