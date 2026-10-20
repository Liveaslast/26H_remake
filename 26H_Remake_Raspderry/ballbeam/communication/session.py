"""通信收发调度器"""

from concurrent.futures import Future
from queue import Empty, Full, Queue
import math
import threading
import time

from .protocol import (
    Mode, ModeReply, VelocityParameters, REQUEST_SEQ_NONE,
    pack_mode_request, pack_run, pack_tuning,
)

## 模式请求-应答管理器
class ModeRequest:
    def __init__(self):
        self.current_mode = Mode.NONE
        self.target_mode = Mode.NONE
        self.seq = 0
        self._next_seq = 0
        self.reply = None
        self.deadline = None
        self.last_error = None

    def begin(self, mode, reply, timeout):                 # 登记模式请求，设置待确认状态及超时时刻
        mode = Mode(mode)
        if mode == Mode.NONE:
            raise ValueError("choose run or tuning mode")
        if self.reply is not None:
            reply.set_result(False)
            return False
        self.current_mode = Mode.NONE
        self.target_mode = mode
        self.seq = self._next_seq
        self._next_seq = (self._next_seq + 1) & 0xFFFF
        self.reply = reply
        self.deadline = time.monotonic() + timeout
        self.last_error = None
        return True

    def receive(self, response):                            # 核对收到的模式应答
        if self.reply is None:
            return
        if (response.mode, response.seq) != (self.target_mode, self.seq):
            return
        success = response.result == 0
        self.current_mode = self.target_mode if success else Mode.NONE  # 应答成功后匹配更新模式
        self.last_error = None if success else "MCU rejected mode selection"
        reply = self.reply
        self.reply = self.deadline = None
        reply.set_result(success)

    def check_timeout(self, now):                            # 检查模式应答确认是否超时
        if self.reply is not None and now >= self.deadline:
            self.fail("mode reply timeout")

    def fail(self, reason):                                  # 结束等待并返回失败
        self.last_error = reason
        reply = self.reply
        self.reply = self.deadline = None
        self.current_mode = Mode.NONE
        if reply is not None:
            reply.set_result(False)

## RUN/TUNING周期帧的数据管理器
class DataStream:
    """Own vision, task, parameter and sequence data; no encoding or serial I/O."""

    def __init__(self, mode):
        self.mode = mode
        self.packet_seq = 0
        self.updates = Queue(maxsize=1)
        self.reset()

    def reset(self):
        self.task_id = self.request_seq = self.revision = 0
        self._request_counter = 0
        self.parameters = VelocityParameters()
        self.latest_ball = None
        while True:
            try:
                self.updates.get_nowait()
            except Empty:
                break

    # 等级任务ID及序列号
    def request_task(self, task_id):
        if self.mode.current_mode == Mode.NONE:
            raise ValueError("select a communication mode before requesting a task")
        self._validate_task_id(task_id)
        self.task_id = task_id
        # Zero means data only, including after the request counter wraps.
        self._request_counter = ((self._request_counter + 1) & 0xFFFF) or (REQUEST_SEQ_NONE + 1)
        self.request_seq = self._request_counter
        return self.request_seq

    @staticmethod
    def _validate_task_id(task_id):
        if isinstance(task_id, bool) or not isinstance(task_id, int) or not 0 <= task_id <= 15:
            raise ValueError("task ID must fit in four bits")

    def set_parameters(self, data):
        if self.mode.current_mode != Mode.TUNING:
            raise ValueError("velocity parameters require tuning mode")
        task_id, parameters = data
        self._validate_task_id(task_id)
        parameters.scaled()
        # Configuration selects its owner without submitting a motion request.
        self.task_id = task_id
        self.request_seq = REQUEST_SEQ_NONE
        self.parameters = parameters
        self.revision = (self.revision + 1) & 0xFFFF
        return self.revision

    def publish_vision(self, position, velocity, valid, *, measured_at=None):
        timestamp = time.monotonic() if measured_at is None else float(measured_at)
        sample = (position, velocity, valid, timestamp)
        while True:
            try:
                self.updates.put_nowait(sample)
                return
            except Full:
                try:
                    self.updates.get_nowait()
                except Empty:
                    pass

    def snapshot(self, now):
        try:
            self.latest_ball = self.updates.get_nowait()
        except Empty:
            pass
        x, v, valid, measured_at = self.latest_ball or (0, 0, False, now)
        # Repeated transport packets must not keep old vision valid forever.
        fresh = math.isfinite(measured_at) and 0 <= now - measured_at <= 0.1
        fields = dict(seq=self.packet_seq, pos_cm=x, vel_cm_s=v, valid=valid and fresh,
                      pi_time_ms=int(now * 1000), task_id=self.task_id,
                      request_seq=self.request_seq)
        if self.mode.current_mode == Mode.TUNING:
            fields.update(parameters=self.parameters, revision=self.revision)
        return fields

    def mark_sent(self):
        self.packet_seq = (self.packet_seq + 1) & 0xFFFF


