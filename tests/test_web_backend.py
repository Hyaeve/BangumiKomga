import json
import tempfile
import sqlite3
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch
from unittest.mock import Mock

import web_backend


class _FakeKomga:
    def __init__(self):
        self.calls = 0

    def get_latest_series(self, library_id=None, page=0):
        self.calls += 1
        return {
            "content": [
                {"id": f"series-{self.calls}-{index}", "name": f"Book {index}"}
                for index in range(4)
            ]
        }


class PreviewCacheTests(unittest.TestCase):
    def test_preview_is_stable_until_forced_and_survives_reload(self):
        fake = _FakeKomga()
        with tempfile.TemporaryDirectory() as folder:
            cache_file = Path(folder) / "cover_collage_cache.json"
            with patch.object(web_backend, "PREVIEW_CACHE_FILE", cache_file), \
                    patch.object(web_backend, "_load_komga", return_value=fake):
                web_backend.PREVIEW_CACHE.clear()
                web_backend.PREVIEW_CACHE_LOADED = False
                first = web_backend._preview_items("server", "library")
                stable = web_backend._preview_items("server", "library")
                refreshed = web_backend._preview_items("server", "library", force=True)
                self.assertEqual(fake.calls, 2)
                self.assertEqual(len(first), 8)
                self.assertEqual(len({item["preview_id"] for item in first}), 8)
                self.assertEqual(len({item["id"] for item in first}), 4)
                self.assertEqual(first, stable)
                self.assertNotEqual(stable, refreshed)

                web_backend.PREVIEW_CACHE.clear()
                web_backend.PREVIEW_CACHE_LOADED = False
                self.assertEqual(web_backend._preview_items("server", "library"), refreshed)
                self.assertEqual(fake.calls, 2)

    def test_empty_preview_is_cached(self):
        fake = _FakeKomga()
        fake.get_latest_series = lambda library_id=None, page=0: {"content": []}
        with tempfile.TemporaryDirectory() as folder:
            cache_file = Path(folder) / "cover_collage_cache.json"
            with patch.object(web_backend, "PREVIEW_CACHE_FILE", cache_file), \
                    patch.object(web_backend, "_load_komga", return_value=fake):
                web_backend.PREVIEW_CACHE.clear()
                web_backend.PREVIEW_CACHE_LOADED = False
                self.assertEqual(web_backend._preview_items("server", "empty"), [])
                web_backend.PREVIEW_CACHE.clear()
                web_backend.PREVIEW_CACHE_LOADED = False
                self.assertEqual(web_backend._preview_items("server", "empty"), [])
                self.assertTrue(json.loads(cache_file.read_text(encoding="utf-8")))


class CollageTaskTests(unittest.TestCase):
    def test_collage_task_refreshes_selected_libraries(self):
        refreshed = []
        with patch.object(web_backend, "_configured_library_context", return_value={
            "library-a": {"server_id": "server-a"},
            "library-b": {"server_id": "server-b"},
        }), patch.object(web_backend, "_preview_items", side_effect=lambda server, library, force=False: refreshed.append((server, library, force))), patch.object(web_backend, "_write_activity"):
            web_backend._refresh_card_collages(["library-a", "library-b"])
        self.assertEqual(refreshed, [("server-a", "library-a", True), ("server-b", "library-b", True)])

    def test_collage_task_uses_server_qualified_library_keys(self):
        refreshed = []
        with patch.object(web_backend, "_configured_library_context", return_value={
            "server-a::shared": {"server_id": "server-a", "library_id": "shared"},
            "server-b::shared": {"server_id": "server-b", "library_id": "shared"},
        }), patch.object(web_backend, "_preview_items", side_effect=lambda server, library, force=False: refreshed.append((server, library, force))), patch.object(web_backend, "_write_activity"):
            web_backend._refresh_card_collages(["server-b::shared"])
        self.assertEqual(refreshed, [("server-b", "shared", True)])

    def test_task_library_ids_strip_server_qualification(self):
        with patch.object(web_backend, "_configured_library_context", return_value={
            "server-a::library-a": {"server_id": "server-a", "library_id": "library-a"},
        }):
            self.assertEqual(web_backend._task_library_ids(["server-a::library-a"]), ["library-a"])


