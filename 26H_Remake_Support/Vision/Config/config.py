"""Load documented vision-tool defaults from TOML before parsing CLI options.

The checked-in ``config.toml`` is the single source of tunable defaults.  A
custom file passed with ``--config`` may contain only the sections or values it
wants to override.  Command-line options are parsed last and therefore always
win over both files.
"""

from __future__ import annotations

import argparse
from pathlib import Path
import sys
import tomllib
from typing import Any, Iterable, Sequence


CONFIG_DIR = Path(__file__).resolve().parent
DEFAULT_CONFIG_PATH = CONFIG_DIR / "vision_tools.toml"
CONFIG_VERSION = 1
FORBIDDEN_CONFIG_KEYS = frozenset({"enable_balance_control", "clear_estop"})

# Keeping the section names explicit catches misspellings in hand-edited files.
KNOWN_SECTIONS = frozenset(
    {
        "vision_geometry",
        "tracking",
        "detector",
        "tracker",
        "control",
        "debug",
        "formal_tracking",
        "manual_tracking",
        "calibration",
        "formal_calibration",
        "manual_calibration",
        "roi_capture",
        "training",
        "dataset_prepare",
        "ncnn_export",
    }
)


class AlgorithmConfigError(ValueError):
    """The TOML parameter file is missing, malformed, or inconsistent."""


def add_config_argument(parser: argparse.ArgumentParser) -> None:
    """Add the common parameter-file option to an application parser."""

    parser.add_argument(
        "--config",
        type=Path,
        default=DEFAULT_CONFIG_PATH,
        help=(
            "TOML参数文件；未指定时加载Vision/Config/vision_tools.toml。"
            "命令行显式参数优先于文件值"
        ),
    )


def _read_document(path: Path) -> dict[str, Any]:
    try:
        with path.open("rb") as stream:
            document = tomllib.load(stream)
    except FileNotFoundError as exc:
        raise AlgorithmConfigError(f"参数文件不存在：{path}") from exc
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise AlgorithmConfigError(f"无法读取参数文件 {path}：{exc}") from exc

    version = document.pop("version", None)
    if version != CONFIG_VERSION:
        raise AlgorithmConfigError(
            f"参数文件version必须为{CONFIG_VERSION}，实际为{version!r}：{path}"
        )
    unknown_sections = sorted(set(document) - KNOWN_SECTIONS)
    if unknown_sections:
        raise AlgorithmConfigError(
            "参数文件包含未知分组：" + ", ".join(unknown_sections)
        )
    for name, section in document.items():
        if not isinstance(section, dict):
            raise AlgorithmConfigError(f"参数分组[{name}]必须是TOML表")
    return document


def _resolve_config_path(path: Path, *, base: Path) -> Path:
    expanded = path.expanduser()
    if not expanded.is_absolute():
        expanded = base / expanded
    return expanded.resolve()


def _coerce_scalar(
    action: argparse.Action,
    value: Any,
    *,
    config_dir: Path,
    source: str,
) -> Any:
    expected = action.type
    try:
        if expected is Path:
            if not isinstance(value, str):
                raise TypeError("路径必须写成字符串")
            converted = _resolve_config_path(Path(value), base=config_dir)
        elif expected is int:
            if not isinstance(value, int) or isinstance(value, bool):
                raise TypeError("必须是整数")
            converted = value
        elif expected is float:
            if not isinstance(value, (int, float)) or isinstance(value, bool):
                raise TypeError("必须是数值")
            converted = float(value)
        elif expected is str or expected is None:
            if not isinstance(value, str):
                raise TypeError("必须是字符串")
            converted = value
        else:
            converted = expected(value)
    except (TypeError, ValueError) as exc:
        raise AlgorithmConfigError(
            f"参数{source}.{action.dest}类型错误：{exc}"
        ) from exc

    if action.choices is not None and converted not in action.choices:
        choices = ", ".join(repr(item) for item in action.choices)
        raise AlgorithmConfigError(
            f"参数{source}.{action.dest}必须是以下值之一：{choices}"
        )
    return converted


