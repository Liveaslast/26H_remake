"""A small, thread-safe telemetry server with a browser dashboard."""

from __future__ import annotations

import json
import math
import queue
import threading
import time
from collections import deque
from collections.abc import Mapping
from numbers import Real
from typing import Any

from flask import Flask, Response, jsonify, render_template, request, stream_with_context
from werkzeug.serving import BaseWSGIServer, make_server


Sample = dict[str, Any]
StreamMessage = tuple[str, Sample] | None


class DebugPage:
    """Publish arbitrary numeric values as live browser charts.

    The lifecycle deliberately mirrors ``BrowserStream``::

        with DebugPage(port=8000) as page:
            page.publish(
                ball_position_cm=2.4,
                ball_velocity_cm_s=-8.1,
                target_angle_deg=-2.0,
                actual_angle_deg=-1.8,
            )

    Data can also be submitted by another process with ``POST /api/data``.
    """

    def __init__(
        self,
        host: str = "0.0.0.0",
        port: int = 8000,
        *,
        max_points: int = 1000,
        title: str = "实时数据调试",
    ) -> None:
        if not isinstance(host, str) or not host.strip():
            raise ValueError("host 不能为空")
        if not isinstance(port, int) or isinstance(port, bool) or not 0 <= port <= 65535:
            raise ValueError("port 必须在 0 到 65535 之间")
        if (
            not isinstance(max_points, int)
            or isinstance(max_points, bool)
            or max_points < 2
        ):
            raise ValueError("max_points 必须是至少为 2 的整数")
        if not isinstance(title, str) or not title.strip():
            raise ValueError("title 不能为空")

        self.host = host.strip()
        self.port = port
        self.max_points = max_points
        self.title = title.strip()

        self._lock = threading.RLock()
        self._history: deque[Sample] = deque(maxlen=max_points)
        self._subscribers: set[queue.Queue[StreamMessage]] = set()
        self._started_at: float | None = None
        self._http_server: BaseWSGIServer | None = None
        self._server_thread: threading.Thread | None = None
        self._actual_port = port

        self._app = Flask(__name__)
        self._app.config["JSON_AS_ASCII"] = False
        self._register_routes()

    @property
    def is_running(self) -> bool:
        """Whether the background HTTP server is running."""
        with self._lock:
            return self._http_server is not None

    @property
    def local_url(self) -> str:
        """Loopback URL, including the actual port when ``port=0`` is used."""
        return f"http://127.0.0.1:{self._actual_port}"

    @property
    def network_url_template(self) -> str:
        """A hint for opening the page from another machine on the LAN."""
        if self.host not in {"0.0.0.0", "::"}:
            return f"http://{self.host}:{self._actual_port}"
        return f"http://<设备IP>:{self._actual_port}"

    def _register_routes(self) -> None:
        @self._app.get("/")
        def index() -> str:
            return render_template("index.html", title=self.title)

        @self._app.get("/api/status")
        def status() -> Response:
            with self._lock:
                metric_names = sorted(
                    {
                        name
                        for sample in self._history
                        for name in sample["values"]
                    }
                )
                payload = {
                    "ok": True,
                    "running": self._http_server is not None,
                    "samples": len(self._history),
                    "max_points": self.max_points,
                    "metrics": metric_names,
                }
            return jsonify(payload)

        @self._app.get("/api/history")
        def history() -> Response:
            with self._lock:
                samples = [self._copy_sample(sample) for sample in self._history]
            return jsonify({"samples": samples, "max_points": self.max_points})

        @self._app.post("/api/data")
        def receive_data() -> Response | tuple[Response, int]:
            payload = request.get_json(silent=True)
            if not isinstance(payload, dict):
                return jsonify(ok=False, error="请求体必须是 JSON 对象"), 400

            timestamp = payload.get("timestamp")
            if "values" in payload:
                values = payload["values"]
                if not isinstance(values, dict):
                    return jsonify(ok=False, error="values 必须是 JSON 对象"), 400
            else:
                values = {
                    name: value
                    for name, value in payload.items()
                    if name != "timestamp"
                }

            try:
                sample = self.publish(values, timestamp=timestamp)
            except (TypeError, ValueError, RuntimeError) as exc:
                return jsonify(ok=False, error=str(exc)), 400

            return jsonify(ok=True, sample=sample), 202

        @self._app.post("/api/clear")
        def clear_data() -> Response:
            self.clear()
            return jsonify(ok=True)

        @self._app.get("/api/events")
        def events() -> Response:
            @stream_with_context
            def generate():
                subscriber: queue.Queue[StreamMessage] = queue.Queue(maxsize=128)
                with self._lock:
                    snapshot = [
                        self._copy_sample(sample) for sample in self._history
                    ]
                    self._subscribers.add(subscriber)

                try:
                    yield self._format_event(
                        "snapshot",
                        {"samples": snapshot, "max_points": self.max_points},
                    )
                    while True:
                        try:
                            message = subscriber.get(timeout=10.0)
                        except queue.Empty:
                            yield ": keep-alive\n\n"
                            continue

                        if message is None:
                            break
                        event_name, payload = message
                        yield self._format_event(event_name, payload)
                finally:
                    with self._lock:
                        self._subscribers.discard(subscriber)

            response = Response(generate(), mimetype="text/event-stream")
            response.headers["Cache-Control"] = "no-store"
            response.headers["X-Accel-Buffering"] = "no"
            return response

        @self._app.get("/health")
        def health() -> Response:
            return jsonify(ok=True, running=self.is_running)

    def start(self) -> None:
        """Start the HTTP server in a daemon thread without blocking the caller."""
        with self._lock:
            if self._http_server is not None:
                return

            try:
                server = make_server(self.host, self.port, self._app, threaded=True)
            except OSError as exc:
                raise RuntimeError(
                    f"无法启动 DebugPage：{self.host}:{self.port}，端口可能已被占用"
                ) from exc

            self._history.clear()
            self._started_at = time.perf_counter()
            self._http_server = server
            self._actual_port = int(server.server_port)
            self._server_thread = threading.Thread(
                target=server.serve_forever,
                name="DebugPageHTTP",
                daemon=True,
            )
            self._server_thread.start()

        print("DebugPage 已启动")
        print(f"本机地址：{self.local_url}")
        print(f"局域网地址：{self.network_url_template}")

    def publish(
        self,
        values: Mapping[str, Real] | None = None,
        /,
        *,
        timestamp: Real | None = None,
        **metrics: Real,
    ) -> Sample:
        """Publish one sample without waiting for any browser.

        ``values`` and keyword metrics may be used together. Metric names are
        created automatically the first time they appear.
        """
        if not self.is_running:
            raise RuntimeError("DebugPage 尚未启动，请先调用 start()")

        merged: dict[str, Real] = {}
        if values is not None:
            if not isinstance(values, Mapping):
                raise TypeError("values 必须是字典或其他 Mapping")
            merged.update(values)
        merged.update(metrics)
        normalized = self._normalize_values(merged)

        if timestamp is None:
            with self._lock:
                started_at = self._started_at
            if started_at is None:
                raise RuntimeError("DebugPage 尚未启动，请先调用 start()")
            sample_time = time.perf_counter() - started_at
        else:
            sample_time = self._normalize_number(timestamp, "timestamp")

        sample: Sample = {"t": float(sample_time), "values": normalized}
        with self._lock:
            if self._http_server is None:
                raise RuntimeError("DebugPage 已停止")
            self._history.append(sample)
            self._broadcast_locked("sample", self._copy_sample(sample))
        return self._copy_sample(sample)

    def clear(self) -> None:
        """Clear retained samples and notify all connected browsers."""
        with self._lock:
            self._history.clear()
            self._broadcast_locked("clear", {})

    def stop(self) -> None:
        """Stop the HTTP server and release the listening port."""
        with self._lock:
            server = self._http_server
            thread = self._server_thread
            if server is None:
                return
            self._http_server = None
            self._server_thread = None
            self._started_at = None
            subscribers = list(self._subscribers)

        for subscriber in subscribers:
            self._put_latest(subscriber, None)

        server.shutdown()
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=3.0)
        server.server_close()

    def _broadcast_locked(self, event_name: str, payload: Sample) -> None:
        message: StreamMessage = (event_name, payload)
        for subscriber in tuple(self._subscribers):
            self._put_latest(subscriber, message)

    @staticmethod
    def _put_latest(
        subscriber: queue.Queue[StreamMessage], message: StreamMessage
    ) -> None:
        try:
            subscriber.put_nowait(message)
            return
        except queue.Full:
            pass

        try:
            subscriber.get_nowait()
        except queue.Empty:
            pass
        try:
            subscriber.put_nowait(message)
        except queue.Full:
            pass

    @classmethod
    def _normalize_values(cls, values: Mapping[str, Real]) -> dict[str, float]:
        if not values:
            raise ValueError("至少需要一个数据项")

        normalized: dict[str, float] = {}
        for name, value in values.items():
            if not isinstance(name, str) or not name.strip():
                raise ValueError("数据名称必须是非空字符串")
            normalized[name.strip()] = cls._normalize_number(value, name)
        return normalized

    @staticmethod
    def _normalize_number(value: Real, name: str) -> float:
        if not isinstance(value, Real) or isinstance(value, bool):
            raise TypeError(f"{name} 必须是数字")
        number = float(value)
        if not math.isfinite(number):
            raise ValueError(f"{name} 必须是有限数字")
        return number

    @staticmethod
    def _copy_sample(sample: Sample) -> Sample:
        return {"t": sample["t"], "values": dict(sample["values"])}

    @staticmethod
    def _format_event(event_name: str, payload: Sample) -> str:
        data = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        return f"event: {event_name}\ndata: {data}\n\n"

    def __enter__(self) -> DebugPage:
        self.start()
        return self

    def __exit__(self, exc_type: Any, exc: Any, traceback: Any) -> None:
        self.stop()
