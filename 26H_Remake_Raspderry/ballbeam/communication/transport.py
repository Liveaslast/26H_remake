"""串口字节收发器"""

import serial


class SerialTransport:
    def __init__(self, config):
        self.config = config
        self.port = None
        self.last_error = None

    @property
    def is_open(self):
        return self.port is not None and self.port.is_open

    def open(self):
        self.last_error = None
        self.port = serial.Serial(
            self.config.port, self.config.baudrate,
            timeout=self.config.read_timeout_seconds,
            write_timeout=self.config.write_timeout_seconds,
        )

    def close(self):
        if self.port is not None:
            self.port.close()
            self.port = None

    def read_available(self):
        """Read only bytes already buffered, so RX cannot hold up scheduled TX."""
        if not self.is_open:
            return b""
        try:
            count = min(self.port.in_waiting, 1024)
            return self.port.read(count) if count else b""
        except OSError as exc:
            self.last_error = str(exc)
            return b""

    def write(self, frame):
        if not self.is_open:
            self.last_error = "serial port is not open"
            return False
        try:
            if self.port.write(frame) != len(frame):
                self.last_error = "incomplete serial write"
                return False
        except serial.SerialException as exc:
            self.last_error = str(exc)
            return False
        self.last_error = None
        return True
