"""CSV write ownership, bounded queues, failure reporting and shutdown draining."""

import csv
from contextlib import redirect_stderr
import io
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from ballbeam.recording.csv_writer import CsvWriter, CsvWriteWorker
from ballbeam.recording.csv_recorders import BallStateTxLogger
from fake_mcu import send_once, start_client, wait_until


class CsvWriterTests(unittest.TestCase):
    def test_rows_keep_order_and_close_drains_them(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "data.csv"
            output = CsvWriter(path, ("value",))
            writers = []
            original = output._write
            def write(row):
                writers.append(threading.current_thread().name)
                original(row)
            with patch.object(output, "_write", side_effect=write):
                for value in range(100):
                    self.assertTrue(output.write((value,)))
                output.close()
                output.close()
            self.assertTrue(output.closed)
            self.assertEqual(set(writers), {"CsvWriter"})
            self.assertFalse(output._worker._thread.is_alive())
            self.assertFalse(output.write((101,)))
            with path.open(newline="", encoding="utf-8") as handle:
                self.assertEqual(list(csv.reader(handle)), [["value"]] + [[str(i)] for i in range(100)])

    def test_slow_disk_does_not_stop_serial_transmission(self):
        client, port = start_client(self)
        entered, release = threading.Event(), threading.Event()
        with tempfile.TemporaryDirectory() as directory:
            logger = BallStateTxLogger(Path(directory) / "tx.csv")
            original = logger.output._write
            def slow_write(row):
                entered.set()
                release.wait(2)
                original(row)
            try:
                with patch.object(logger.output, "_write", side_effect=slow_write):
                    client.record_sent_frame = logger.publish
                    self.assertTrue(send_once(client, 1, 0, True))
                    self.assertTrue(entered.wait(1))
                    client.start_stream(.005)
                    client.publish_ball_state(2, 0, True)
                    initial = len(port.frames)
                    wait_until(lambda: len(port.frames) >= initial + 4, timeout=.5)
                    self.assertFalse(release.is_set())
                    client.stop_stream()
                    release.set()
                    logger.close()
            finally:
                client.record_sent_frame = None
                release.set()
                logger.close()

    def test_full_queue_drops_explicitly_without_blocking_producer(self):
        entered, release = threading.Event(), threading.Event()
        with tempfile.TemporaryDirectory() as directory, redirect_stderr(io.StringIO()) as errors:
            worker = CsvWriteWorker(queue_size=1)
            output = CsvWriter(Path(directory) / "data.csv", ("value",), worker=worker)
            original = output._write
            def slow_write(row):
                entered.set()
                release.wait(2)
                original(row)
            try:
                with patch.object(output, "_write", side_effect=slow_write):
                    self.assertTrue(output.write((1,)))
                    self.assertTrue(entered.wait(1))
                    self.assertTrue(output.write((2,)))
                    started = time.monotonic()
                    self.assertFalse(output.write((3,)))
                    self.assertLess(time.monotonic() - started, .2)
                    self.assertEqual(output.dropped_rows, 1)
                    self.assertIn("queue is full", output.error)
                    release.set()
                    output.close()
            finally:
                release.set()
                output.close()
                worker.close()
            self.assertEqual(output.rows_written, 2)
            self.assertIn("queue is full", errors.getvalue())

    def test_disk_failure_is_reported_and_other_files_still_write(self):
        with tempfile.TemporaryDirectory() as directory, redirect_stderr(io.StringIO()) as errors:
            worker = CsvWriteWorker()
            failed = CsvWriter(Path(directory) / "failed.csv", ("value",), worker=worker)
            healthy = CsvWriter(Path(directory) / "healthy.csv", ("value",), worker=worker)
            try:
                with patch.object(failed, "_write", side_effect=OSError("disk full")):
                    failed.write((1,))
                    healthy.write((2,))
                    failed.close()
                    healthy.close()
            finally:
                failed.close()
                healthy.close()
                worker.close()
            self.assertEqual(failed.dropped_rows, 1)
            self.assertEqual(failed.error, "disk full")
            self.assertEqual(healthy.rows_written, 1)
            self.assertIn("disk full", errors.getvalue())

    def test_concurrent_close_closes_file_once(self):
        with tempfile.TemporaryDirectory() as directory:
            output = CsvWriter(Path(directory) / "data.csv", ("value",))
            output.write((1,))
            threads = [threading.Thread(target=output.close) for _ in range(2)]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join(1)
                self.assertFalse(thread.is_alive())
            self.assertTrue(output.closed)
            self.assertEqual(output.rows_written, 1)