class FrameSender:
    """Encode and write every outgoing frame; schedule only the data stream."""

    def __init__(self, transport, on_data_sent):
        self.transport = transport
        self.on_data_sent = on_data_sent
        self.period = None
        self.next_send_at = 0.0
        self.last_error = None
        self.send_failures = 0

    def set_period(self, period):
        self.period = period
        self.next_send_at = time.monotonic()
        return True

    def send_mode(self, request):
        return self._write(pack_mode_request(request.seq, request.target_mode))

    # 控制发送时间（从而保持发送周期）
    def send_due(self, mode, stream, now):
        if mode == Mode.NONE or self.period is None:
            return
        if now < self.next_send_at:
            return
        self.send_data(mode, stream)
        self.next_send_at = max(self.next_send_at + self.period, now)

    # 打包数据并发送
    def send_data(self, mode, stream):
        if mode == Mode.NONE:
            return False
        try:
            sent_at = time.monotonic()
            fields = stream.snapshot(sent_at)
            frame = pack_run(**fields) if mode == Mode.RUN else pack_tuning(**fields)
        except Exception as exc:
            self.last_error = str(exc)
            self.send_failures += 1
            return False
        if not self._write(frame):
            return False
        stream.mark_sent()
        try:
            self.on_data_sent(frame, sent_at)
        except Exception as exc:
            self.last_error = str(exc)
        return True

    def _write(self, frame):
        try:
            if self.transport.write(frame):
                self.last_error = None
                return True
            self.last_error = self.transport.last_error or "serial write failed"
        except Exception as exc:
            self.last_error = str(exc)
        self.send_failures += 1
        return False


class CommunicationSession:
    """One worker connects client operations, mode replies and serial I/O."""
    def __init__(self, transport, decoder, on_telemetry, on_data_sent):
        self.transport = transport
        self.decoder = decoder
        self.on_telemetry = on_telemetry
        self.on_data_sent = on_data_sent
        self.thread = None
        self.mode = ModeRequest()
        self.last_error = None
        self.inbox = Queue()
        self._wakeup = threading.Event()
        self._reset_components()

    # 创建组件
    def _reset_components(self):
        self.stream = DataStream(self.mode)
        self.sender = FrameSender(self.transport, self.on_data_sent)
        self._handlers = {                                      # 创建处理器
            "task": self.stream.request_task,                   # 请求任务
            "parameters": self.stream.set_parameters,
            "stream": self.sender.set_period,
            "stop": self._stop_loop,
        }

    @property
    def send_failures(self):
        return self.sender.send_failures

    @property
    def is_running(self):
        return self.thread is not None and self.thread.is_alive()

    # 初始化状态，启动通信线程
    def start(self):
        if self.is_running:
            return
        ## 初始化状态
        self.mode = ModeRequest()
        self.last_error = None
        self.inbox = Queue()                        ## 重置队列
        self._reset_components()
        self.running = True
        self.decoder.reset()

        # 创建通信线程，线程开始执行_run
        self.thread = threading.Thread(target=self._run, name="McuCommunication", daemon=True)
        self.thread.start()

    def stop(self):                                 # 请求线程停止，并等待退出
        if self.is_running:
            self.call("stop")
            self.thread.join()
        self.thread = None

    ## 把请求通信线程执行的操作这件事存放进队列
    def submit(self, operation, data=None):         # 
        reply = Future()
        if not self.is_running:                     # 确认线程运行
            reply.set_result(False)
            return reply
        self.inbox.put((operation, data, reply))
        self._wakeup.set()
        return reply

    ## 请求通信线程目前执行什么操作
    def call(self, operation, data=None):
        """Local operations finish immediately; mode selection waits for its reply."""
        if threading.current_thread() is self.thread:
            raise RuntimeError("communication callbacks cannot wait on the communication thread")
        return self.submit(operation, data).result()

    def publish_ball(self, position, velocity, valid, *, measured_at=None):
        self.stream.publish_vision(position, velocity, valid, measured_at=measured_at)
        self._wakeup.set()

    def _run(self):
        try:
            while self.running:
                self._wakeup.clear()
                self._receive_frames()
                self._process_operation()               ## 取出队列操作事件

                ## 根据时间决定本轮发布发送数据
                if self.running:
                    self.sender.send_due(self.mode.current_mode, self.stream, time.monotonic())
                self.mode.check_timeout(time.monotonic())
                if self.running and self.inbox.empty():
                    self._wakeup.wait(0.001)
        finally:
            self.mode.fail("communication stopped")
            while not self.inbox.empty():
                _, _, reply = self.inbox.get_nowait()
                if not reply.done():
                    reply.set_result(False)

    def _receive_frames(self):
        for frame in self.decoder.feed(self.transport.read_available()):
            try:
                if isinstance(frame, ModeReply):
                    self.mode.check_timeout(time.monotonic())
                    self.mode.receive(frame)
                elif frame.mode == self.mode.current_mode:
                    self.on_telemetry(frame, time.monotonic())
            except Exception as exc:
                self.last_error = str(exc)

    ## 从队列中取出请求事件
    def _process_operation(self):
        try:
            operation, data, reply = self.inbox.get_nowait()
        except Empty:
            return
        try:
            if operation == "mode":
                self._request_mode(data, reply)                     # 登记模式请求，并交给发送器
            else:                                                   # 正式
                reply.set_result(self._handlers[operation](data))
        except Exception as exc:
            self.last_error = str(exc)
            reply.set_exception(exc)

    ## 在取出队列中的模式请求操作事件后，登记请求并协调发送
    def _request_mode(self, data, reply):
        mode, timeout = data                        # data是个元组

        # 模式请求结果
        if not self.mode.begin(mode, reply, timeout):               # 分配模式请求号、保存等待状态
            return
        self.stream.reset()
        if not self.sender.send_mode(self.mode):                    # 打包并发送
            self.mode.fail(self.sender.last_error or "mode request write failed")

    def _stop_loop(self, _data):
        self.running = False
        return True

