import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import web_backend
from tools.db import init_sqlite3, record_scrape_event


class RecordComparisonTests(unittest.TestCase):
    def test_new_snapshot_event_is_visible_even_with_legacy_series_history(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            _, conn = init_sqlite3(root / "recordsRefreshed.db")
            context = {"s::lib": {"server_id": "s", "library_id": "lib", "server_name": "服务"}}
            with patch.object(web_backend, "ROOT", root), \
                    patch.object(web_backend, "_configured_library_context", return_value=context), \
                    patch.object(web_backend, "_cleanup_expired_records"), \
                    patch.object(web_backend, "_schedule_path_backfill"):
                record_scrape_event(conn, "漫画", "书名", "lib", "库", ["title"],
                                    event_kind="series", server_id="s", source_title="书名")
                old = web_backend._read_scrape_records()[0]
                record_scrape_event(conn, "漫画", "书名", "lib", "库", ["summary"],
                                    event_kind="series", server_id="s", source_title="书名",
                                    metadata_before={"summary": "旧简介"}, metadata_after={"summary": "新简介"})
                new = web_backend._read_scrape_records()[0]
                self.assertNotEqual(old["id"], new["id"])
                self.assertEqual(old["group_key"], new["group_key"])
                self.assertEqual([item["id"] for item in new["volumes"]], [2, 1])
                self.assertEqual(new["volume_count"], 2)
                comparison = web_backend._read_record_comparison(new["volumes"][0]["id"])
                self.assertEqual(comparison["before"], {"summary": "旧简介"})
                self.assertEqual(comparison["after"], {"summary": "新简介"})
                self.assertEqual([item["id"] for item in web_backend._read_record_details(new["id"])["items"]], [2, 1])
            conn.close()

    def test_snapshots_are_persistent_scoped_and_not_in_list(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            _, conn = init_sqlite3(root / "recordsRefreshed.db")
            before = {"title": "原名", "summary": "", "authors": [{"name": "作者"}]}
            after = {**before, "title": "新名", "titleLock": True}
            record_scrape_event(conn, "漫画", "新名", "lib", "漫画库", ["title", "titleLock"],
                               server_id="server", metadata_before=before, metadata_after=after)
            record_scrape_event(conn, "漫画", "旧记录", "lib", "漫画库", [], server_id="server")
            record_scrape_event(conn, "漫画", "其他服务", "lib", "漫画库", [], server_id="other")
            conn.close()
            context = {"server::lib": {"server_id": "server", "library_id": "lib", "server_name": "测试"}}
            with patch.object(web_backend, "ROOT", root), \
                    patch.object(web_backend, "_configured_library_context", return_value=context), \
                    patch.object(web_backend, "_cleanup_expired_records"):
                comparison = web_backend._read_record_comparison("book:lib:1")
                self.assertEqual(comparison["before"], before)
                self.assertEqual(comparison["after"], after)
                self.assertIsNone(web_backend._read_record_comparison(2)["before"])
                self.assertIsNone(web_backend._read_record_comparison(3))
                self.assertIsNone(web_backend._read_record_comparison(999))
                self.assertNotIn("metadata_before", web_backend._read_scrape_rows([1])[0])

    def test_old_schema_migration_keeps_historical_snapshot_unknown(self):
        with tempfile.TemporaryDirectory() as folder:
            db = Path(folder) / "recordsRefreshed.db"
            conn = sqlite3.connect(db)
            conn.execute("""CREATE TABLE scrape_records (
                id INTEGER PRIMARY KEY, item_type TEXT, item_title TEXT, library_id TEXT,
                library_name TEXT, metadata_fields TEXT, status TEXT, recorded_at TEXT)""")
            conn.execute("INSERT INTO scrape_records VALUES (1,'漫画','旧名','lib','库','title','success','2026-09-20')")
            conn.commit()
            conn.close()
            _, conn = init_sqlite3(db)
            self.assertEqual(conn.execute("SELECT metadata_before,metadata_after FROM scrape_records").fetchone(), (None, None))
            conn.close()
