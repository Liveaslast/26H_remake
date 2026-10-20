"""Offline architecture checks; no camera, Hailo device, or serial port needed."""

from pathlib import Path
import builtins
import csv
import json
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

import numpy as np

from ballbeam.app.arguments import build_parser, validate_args
from ballbeam.app.task_startup import TASKS
from ballbeam.recording.csv_recorders import BallStateTxLogger, Task1CsvLogger
from ballbeam.app.detector_setup import load_detector
from ballbeam.vision.calibration import require_matching_source_roi
from ballbeam.config import parse_args_with_config
from ballbeam.errors import RuntimeIOError
from ballbeam.communication.client import McuSerialClient
from fake_mcu import start_client, wait_until, telemetry, send_once
from ballbeam.communication.protocol import (
    TUNING_TELEMETRY_FRAME,
    TASK_ID_INIT,
    PI_TUNING_FRAME,
    Mode,
    crc8,
    pack_tuning,
)
from ballbeam.vision.calibration import (
    DynamicCalibration,
    DynamicCalibrationError,
    SourceRoi,
)
from ballbeam.vision.detection_runtime.detector import (
    AdaptiveBallDetector,
    AdaptiveBallDetectorConfig,
)


ROOT = Path(__file__).resolve().parents[1]
SECTIONS = (
    "vision_geometry",
    "tracking",
    "detector",
    "tracker",
    "debug",
    "formal_tracking",
)


