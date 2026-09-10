import os
import sqlite3
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

import web_backend as backend
from tools.db import init_sqlite3, record_scrape_event
from tools.execution_outcomes import record_outcome


def wait_until(predicate):
    deadline = time.monotonic() + 5
    while not predicate():
        if time.monotonic() >= deadline:
            raise AssertionError("Timed out waiting for task state")
        time.sleep(.02)


class TaskControlTests(unittest.TestCase):
    def tearDown(self):
        backend.EXECUTION_STOP.clear()
        backend.REFRESH_STATE.update(running=False, task_id=None, stopping=False)

    def test_real_worker_terminates_without_followup_write(self):
        with tempfile.TemporaryDirectory() as folder:
            started, finished = Path(folder) / "started", Path(folder) / "finished"
            backend._begin_execution("task-a")
            errors = []

            def work():
                try:
                    backend._run_managed("tests.task_sleep_worker", {
                        "started": str(started), "finished": str(finished)})
                except backend.TaskStopped:
                    errors.append("stopped")
            thread = threading.Thread(target=work)
            thread.start()
            try:
                wait_until(started.exists)
                self.assertFalse(backend._stop_task("other-task"))
                self.assertTrue(backend._stop_task("task-a"))
                thread.join(5)
                self.assertFalse(thread.is_alive())
                self.assertEqual(errors, ["stopped"])
                self.assertIsNone(backend.EXECUTION_PROCESS)
                self.assertFalse(finished.exists())
            finally:
                backend._stop_task("task-a")
                thread.join(5)

    def test_all_task_types_publish_identity_and_release_lock_after_stop(self):
        for function in ("metadata_completion", "summary_translation", "metadata_correction", "card_collage_refresh"):
            with self.subTest(function=function):
                entered = threading.Event()

                def run(*args, **kwargs):
                    entered.set()
                    self.assertTrue(backend.EXECUTION_STOP.wait(5))
                    raise backend.TaskStopped()

                with patch.object(backend, "_run_managed", side_effect=run), \
                        patch.object(backend, "_configured_library_context", return_value={
                            "s::l": {"server_id": "s", "library_id": "l"}}), \
                        patch.object(backend, "_write_activity"):
                    task = dict(id=function, name=function, functions=[function], fields=["summary"], card_ids=["s::l"])
                    self.assertTrue(backend._start_task(task))
                    self.assertTrue(entered.wait(5))
                    self.assertEqual(backend.REFRESH_STATE["task_id"], function)
                    self.assertFalse(backend._start_task(task))
                    self.assertTrue(backend._stop_task(function))
                    wait_until(lambda: not backend.REFRESH_STATE["running"])
                    self.assertEqual(backend.REFRESH_STATE["last_result"], "stopped")
                    self.assertFalse(backend.REFRESH_STATE["stopping"])
                    self.assertIsNone(backend.REFRESH_STATE["task_id"])
                    self.assertTrue(backend.REFRESH_LOCK.acquire(timeout=2))
                    backend.REFRESH_LOCK.release()


class PagedHistoryTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.root = Path(self.folder.name)
        self.root_patch = patch.object(backend, "ROOT", self.root)
        self.root_patch.start()
        self.state_patch = patch.object(backend, "_read_state", return_value={
            "KOMGA_SERVERS": [{"id": "server", "name": "Test Server"}],
            "KOMGA_LIBRARY_LIST": [{"SERVER_ID": "server", "LIBRARY": "library"}]})
        self.state_patch.start()
        _, self.conn = init_sqlite3(self.root / "recordsRefreshed.db")
        for index in range(125):
            record_scrape_event(self.conn, "漫画", f"Book {index:03}", "library", "Library",
                                ["title"], source_title=f"Book {index:03}", event_kind="series",
                                source_path=f"/data/{index}", komga_id=str(index), server_id="server")
        for index in range(110):
            record_scrape_event(self.conn, "漫画", f"Volume {index}", "library", "Library",
                                ["numberSort"], source_title="Book 000", event_kind="volume",
                                source_path=f"/data/000/{index}", komga_id=f"v{index}", server_id="server")
        now = __import__("datetime").datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self.conn.executemany("INSERT INTO activity_logs(level,action,detail,source,recorded_at) VALUES (?,?,?,?,?)",
                              [("info", "Task", f"Entry {i}", "manual", now) for i in range(230)])
        self.conn.commit()

    def tearDown(self):
        self.conn.close()
        self.state_patch.stop()
        self.root_patch.stop()
        self.folder.cleanup()

    def test_record_pages_are_bounded_and_search_is_server_side(self):
        with patch.object(backend, "_read_scrape_rows", wraps=backend._read_scrape_rows) as read:
            first = backend._read_scrape_records(500, with_total=True)
            self.assertEqual(first["total"], 125)
            self.assertEqual(len(first["items"]), 50)
            self.assertLessEqual(len(read.call_args.args[0]), 50 * 51)
        second = backend._read_scrape_records(50, 50, with_total=True)
        self.assertFalse({row["id"] for row in first["items"]} & {row["id"] for row in second["items"]})
        self.assertEqual(len(backend._read_scrape_records(50, 100)), 25)
        found = backend._read_scrape_records(search="Book 003", with_total=True)
        self.assertEqual(found["total"], 1)
        self.assertEqual(found["items"][0]["source_title"], "Book 003")
        self.assertEqual(backend._read_scrape_stats()["total"], 125)
        self.assertEqual(backend._read_scrape_records(search="no match", with_total=True)["total"], 0)

    def test_volume_details_are_paged_without_loss(self):
        row = backend._read_scrape_records(search="Book 000")[0]
        self.assertEqual(row["volume_count"], 110)
        self.assertEqual(len(row["volumes"]), 50)
        pages = [backend._read_record_details(row["id"], offset) for offset in (0, 50, 100)]
        self.assertEqual([len(page["items"]) for page in pages], [50, 50, 10])
        self.assertEqual(len({item["id"] for page in pages for item in page["items"]}), 110)
        self.assertEqual(pages[0]["total"], 110)

    def test_logs_are_capped_at_100_and_filtered_before_pagination(self):
        first = backend._read_runtime_logs(1000, with_total=True)
        self.assertEqual(len(first["items"]), 100)
        self.assertEqual(first["total"], 230)
        self.assertEqual(len(backend._read_runtime_logs(100, 200)), 30)
        self.assertEqual(backend._read_runtime_logs(search="Entry 229", with_total=True)["total"], 1)

    def test_outcome_statistics_are_per_entry_not_log_message_or_field(self):
        with patch.dict(os.environ, {"BANGUMI_EXECUTION_ID": "manual-1", "BANGUMI_EXECUTION_SERVER": "s"}):
            record_outcome("series", "a", conn=self.conn)
            record_outcome("series", "a", conn=self.conn)
            record_outcome("series", "b", True, self.conn)
            record_outcome("series", "b", conn=self.conn)
        with patch.dict(os.environ, {"BANGUMI_EXECUTION_ID": "scheduled-1", "BANGUMI_EXECUTION_SERVER": "s"}):
            record_outcome("series", "a", conn=self.conn)
        stats = backend._runtime_log_stats()
        self.assertEqual(stats["total"], 230)
        self.assertEqual(stats["success"], 2)
        self.assertEqual(stats["failed"], 1)


if __name__ == "__main__":
    unittest.main()
