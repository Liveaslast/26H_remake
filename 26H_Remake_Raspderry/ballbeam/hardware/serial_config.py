"""Serial device parameters; values are supplied by the application."""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class SerialConfig:
    port: str
    baudrate: int
    read_timeout_seconds: float
    write_timeout_seconds: float