class RuntimeStructureTests(unittest.TestCase):
    def test_tuning_packet_includes_vision_and_parameter_revision(self):
        self.assertEqual(PI_TUNING_FRAME.size, 39)
        client, port = start_client(self, Mode.TUNING)
        revision = client.set_velocity_parameters(.5, .1, .02, -5)
        self.assertTrue(send_once(client, 2, 1, True))
        fields = PI_TUNING_FRAME.unpack(port.frames[-1])
        self.assertEqual(fields[4:6], (200, 100))
        self.assertEqual(fields[9:14], (5000, 1000, 200, -500, revision))

    def test_velocity_task_ids_and_cli(self) -> None:
        self.assertEqual(TASK_ID_INIT, 0)
        self.assertEqual(set(TASKS[Mode.TUNING]), {1})
        parser = build_parser()
        args = parse_args_with_config(
            parser, sections=SECTIONS,
            argv=["--task-console", "--velocity-test", "-5",
                  "--task1-csv", "diagnostics/step/control.csv"],
        )
        validate_args(args, parser)

    def test_tuning_task_number_matches_mcu_wire_constant(self):
        import re
        from ballbeam.communication.protocol import TUNING_TASK_VELOCITY
        header = ROOT.parent / "26H_Remake_DJC/APP/inc/CommunicationTask.h"
        if not header.exists():
            self.skipTest("MCU source is not included in this deployment")
        match = re.search(r"PI_TUNING_TASK_VELOCITY\s*=\s*(\d+)", header.read_text(encoding="utf-8"))
        self.assertIsNotNone(match)
        self.assertEqual(TUNING_TASK_VELOCITY, int(match.group(1)))

    def test_velocity_step_reuses_task1_sample_and_csv(self) -> None:
        self.assertEqual(TUNING_TELEMETRY_FRAME.size, 44)
        client, serial_port = start_client(self, Mode.TUNING)
        samples = []
        client.record_control_sample = samples.append
        packet = TUNING_TELEMETRY_FRAME.pack(
            0x5A, 0x85, 0x80, 7, 100, 0, 200, 2200, 2300,
            0, 0, 0, 10, 12, 5, 110, 190, 500, 1234, 1235, 0, 0, 0,
        )
        serial_port.incoming.put(packet[:-1] + bytes((crc8(packet[:-1]),)))
        wait_until(lambda: len(samples) == 1)
        self.assertEqual(len(samples), 1)
        self.assertAlmostEqual(samples[0].target_v, 5.0)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "control.csv"
            logger = Task1CsvLogger(path, duration_seconds=2.0)
            logger.start()
            logger.publish(samples[0])
            logger.close()
            with path.open(newline="", encoding="utf-8") as handle:
                rows = list(csv.DictReader(handle))
        self.assertEqual(rows[0]["phase"], "speed_step")
        self.assertEqual(rows[0]["target_v"], "5.0")

    def test_ball_state_tx_log_matches_written_packet(self) -> None:
        client, serial_port = start_client(self)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "ball_state_tx.csv"
            logger = BallStateTxLogger(path)
            client.record_sent_frame = logger.publish
            self.assertTrue(send_once(client, 12.6066, 0.0, True))
            self.assertTrue(send_once(client, 4.4422, -1.0, True))
            logger.close()
            with path.open(newline="", encoding="utf-8") as handle:
                rows = list(csv.DictReader(handle))
        self.assertEqual([row["seq"] for row in rows], ["0", "1"])
        self.assertEqual([row["position_001cm"] for row in rows], ["1261", "444"])
        self.assertEqual(rows[0]["tracking_valid"], "1")
        self.assertEqual(len(serial_port.frames), 2)
        self.assertEqual(len(serial_port.frames[0]), 21)

    def test_task1_sample_decodes_exact_control_input(self) -> None:
        self.assertEqual(TUNING_TELEMETRY_FRAME.size, 44)
        client, serial_port = start_client(self, Mode.TUNING)
        samples = []
        client.record_control_sample = samples.append
        packet = TUNING_TELEMETRY_FRAME.pack(
            0x5A, 0x85, 0, 1, 100, 500, 20, 2200, 2650,
            -400, 0, 1, 1, 12, 5, 105, 25, 200, 1234, 1235, 0, 0, 0,
        )
        serial_port.incoming.put(packet[:-1] + bytes((crc8(packet[:-1]),)))
        wait_until(lambda: len(samples) == 1)
        self.assertEqual(len(samples), 1)
        self.assertEqual(samples[0].control_tick_ms, 1234)
        self.assertAlmostEqual(samples[0].control_x, 1.05)
        self.assertAlmostEqual(samples[0].control_v, 0.25)
        self.assertAlmostEqual(samples[0].target_v, 2.0)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "control.csv"
            logger = Task1CsvLogger(path)
            logger.start()
            logger.publish(samples[0])
            logger.close()
            with path.open(newline="", encoding="utf-8") as handle:
                rows = list(csv.DictReader(handle))
            self.assertEqual(rows[0]["control_ms"], "1234")
            self.assertEqual(rows[0]["control_x"], "1.05")
            self.assertEqual(rows[0]["control_v"], "0.25")
            self.assertEqual(rows[0]["target_v"], "2.0")

    def test_formal_config_resolves_existing_assets(self) -> None:
        args = parse_args_with_config(build_parser(), sections=SECTIONS, argv=[])
        self.assertEqual(args.calibration, ROOT / "assets/calibration/dynamic_calibration_12_30deg.json")
        self.assertEqual(args.hailo_model, ROOT / "assets/models/hailo")
        self.assertTrue(args.calibration.is_file())
        self.assertTrue((args.hailo_model / "best.hef").is_file())
        self.assertTrue((args.model / "model.ncnn.param").is_file())
        self.assertTrue((args.model / "model.ncnn.bin").is_file())
        self.assertTrue(args.disable_circle_refinement)
        self.assertEqual(args.detection_interval, 1)

    def test_bbox_only_skips_circle_refinement(self) -> None:
        class FakeModel:
            def predict(self, **_kwargs):
                class Boxes:
                    xyxy = np.array([[10, 20, 30, 40]], dtype=np.float32)
                    conf = np.array([0.9], dtype=np.float32)
                    cls = np.array([0], dtype=np.float32)

                    def __len__(self):
                        return len(self.xyxy)

                boxes = Boxes()
                return [SimpleNamespace(boxes=boxes)]

        def unexpected_refinement(*_args):
            raise AssertionError("circle refinement must be disabled")

        detector = AdaptiveBallDetector(
            AdaptiveBallDetectorConfig(
                image_size=(128, 640), detection_interval=1,
                enable_circle_refinement=False,
            ),
            model=FakeModel(), circle_refiner=unexpected_refinement,
        )
        result = detector.detect(np.zeros((128, 640, 3), dtype=np.uint8))
        self.assertEqual(result.balls[0].center_px, (20.0, 30.0))
        self.assertEqual(result.balls[0].source, "yolo_box")
        self.assertEqual(result.refined_count, 0)
        self.assertEqual(result.refinement_ms, 0.0)

    def test_config_roi_matches_actual_calibration(self) -> None:
        args = parse_args_with_config(build_parser(), sections=SECTIONS, argv=[])
        calibration = DynamicCalibration.load(args.calibration)
        configured = SourceRoi(
            args.source_roi_x,
            args.source_roi_y,
            args.source_roi_width,
            args.source_roi_height,
        )
        self.assertEqual(configured.xywh, (128, 425, 1141, 121))
        require_matching_source_roi(calibration.source_roi, configured)

    def test_active_calibration_has_real_12_to_30_degree_samples(self) -> None:
        calibration = DynamicCalibration.load(
            ROOT / "assets/calibration/dynamic_calibration_12_30deg.json"
        )
        self.assertEqual(
            tuple(sample.angle_deg for sample in calibration.samples),
            tuple(float(angle) for angle in range(12, 31, 2)),
        )
        self.assertEqual(calibration.angle_range_deg, (12.0, 30.0))
        state = calibration.state_for_angle(12.0)
        self.assertEqual((state.lower_angle_deg, state.upper_angle_deg), (12.0, 12.0))

    def test_mismatched_roi_is_rejected(self) -> None:
        calibration = DynamicCalibration.load(
            ROOT / "assets/calibration/dynamic_calibration_12_30deg.json"
        )
        with self.assertRaises(DynamicCalibrationError):
            require_matching_source_roi(
                calibration.source_roi,
                SourceRoi(129, 422, 1143, 124),
            )

    def test_hailort_import_failure_does_not_switch_backend(self) -> None:
        args = parse_args_with_config(build_parser(), sections=SECTIONS, argv=[])
        calibration = DynamicCalibration.load(args.calibration)
        original_import = builtins.__import__

        def fail_adaptive_detector(name, *args, **kwargs):
            if "detection_runtime.detector" in name:
                raise ImportError("simulated missing detector")
            return original_import(name, *args, **kwargs)

        with patch("builtins.__import__", side_effect=fail_adaptive_detector):
            with self.assertRaisesRegex(RuntimeIOError, "拒绝静默切换"):
                load_detector(
                    args,
                    (1000, 200),
                    calibration_geometry_id=calibration.geometry_id,
                )

    def test_historical_ncnn_geometry_requires_explicit_flag(self) -> None:
        args = parse_args_with_config(
            build_parser(), sections=SECTIONS,
            argv=["--inference-backend", "ncnn", "--ncnn-backend", "cpp"],
        )
        calibration = DynamicCalibration.load(args.calibration)
        with self.assertRaisesRegex(RuntimeIOError, "不一致"):
            load_detector(
                args,
                (1000, 200),
                calibration_geometry_id=calibration.geometry_id,
            )

    def test_explicit_historical_ncnn_geometry_keeps_provenance(self) -> None:
        args = parse_args_with_config(
            build_parser(), sections=SECTIONS,
            argv=[
                "--inference-backend", "ncnn",
                "--ncnn-backend", "cpp",
                "--allow-historical-ncnn-geometry",
            ],
        )
        calibration = DynamicCalibration.load(args.calibration)
        with patch(
            "ballbeam.vision.detection_runtime.ncnn_backend.native_ncnn_available",
            return_value=True,
        ):
            detector = load_detector(
                args,
                (1000, 200),
                calibration_geometry_id=calibration.geometry_id,
            )
        self.assertIsNotNone(detector)
        self.assertEqual(
            json.loads((args.model / "deployment.json").read_text(encoding="utf-8"))["geometry_id"],
            "b5db7d686fc483d125f523499dbbdb9bc71a2d9a2b7f9709992a53b8174de5ad",
        )
        with self.assertRaisesRegex(RuntimeIOError, "不一致"):
            load_detector(
                args,
                (1000, 200),
                calibration_geometry_id="another-calibration-id",
            )


if __name__ == "__main__":
    unittest.main()
