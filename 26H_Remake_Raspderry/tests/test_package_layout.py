"""Package ownership remains clear after consolidating modules, without shims."""

import ast
import importlib.util
from pathlib import Path
import unittest

import ballbeam
from ballbeam.app.tracking import (
    TrackingComponents, build_tracking_components, process_frame, run_tracking_loop,
)
from ballbeam.communication.protocol import FrameDecoder
from ballbeam.communication.session import ModeRequest, DataStream, FrameSender, CommunicationSession
from ballbeam.interfaces.presentation import TrackingDisplay, VisionReporter
from ballbeam.recording.capture import CaptureSession
from ballbeam.recording.csv_recorders import Task1CsvLogger
from ballbeam.recording.csv_writer import CsvWriter
from ballbeam.vision.angles import AngleHistory, FrameAngleSource
from ballbeam.vision.calibration import require_matching_source_roi
from ballbeam.vision.metrics import VisionStats


ROOT = Path(ballbeam.__file__).parent


class PackageLayoutTests(unittest.TestCase):
    def test_components_live_in_their_owning_modules(self):
        owners = {
            "app.tracking": [TrackingComponents, build_tracking_components, process_frame, run_tracking_loop],
            "communication.protocol": [FrameDecoder],
            "communication.session": [ModeRequest, DataStream, FrameSender, CommunicationSession],
            "interfaces.presentation": [TrackingDisplay, VisionReporter],
            "recording.capture": [CaptureSession],
            "recording.csv_recorders": [Task1CsvLogger],
            "recording.csv_writer": [CsvWriter],
            "vision.angles": [AngleHistory, FrameAngleSource],
            "vision.calibration": [require_matching_source_roi],
            "vision.metrics": [VisionStats],
        }
        for module, components in owners.items():
            for component in components:
                with self.subTest(component=component.__name__):
                    self.assertEqual(component.__module__, "ballbeam." + module)

    def test_old_paths_are_removed_not_forwarding_modules(self):
        removed = (
            "app/angle_source.py", "app/frame_angle.py", "app/vision_stats.py",
            "app/display.py", "app/capture.py", "app/csv_recorders.py",
            "app/csv_writer.py", "app/vision_geometry.py",
            "communication/mode.py", "communication/framing.py",
            "app/tasks.py",
            "app/tracking_setup.py", "app/tracking_loop.py",
        )
        for relative in removed:
            with self.subTest(path=relative):
                self.assertFalse((ROOT / relative).exists())
                module = "ballbeam." + relative[:-3].replace("/", ".")
                self.assertIsNone(importlib.util.find_spec(module))

    def test_lower_layers_do_not_import_application_or_unrelated_services(self):
        forbidden = {
            "vision": {"app", "communication", "recording", "hardware", "interfaces"},
            "communication": {"app", "vision", "recording", "interfaces"},
            "recording": {"app", "hardware", "interfaces"},
            "hardware": {"app", "communication", "vision", "recording", "interfaces"},
            "interfaces": {"app", "recording"},
        }
        for layer, dependencies in forbidden.items():
            for path in (ROOT / layer).rglob("*.py"):
                package = "ballbeam." + ".".join(path.relative_to(ROOT).parts[:-1])
                tree = ast.parse(path.read_text(encoding="utf-8"))
                for node in ast.walk(tree):
                    imports = []
                    if isinstance(node, ast.ImportFrom):
                        name = "." * node.level + (node.module or "")
                        base = importlib.util.resolve_name(name, package)
                        imports = [base] + [base + "." + alias.name for alias in node.names]
                    elif isinstance(node, ast.Import):
                        imports = [alias.name for alias in node.names]
                    for name in imports:
                        if name.startswith("ballbeam."):
                            with self.subTest(path=path, dependency=name):
                                self.assertNotIn(name.split(".")[1], dependencies)