def _coerce_value(
    action: argparse.Action,
    value: Any,
    *,
    config_dir: Path,
    source: str,
) -> Any:
    # store_true/store_false/BooleanOptionalAction all have nargs == 0.
    if action.nargs == 0:
        if not isinstance(value, bool):
            raise AlgorithmConfigError(f"参数{source}.{action.dest}必须是布尔值")
        return value

    if action.__class__.__name__ == "_AppendAction":
        if not isinstance(value, list):
            raise AlgorithmConfigError(f"参数{source}.{action.dest}必须是数组")
        return [
            _coerce_scalar(
                action,
                item,
                config_dir=config_dir,
                source=source,
            )
            for item in value
        ]

    if isinstance(value, (dict, list)):
        raise AlgorithmConfigError(f"参数{source}.{action.dest}必须是单个值")
    return _coerce_scalar(
        action,
        value,
        config_dir=config_dir,
        source=source,
    )


def _defaults_from_document(
    parser: argparse.ArgumentParser,
    document: dict[str, Any],
    *,
    path: Path,
    sections: Iterable[str],
) -> dict[str, Any]:
    actions = {
        action.dest: action
        for action in parser._actions
        if action.dest not in {"help", "config"}
    }
    defaults: dict[str, Any] = {}
    for section_name in sections:
        section = document.get(section_name, {})
        for key, value in section.items():
            if key in FORBIDDEN_CONFIG_KEYS:
                raise AlgorithmConfigError(
                    f"安全开关[{section_name}].{key}不能持久化，必须在命令行显式指定"
                )
            action = actions.get(key)
            if action is None:
                raise AlgorithmConfigError(
                    f"参数[{section_name}].{key}不适用于当前命令"
                )
            defaults[key] = _coerce_value(
                action,
                value,
                config_dir=path.parent,
                source=section_name,
            )
    return defaults


def parse_args_with_config(
    parser: argparse.ArgumentParser,
    *,
    sections: Sequence[str],
    argv: Sequence[str] | None = None,
) -> argparse.Namespace:
    """Load built-in defaults, overlay ``--config``, then parse the CLI.

    Relative paths inside a TOML file are resolved from that file's directory,
    so commands work identically from ``best/``, ``formal/``, or another cwd.
    """

    invalid_sections = sorted(set(sections) - KNOWN_SECTIONS)
    if invalid_sections:
        raise ValueError("unknown requested config sections: " + ", ".join(invalid_sections))

    options = list(sys.argv[1:] if argv is None else argv)
    probe = argparse.ArgumentParser(add_help=False)
    probe.add_argument("--config", type=Path, default=DEFAULT_CONFIG_PATH)
    selected, _ = probe.parse_known_args(options)
    selected_path = _resolve_config_path(selected.config, base=Path.cwd())

    try:
        built_in_document = _read_document(DEFAULT_CONFIG_PATH)
        defaults = _defaults_from_document(
            parser,
            built_in_document,
            path=DEFAULT_CONFIG_PATH,
            sections=sections,
        )
        if selected_path != DEFAULT_CONFIG_PATH.resolve():
            override_document = _read_document(selected_path)
            defaults.update(
                _defaults_from_document(
                    parser,
                    override_document,
                    path=selected_path,
                    sections=sections,
                )
            )
    except AlgorithmConfigError as exc:
        parser.error(str(exc))

    parser.set_defaults(config=selected_path, **defaults)
    args = parser.parse_args(options)
    # An explicitly supplied relative --config is parsed again by argparse;
    # preserve the already-normalized path used above.
    args.config = selected_path
    print(
        f"Config loaded: {selected_path}; sections={','.join(sections)}",
        flush=True,
    )
    return args