class ScrapeRecordGroupingTests(unittest.TestCase):
    def test_series_and_volumes_are_grouped_with_source_paths(self):
        rows = [
            {
                "id": 13, "item_type": "漫画", "item_title": "第一卷",
                "library_id": "library-a", "library_name": "国漫",
                "server_id": "server-a", "server_name": "家庭 Komga",
                "metadata_fields": ["number"], "status": "success",
                "recorded_at": "2026-09-10T13:14:13", "source_title": "万古之王",
                "matched_title": "万古之王", "match_source": "书名号",
                "event_kind": "volume", "source_path": "/books/volume-1.cbz",
            },
            {
                "id": 12, "item_type": "漫画", "item_title": "万古之王",
                "library_id": "library-a", "library_name": "国漫",
                "server_id": "server-a", "server_name": "家庭 Komga",
                "metadata_fields": ["title", "summary"], "status": "success",
                "recorded_at": "2026-09-10T13:13:00", "source_title": "万古之王",
                "matched_title": "万古之王", "match_source": "书名号",
                "event_kind": "series", "source_path": "",
            },
            {
                "id": 11, "item_type": "漫画", "item_title": "第二卷",
                "library_id": "library-a", "library_name": "国漫",
                "server_id": "server-a", "server_name": "家庭 Komga",
                "metadata_fields": ["numberSort"], "status": "success",
                "recorded_at": "2026-09-10T13:12:00", "source_title": "万古之王",
                "matched_title": "万古之王", "match_source": "书名号",
                "event_kind": "volume", "source_path": "/books/volume-2.cbz",
            },
        ]

        grouped = web_backend._group_scrape_records(rows)

        self.assertEqual(len(grouped), 1)
        self.assertEqual(grouped[0]["volume_count"], 2)
        self.assertEqual(grouped[0]["source_path"], "/books/volume-1.cbz")
        self.assertEqual(grouped[0]["metadata_fields"], ["number", "title", "summary", "numberSort"])
        self.assertEqual(
            [volume["source_path"] for volume in grouped[0]["volumes"]],
            ["/books/volume-1.cbz", "/books/volume-2.cbz"],
        )


