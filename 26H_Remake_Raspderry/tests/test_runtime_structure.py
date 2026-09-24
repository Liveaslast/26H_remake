"""Offline architecture checks; no camera, Hailo device, or serial port needed."""

from pathlib import Path
import builtins
import unittest
from unittest.mock import patch

from ballbeam.app.main import build_parser
from ballbeam.app.tracking_support import load_detector
from ballbeam.app.vision_geometry import require_matching_source_roi
from ballbeam.config import parse_args_with_config
from ballbeam.hardware.runtime import RuntimeIOError
from ballbeam.vision.calibration import (
    DynamicCalibration,
    DynamicCalibrationError,
    SourceRoi,
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
    def test_formal_config_resolves_existing_assets(self) -> None:
        args = parse_args_with_config(build_parser(), sections=SECTIONS, argv=[])
        self.assertEqual(args.calibration, ROOT / "assets/calibration/dynamic_calibration_12_30deg.json")
        self.assertEqual(args.hailo_model, ROOT / "assets/models/hailo")
        self.assertTrue(args.calibration.is_file())
        self.assertTrue((args.hailo_model / "best.hef").is_file())

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


if __name__ == "__main__":
    unittest.main()
