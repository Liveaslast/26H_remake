"""Shared CSV file operations with one bounded background queue per capture."""

import csv
from pathlib import Path
from queue import Full, Queue
import sys
import threading


class CsvWriteWorker:
    def __init__(self, queue_size=4096):
        self._queue = Queue(maxsize=queue_size)
        self._closed = False
        self._thread = threading.Thread(target=self._run, name="CsvWriter", daemon=True)
        self._thread.start()

    def submit(self, output, row):
        if self._closed:
            output._fail("CSV writer is stopped")
            output.dropped_rows += 1
            return False
        try:
            self._queue.put_nowait((output, tuple(row)))
            return True
        except Full:
            output._fail("CSV queue is full; rows were dropped")
            output.dropped_rows += 1
            return False

    def close_file(self, output):
        self._queue.put((output, None))
        output._closed_event.wait()

    def close(self):
        if not self._closed:
            self._closed = True
            self._queue.put(None)
            self._thread.join()

    def _run(self):
        while True:
            item = self._queue.get()
            if item is None:
                return
            output, row = item
            try:
                if row is None:
                    output._file.close()
                else:
                    output._write(row)
            except Exception as exc:
                output._fail(str(exc))
                if row is not None:
                    output.dropped_rows += 1
            finally:
                if output.error is not None and not output._reported:
                    output._reported = True
                    print(f"CSV recording error: {output.path}: {output.error}",
                          file=sys.stderr, flush=True)
                if row is None:
                    if output.dropped_rows:
                        print(f"CSV recording incomplete: {output.path}: "
                              f"written={output.rows_written} dropped={output.dropped_rows}",
                              file=sys.stderr, flush=True)
                    output._closed_event.set()


class CsvWriter:
    """Own a CSV file; producers enqueue rows, close waits for queued writes."""

    def __init__(self, path: Path, header, *, worker=None):
        self.path = path
        self.error = None
        self.dropped_rows = 0
        self.rows_written = 0
        self._reported = False
        self._closed = False
        self._closed_event = threading.Event()
        self._lock = threading.Lock()
        path.parent.mkdir(parents=True, exist_ok=True)
        self._file = path.open("w", newline="", encoding="utf-8", buffering=1)
        try:
            self._writer = csv.writer(self._file)
            self._writer.writerow(header)
        except Exception:
            self._file.close()
            raise
        self._owns_worker = worker is None
        try:
            self._worker = CsvWriteWorker() if worker is None else worker
        except Exception:
            self._file.close()
            raise

    @property
    def closed(self):
        return self._closed_event.is_set()

    def write(self, row):
        with self._lock:
            if self._closed:
                return False
            return self._worker.submit(self, row)

    def _write(self, row):
        self._writer.writerow(row)
        self.rows_written += 1

    def _fail(self, message):
        self.error = message

    def close(self):
        with self._lock:
            first_close = not self._closed
            self._closed = True
        if first_close:
            self._worker.close_file(self)
            if self._owns_worker:
                self._worker.close()
        else:
            self._closed_event.wait()