class RecordPathTests(unittest.TestCase):
    def test_old_record_path_recovered_by_id_and_library_checked(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            with closing(sqlite3.connect(root / "recordsRefreshed.db")) as conn:
                conn.executescript("""
                    CREATE TABLE scrape_records(id INTEGER PRIMARY KEY, source_path TEXT);
                    INSERT INTO scrape_records VALUES (1, NULL);
                    CREATE TABLE refreshed_series(series_id TEXT, series_name TEXT);
                    INSERT INTO refreshed_series VALUES ('series', 'Book');
                """)
            komga = Mock()
            record = {"id": "book:lib:1", "source_title": "Book", "event_kind": "series", "library_id": "lib", "server_id": "server"}
            with patch.object(web_backend, "ROOT", root), patch.object(web_backend, "_load_komga", return_value=komga):
                komga.get_specific_series.return_value = {"libraryId": "other", "url": "/wrong"}
                web_backend._backfill_source_paths([record])
                with closing(sqlite3.connect(root / "recordsRefreshed.db")) as conn:
                    self.assertIsNone(conn.execute("SELECT source_path FROM scrape_records").fetchone()[0])
                komga.get_specific_series.return_value = {"libraryId": "lib", "url": "/books/Book"}
                web_backend._backfill_source_paths([record])
                with closing(sqlite3.connect(root / "recordsRefreshed.db")) as conn:
                    self.assertEqual(conn.execute("SELECT source_path FROM scrape_records").fetchone()[0], "/books/Book")


class TaskConfigPersistenceTests(unittest.TestCase):
    def test_edit_keeps_order_and_new_task_defaults_to_two_hours(self):
        import threading
        from http.server import ThreadingHTTPServer
        from urllib.request import Request, urlopen
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            with patch.object(web_backend, "CONFIG_DIR", root), \
                 patch.object(web_backend, "CONFIG_FILE", root / "config.py"), \
                 patch.object(web_backend, "WEB_STATE", root / "state.json"), \
                 patch.object(web_backend, "SESSIONS", {"test-session"}), \
                 patch.object(web_backend, "_write_activity"):
                tasks = [{"id": key, "name": key, "functions": ["card_collage_refresh"],
                          "card_ids": ["s::lib"], "time_limit_hours": hours}
                         for key, hours in [("last", 0), ("first", 1.5), ("middle", 3)]]
                web_backend.save_state({"METADATA_TASKS": tasks})
                server = ThreadingHTTPServer(("127.0.0.1", 0), web_backend.Handler)
                thread = threading.Thread(target=server.serve_forever)
                thread.start()
                def save(task):
                    request = Request(f"http://127.0.0.1:{server.server_port}/api/tasks",
                        data=json.dumps(task).encode(),
                        headers={"Cookie": "bk_session=test-session", "Content-Type": "application/json"})
                    with urlopen(request) as response:
                        return json.load(response)["items"]
                try:
                    for task in tasks:
                        payload = {key: value for key, value in task.items() if key != "time_limit_hours"}
                        payload["name"] += " edited"
                        saved = save(payload)
                        self.assertEqual([item["id"] for item in saved], ["last", "first", "middle"])
                        self.assertEqual([item["time_limit_hours"] for item in saved], [0, 1.5, 3])
                    saved = save({"name": "new", "functions": ["card_collage_refresh"]})
                    self.assertEqual(saved[-1]["time_limit_hours"], 2)
                    self.assertEqual([item["id"] for item in saved[:-1]], ["last", "first", "middle"])
                    (root / "state.json").unlink()
                    self.assertEqual(web_backend._read_state()["METADATA_TASKS"], saved)
                finally:
                    server.shutdown()
                    server.server_close()
                    thread.join()

    def test_media_policy_survives_config_reload_and_legacy_translation_is_removed(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            with patch.object(web_backend, "CONFIG_DIR", root), \
                 patch.object(web_backend, "CONFIG_FILE", root / "config.py"), \
                 patch.object(web_backend, "WEB_STATE", root / "state.json"):
                web_backend.save_state({"KOMGA_LIBRARY_LIST": [
                    {"LIBRARY": "one", "MEDIA_TYPE": "mixed", "SCRAPE_ENABLED": False, "TRANSLATE_SUMMARY_TO_ZH": True},
                    {"LIBRARY": "two", "IS_NOVEL_ONLY": True},
                ]})
                (root / "state.json").unlink()
                cards = web_backend._read_state()["KOMGA_LIBRARY_LIST"]
                self.assertEqual(cards[0]["MEDIA_TYPE"], "mixed")
                self.assertFalse(cards[0]["SCRAPE_ENABLED"])
                self.assertFalse(cards[0]["TRANSLATE_SUMMARY_TO_ZH"])
                self.assertEqual(cards[1]["MEDIA_TYPE"], "book")
                self.assertTrue(cards[1]["SCRAPE_ENABLED"])

    def test_operations_and_ai_completion_survive_config_reload(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            with patch.object(web_backend, "CONFIG_DIR", root), \
                 patch.object(web_backend, "CONFIG_FILE", root / "config.py"), \
                 patch.object(web_backend, "WEB_STATE", root / "state.json"):
                web_backend.save_state({"METADATA_TASKS": [
                    {"id": "correction", "functions": ["metadata_correction"], "fields": ["title", "summary"],
                     "operations": ["simplify", "extract_title", "include_locked"], "card_ids": ["s::lib"],
                     "filter_terms": " [Vchan] \r\n广告\n\n广告"},
                    {"id": "completion", "functions": ["metadata_completion"], "fields": ["summary"],
                     "ai_completion": True, "include_volumes": False, "card_ids": ["s::lib"], "time_limit_hours": 1.5},
                ]})
                # Force loading only config.py, as after a backup restore.
                (root / "state.json").unlink()
                tasks = web_backend._read_state()["METADATA_TASKS"]
                self.assertEqual(tasks[0]["operations"], ["simplify", "extract_title"])
                self.assertEqual(tasks[0]["filter_terms"], "[Vchan]\n广告")
                self.assertEqual(tasks[1]["filter_terms"], "")
                self.assertTrue(tasks[0]["include_locked"])
                self.assertFalse(tasks[0]["lock_completed"])
                self.assertEqual(tasks[0]["fields"], ["title", "summary"])
                self.assertTrue(tasks[1]["ai_completion"])
                self.assertTrue(tasks[0]["include_volumes"])
                self.assertFalse(tasks[1]["include_volumes"])
                self.assertEqual(tasks[0]["time_limit_hours"], 0)
                self.assertEqual(tasks[1]["time_limit_hours"], 1.5)


if __name__ == "__main__":
    unittest.main()
