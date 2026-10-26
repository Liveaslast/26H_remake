"""真实估计任务的配置与最新结果交接，不加载电机驱动或连接设备。"""

from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


class BallStateTaskTests(unittest.TestCase):
    def test_estimator_config_and_invalid_results_cross_the_task_boundary(self):
        compiler = shutil.which("g++")
        root = Path(__file__).resolve().parents[2] / "26H_Remake_DJC"
        if not compiler or not root.exists():
            self.skipTest("Host g++ and MCU source required")
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            (folder / "FreeRTOS.h").write_text("#pragma once\n")
            (folder / "cmsis_os.h").write_text(
                "#pragma once\n#include <cstdint>\n"
                "uint32_t osKernelGetTickCount();\nvoid osDelayUntil(uint32_t);\n")
            (folder / "task.h").write_text(
                "#pragma once\n#include <cassert>\ninline int depth = 0;\n"
                "#define taskENTER_CRITICAL() do { assert(depth == 0); ++depth; } while (0)\n"
                "#define taskEXIT_CRITICAL() do { assert(depth == 1); --depth; } while (0)\n")
            harness = folder / "check.cpp"
            harness.write_text(r'''
#include "BallStateTask.h"
#include "CommunicationTask.h"
#include <cassert>
#include <cmath>
unsigned now_ms = 100, rounds = 0;
VisionData_t vision{0.f, 0.f, 1, 1, 100, 100};
uint32_t osKernelGetTickCount() { return now_ms; }
extern "C" bool Communication_ReadLatestVisionData(VisionData_t* value, uint32_t age) {
    assert(age == 0); *value = vision; return true;
}
struct Stop {};
void osDelayUntil(uint32_t) {
    BallStateEstimate_t state{};
    assert(BallStateGetLatest(&state));
    ++rounds;
    if (rounds == 1) {
        assert(state.valid && state.x_cm == 0 && state.vision_seq == 1);
        auto config = BallStateGetEstimatorConfig();
        config.alpha = 1; config.beta = .5f;
        assert(BallStateSetEstimatorConfig(config));
        config.beta = -1;
        assert(!BallStateSetEstimatorConfig(config));
        assert(BallStateGetEstimatorConfig().beta == .5f);
        now_ms = 120;
        vision.x_cm = .1f; vision.seq = 2; vision.rx_tick_ms = now_ms;
    } else if (rounds == 2) {
        assert(state.valid && std::fabs(state.x_cm - .1f) < 1e-5f);
        assert(std::fabs(state.vx_cm_s - 2.5f) < 1e-5f);
        now_ms = 130; vision.tracking_valid = 0;
    } else if (rounds == 3) {
        assert(state.valid && state.vision_seq == 2 && state.vision_age_ms == 10);
        assert(std::fabs(state.x_cm - .125f) < 1e-5f);
        now_ms = 221;
    } else {
        assert(!state.valid && state.vision_age_ms == 101);
        throw Stop{};
    }
}
int main() {
    BallStateEstimate_t state{};
    assert(!BallStateGetLatest(&state) && !BallStateGetLatest(nullptr));
    try { BallStateTask(nullptr); } catch (Stop&) {}
    assert(rounds == 4);
}
''')
            executable = folder / "check.exe"
            result = subprocess.run([
                compiler, "-std=c++20", "-Wall", "-Wextra", "-Werror",
                "-I" + str(folder), "-I" + str(root / "APP/inc"), "-I" + str(root / "Application/Communication/inc"), "-I" + str(root / "Application/BallBeam/inc"),
                str(harness),
                str(root / "APP/src/BallStateTask.cpp"),
                str(root / "Application/BallBeam/src/BallStateEstimator.cpp"), "-o", str(executable),
            ], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            result = subprocess.run([str(executable)], capture_output=True, text=True, timeout=15)
            self.assertEqual(result.returncode, 0, result.stderr)
