"""One declaration drives CLI creation and final CLI/TOML value validation."""

from contextlib import redirect_stdout, redirect_stderr
import io
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from ballbeam.app import arguments


class ArgumentTests(unittest.TestCase):
    def parse(self, argv):
        with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            return arguments.parse_runtime_args(argv)

    def test_new_option_requires_only_one_declaration(self):
        declaration = (("--test-value",), dict(type=int, default=3, check=lambda v: v > 0))
        with patch.object(arguments, "ARGUMENTS", arguments.ARGUMENTS + (declaration,)):
            self.assertEqual(self.parse([]).test_value, 3)
            self.assertEqual(self.parse(["--test-value", "5"]).test_value, 5)
            with self.assertRaises(SystemExit):
                self.parse(["--test-value", "0"])

    def test_every_float_option_rejects_nonfinite_cli_input(self):
        for flags, spec in arguments.ARGUMENTS:
            if spec.get("type") is not float:
                continue
            for value in ("nan", "inf", "-inf"):
                with self.subTest(option=flags[0], value=value), self.assertRaises(SystemExit):
                    self.parse([flags[0] + "=" + value])

    def test_numeric_ranges_and_multiples(self):
        invalid = (("--fps", "0"), ("--width", "1"), ("--confidence", "1.1"),
                   ("--model-width", "65"), ("--image-size", "-32"),
                   ("--serial-read-timeout-ms", "0"), ("--velocity-kp", "5"),
                   ("--wifi-port", "65536"), ("--ball-state-send-rate-hz", "49"))
        for option, value in invalid:
            with self.subTest(option=option), self.assertRaises(SystemExit):
                self.parse([option, value])
        self.assertEqual(self.parse(["--model-width", "64"]).model_width, 64)
        self.assertEqual(self.parse(["--image-size", "0"]).image_size, 0)

    def test_parameter_relationships_are_checked(self):
        invalid = (
            ["--task1-csv", "control.csv"],
            ["--velocity-test", "2"],
            ["--maximum-lost-ms", "100", "--reset-after-ms", "50"],
            ["--vertical-band-min", ".8", "--vertical-band-max", ".2"],
            ["--kalman-minimum-dt-ms", "10", "--kalman-maximum-dt-ms", "5"],
            ["--source-roi-x", "999999"],
        )
        for argv in invalid:
            with self.subTest(argv=argv), self.assertRaises(SystemExit):
                self.parse(argv)

    def test_toml_uses_same_ranges_and_cli_can_override_values(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "override.toml"
            path.write_text('version = 1\n[tracking]\nfps = -1.0\n', encoding="utf-8")
            with self.assertRaises(SystemExit):
                self.parse(["--config", str(path)])
            self.assertEqual(self.parse(["--config", str(path), "--fps", "60"]).fps, 60)
            path.write_text('version = 1\n[tracking]\nfps = nan\n', encoding="utf-8")
            with self.assertRaises(SystemExit):
                self.parse(["--config", str(path)])

    def test_choices_aliases_and_boolean_pairs_are_preserved(self):
        args = self.parse(["--process-acceleration-std-cm-s2", "5", "--display",
                           "--lock-dynamic-framerate", "--no-debug-page"])
        self.assertEqual(args.process_acceleration_std_cm_s2, 5)
        self.assertFalse(args.no_display)
        self.assertFalse(args.allow_dynamic_framerate)
        self.assertFalse(args.debug_page)
        with self.assertRaises(SystemExit):
            self.parse(["--inference-backend", "unknown"])
