import json
import sqlite3
import tempfile
import unittest
from contextlib import closing, contextmanager, ExitStack
from copy import deepcopy
from pathlib import Path
from unittest.mock import Mock, patch

import web_backend
from tools.db import init_sqlite3, record_scrape_event
from tools.record_edit import validate_changes


class RecordEditTests(unittest.TestCase):
    def _fixture(self, root):
        _, conn = init_sqlite3(root / "recordsRefreshed.db")
        before = {"title": "原名", "summary": "原简介", "tags": ["旧标签"], "titleLock": False}
        after = {**before, "title": "匹配名"}
        record_scrape_event(conn, "漫画", "匹配名", "lib", "库", ["title"], source_title="原名",
                            matched_title="匹配名", event_kind="series", komga_id="series-1",
                            server_id="server", metadata_before=before, metadata_after=after)
        conn.close()
        return before, after

    def test_manual_edit_writes_komga_and_updates_record(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            before, after = self._fixture(root)
            client = Mock()
            current = {"id": "series-1", "libraryId": "lib", "metadata": dict(after)}
            client.get_specific_series.side_effect = [current, {"metadata": {**current["metadata"], "summary": "新简介", "tags": ["新标签"]}}]
            client.update_series_metadata.return_value = True
            context = {"server::lib": {"server_id": "server", "library_id": "lib", "server_name": "服务"}}
            with patch.object(web_backend, "ROOT", root), \
                 patch.object(web_backend, "_configured_library_context", return_value=context), \
                 patch.object(web_backend, "_load_komga", return_value=client), \
                 patch.object(web_backend, "_cleanup_expired_records"), \
                 patch.object(web_backend, "_write_activity"):
                result = web_backend._save_record_edit({
                    "id": "1", "revision": web_backend._read_record_comparison(1)["revision"],
                    "expected": after,
                    "changes": {"summary": "新简介", "tags": ["新标签"]},
                })
                client.update_series_metadata.assert_called_once_with("series-1", {"summary": "新简介", "tags": ["新标签"]})
                self.assertEqual(result["after"]["summary"], "新简介")
                self.assertEqual(result["after"]["tags"], ["新标签"])
                self.assertEqual(result["before"], before)
                with closing(sqlite3.connect(root / "recordsRefreshed.db")) as conn:
                    row = conn.execute("SELECT metadata_after,match_source FROM scrape_records WHERE id=1").fetchone()
                self.assertEqual(json.loads(row[0])["summary"], "新简介")
                self.assertIn("手动修订", row[1])

    def test_concurrent_change_is_rejected_without_patch(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            _, after = self._fixture(root)
            client = Mock()
            client.get_specific_series.return_value = {"id": "series-1", "libraryId": "lib",
                                                       "metadata": {**after, "summary": "其他人已改"}}
            with patch.object(web_backend, "ROOT", root), \
                 patch.object(web_backend, "_configured_library_context", return_value={
                     "server::lib": {"server_id": "server", "library_id": "lib", "server_name": "服务"}}), \
                 patch.object(web_backend, "_load_komga", return_value=client), \
                 patch.object(web_backend, "_cleanup_expired_records"):
                with self.assertRaisesRegex(ValueError, "已变化"):
                    web_backend._save_record_edit({
                        "id": "1", "revision": web_backend._read_record_comparison(1)["revision"],
                        "expected": after, "changes": {"summary": "手动修改"}})
                client.update_series_metadata.assert_not_called()

    def test_edit_validation_rejects_bad_values_and_lock_fields(self):
        with self.assertRaises(ValueError):
            validate_changes({"title": ""}, "series")
        with self.assertRaises(ValueError):
            validate_changes({"summaryLock": False}, "series")
        with self.assertRaises(ValueError):
            validate_changes({"links": [{"label": "x", "url": "javascript:bad"}]}, "series")
        self.assertEqual(validate_changes({"tags": ["一个标签"]}, "series"), {"tags": ["一个标签"]})

    def test_deleted_server_is_not_replaced_with_default_server(self):
        with patch.object(web_backend, "_read_state", return_value={
                "KOMGA_SERVERS": [], "KOMGA_BASE_URL": "http://default.invalid", "KOMGA_API_KEY": "fixture"}):
            with self.assertRaisesRegex(ValueError, "不能使用默认服务代替"):
                web_backend._load_komga("deleted-server", require_server=True)

    @contextmanager
    def editing_environment(self, kind="series"):
        with tempfile.TemporaryDirectory() as folder, ExitStack() as stack:
            root = Path(folder)
            before, after = self._fixture(root)
            with closing(sqlite3.connect(root / "recordsRefreshed.db")) as conn:
                conn.execute("UPDATE scrape_records SET event_kind=?", (kind,))
                conn.commit()
            client = Mock()
            current = deepcopy(after)
            def get(_):
                return {"id": "series-1", "libraryId": "lib", "metadata": deepcopy(current)}
            def update(_, payload):
                current.update(payload)
                return True
            client.get_specific_series.side_effect = get
            client.get_specific_book.side_effect = get
            client.update_series_metadata.side_effect = update
            client.update_book_metadata.side_effect = update
            stack.enter_context(patch.object(web_backend, "ROOT", root))
            stack.enter_context(patch.object(web_backend, "_configured_library_context", return_value={
                "server::lib": {"server_id": "server", "library_id": "lib", "server_name": "服务"}}))
            stack.enter_context(patch.object(web_backend, "_load_komga", return_value=client))
            stack.enter_context(patch.object(web_backend, "_cleanup_expired_records"))
            stack.enter_context(patch.object(web_backend, "_write_activity"))
            edit = web_backend._read_record_edit(1)
            body = {"id": 1, "revision": edit["revision"], "expected": edit["current"],
                    "changes": {"summary": "手动简介"}}
            yield root, client, current, body

    def test_volume_uses_book_patch_and_preserves_unrelated_changes(self):
        with self.editing_environment("volume") as (root, client, current, body):
            current["titleLock"] = True
            result = web_backend._save_record_edit(body)
            client.update_book_metadata.assert_called_once_with("series-1", {"summary": "手动简介"})
            client.update_series_metadata.assert_not_called()
            self.assertTrue(result["after"]["titleLock"])
            self.assertEqual(result["before"]["summary"], "原简介")
            with closing(sqlite3.connect(root / "recordsRefreshed.db")) as conn:
                self.assertEqual(conn.execute("SELECT COUNT(*) FROM activity_logs WHERE action='手动修订：成功'").fetchone()[0], 1)

    def test_failed_komga_write_keeps_history_unchanged(self):
        with self.editing_environment() as (_, client, current, body):
            original = web_backend._read_record_comparison(1)
            client.update_series_metadata.side_effect = None
            client.update_series_metadata.return_value = False
            with self.assertRaisesRegex(ValueError, "写入失败"):
                web_backend._save_record_edit(body)
            self.assertEqual(web_backend._read_record_comparison(1), original)

    def test_readback_mismatch_does_not_claim_record_saved(self):
        with self.editing_environment() as (_, client, current, body):
            original = web_backend._read_record_comparison(1)
            client.update_series_metadata.side_effect = None
            client.update_series_metadata.return_value = True
            with self.assertRaisesRegex(ValueError, "回读结果"):
                web_backend._save_record_edit(body)
            self.assertEqual(web_backend._read_record_comparison(1), original)

    def test_stale_revision_and_changed_lock_are_rejected(self):
        with self.editing_environment() as (_, client, current, body):
            with self.assertRaisesRegex(ValueError, "记录已被"):
                web_backend._save_record_edit({**body, "revision": "stale"})
            current["summaryLock"] = True
            with self.assertRaisesRegex(ValueError, "锁定状态已变化"):
                web_backend._save_record_edit(body)
            client.update_series_metadata.assert_not_called()

    def test_moved_or_removed_media_never_writes(self):
        with self.editing_environment() as (_, client, current, body):
            client.get_specific_series.side_effect = lambda _: {"id": "series-1", "libraryId": "other", "metadata": current}
            with self.assertRaisesRegex(ValueError, "不属于此媒体库"):
                web_backend._save_record_edit(body)
            with patch.object(web_backend, "_configured_library_context", return_value={}):
                with self.assertRaisesRegex(ValueError, "不属于已添加"):
                    web_backend._save_record_edit(body)
            client.update_series_metadata.assert_not_called()

    def test_set_order_normalization_is_not_a_failed_save(self):
        with self.editing_environment() as (_, client, current, body):
            def update(_, payload):
                current.update(payload)
                current["tags"] = sorted(current["tags"])
                return True
            client.update_series_metadata.side_effect = update
            result = web_backend._save_record_edit({**body, "changes": {"tags": ["z", "a"]}})
            self.assertEqual(result["after"]["tags"], ["a", "z"])

    def test_edit_http_requires_login_and_roundtrips(self):
        import threading
        import requests
        from http.server import ThreadingHTTPServer
        with self.editing_environment() as (_, client, current, body), \
                patch.object(web_backend, "SESSIONS", {"edit-test"}):
            server = ThreadingHTTPServer(("127.0.0.1", 0), web_backend.Handler)
            thread = threading.Thread(target=server.serve_forever)
            thread.start()
            url = f"http://127.0.0.1:{server.server_port}/api/scrape-records/edit"
            try:
                self.assertEqual(requests.get(url + "?id=1", timeout=5).status_code, 401)
                self.assertEqual(requests.post(url, json=body, timeout=5).status_code, 401)
                client.update_series_metadata.assert_not_called()
                cookies = {"bk_session": "edit-test"}
                response = requests.get(url + "?id=1", cookies=cookies, timeout=5)
                self.assertEqual(response.status_code, 200)
                self.assertIn("summary", response.json()["editable_fields"])
                response = requests.post(url, cookies=cookies, json=body, timeout=5)
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.json()["after"]["summary"], "手动简介")
            finally:
                server.shutdown()
                server.server_close()
                thread.join()
