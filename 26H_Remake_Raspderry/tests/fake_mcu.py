"""In-memory serial endpoint for the single communication thread tests."""

from queue import Empty, Queue
import threading
import time
from unittest.mock import patch

from ballbeam.communication.client import McuSerialClient
from ballbeam.communication.protocol import (
    Mode, RUN_TELEMETRY_FRAME, TUNING_TELEMETRY_FRAME, MODE_REPLY_FRAME, crc8,
)


def mode_reply(seq, mode=Mode.RUN, result=0):
    frame = MODE_REPLY_FRAME.pack(0x5A, 0x86, seq, mode, result, 0)
    return frame[:-1] + bytes((crc8(frame[:-1]),))


def telemetry(status=0, seq=1, angle=-1200, *, mode=Mode.RUN,
              request_seq=0, revision=0):
    layout = RUN_TELEMETRY_FRAME if mode == Mode.RUN else TUNING_TELEMETRY_FRAME
    fields = (0x5A, 0x84 if mode == Mode.RUN else 0x85, status, seq,
              100, 500, 200, angle, 2300, 10, 12, 5,
              110, 190, 500, 1234, 1235, request_seq)
    if mode == Mode.TUNING:
        fields += (revision,)
    frame = layout.pack(*fields, 0)
    return frame[:-1] + bytes((crc8(frame[:-1]),))


def wait_until(predicate, timeout=1.0):
    deadline = time.perf_counter() + timeout
    while time.perf_counter() < deadline:
        if predicate():
            return
        time.sleep(0.001)
    raise AssertionError("condition was not satisfied before timeout")


def send_once(client, position, velocity, valid):
    """Exercise packet writing on the real worker without a production-only API."""
    def send(ball):
        client.session.stream.publish_vision(*ball)
        return client.session.sender.send_data(client.session.mode.current_mode, client.session.stream)
    client.session._handlers["test_send"] = send
    return client.session.call("test_send", (position, velocity, valid))


class FakeSerial:
    def __init__(self):
        self.is_open = True
        self.frames = []
        self.writers = []
        self.readers = []
        self.incoming = Queue()
        self._read_buffer = bytearray()
        self.on_write = None

    def write(self, frame):
        self.frames.append(frame)
        self.writers.append(threading.current_thread().name)
        if self.on_write:
            self.on_write(frame)
        return len(frame)

    @property
    def in_waiting(self):
        while True:
            try:
                self._read_buffer.extend(self.incoming.get_nowait())
            except Empty:
                return len(self._read_buffer)

    def read(self, size):
        self.readers.append(threading.current_thread().name)
        data = bytes(self._read_buffer[:size])
        del self._read_buffer[:size]
        return data

    def close(self):
        self.is_open = False


def start_client(test, mode=Mode.RUN):
    port = FakeSerial()
    client = McuSerialClient("unused", 115200,
                             read_timeout_seconds=0.001,
                             write_timeout_seconds=0.01)
    with patch("ballbeam.communication.transport.serial.Serial", return_value=port):
        client.start()
    test.addCleanup(client.stop)
    if mode is not None:
        port.on_write = lambda frame: port.incoming.put(
            mode_reply(int.from_bytes(frame[2:4], "little"), frame[4]))
        if not client.select_mode(mode):
            raise AssertionError("fake MCU did not select mode")
        port.on_write = None
        port.frames.clear()
    return client, port
