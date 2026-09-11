"""Exercise actual HTTP clients against isolated local protocol fixtures."""
import json
import tempfile
import threading
import unittest
from contextlib import closing
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

import web_backend
from api.komga_api import KomgaApi
from tools.db import init_sqlite3, record_scrape_event
from tools.translation_task import translate_library
from tools.summary_translation import translate_summary_to_zh


class IntegrationHTTPTests(unittest.TestCase):
    def setUp(self):
        self.calls = []
        self.metadata = {"summary": "A young reader discovers a secret library.", "summaryLock": False}
        owner = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def reply(self, data, status=200):
                raw = json.dumps(data).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)

            def body(self):
                return json.loads(self.rfile.read(int(self.headers["Content-Length"])))

            def do_POST(self):
                payload = self.body()
                owner.calls.append((self.path, payload, self.headers.get("Authorization")))
                if self.path.startswith("/api/v1/series/list"):
                    self.reply({"content": [{"id": "s1", "libraryId": "lib", "name": "原书名", "metadata": dict(owner.metadata)}], "last": True})
                elif self.path.startswith("/api/v1/books/list"):
                    self.reply({"content": [], "last": True})
                elif self.path == "/v1/chat/completions":
                    self.reply({"choices": [{"message": {"content": [{"type": "text", "text": "年轻读者发现了一座秘密图书馆。"}]}}]})
                elif self.path == "/v1/responses":
                    self.reply({"output": [
                        {"type": "web_search_call", "status": "completed"},
                        {"type": "message", "content": [{
                            "type": "output_text",
                            "text": json.dumps({"summary": {"value": "联网检索简介", "source_urls": ["https://publisher.example/book"]}}),
                            "annotations": [{"type": "url_citation", "url": "https://publisher.example/book"}]
                        }]}
                    ]})
                else:
                    self.reply({}, 404)

            def do_GET(self):
                if self.path == "/api/v2/users/me":
                    self.reply({"id": "fixture"})
                elif self.path == "/api/v1/series/s1":
                    self.reply({"id": "s1", "libraryId": "lib", "name": "原书名", "url": "/data/漫画/原书名", "metadata": dict(owner.metadata)})
                else:
                    self.reply({}, 404)

            def do_PATCH(self):
                payload = self.body()
                owner.calls.append((self.path, payload, None))
                owner.metadata.update(payload)
                self.send_response(204)
                self.end_headers()

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.url = f"http://127.0.0.1:{self.server.server_port}"
        self.komga = KomgaApi(self.url, "", "", "fixture-key")
        self.settings = {"OPENAI_BASE_URL": self.url, "OPENAI_API_KEY": "fixture-ai", "OPENAI_MODEL": "fixture"}

    def tearDown(self):
        self.komga.r.close()
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()

    def test_http_translation_write_lock_and_detail_path(self):
        updates = []
        result = translate_library(self.komga, "lib", self.settings, lambda *args: updates.append(args), lambda *args: None)
        self.assertEqual(result["updated"], 1)
        self.assertTrue(self.metadata["summaryLock"])
        self.assertEqual(self.metadata["summary"], "年轻读者发现了一座秘密图书馆。")
        self.assertEqual(updates[0][0]["url"], "/data/漫画/原书名")
        ai = next(call for call in self.calls if call[0] == "/v1/chat/completions")
        self.assertEqual(ai[2], "Bearer fixture-ai")
        self.assertNotIn("temperature", ai[1])
        # A second execution must not call AI for a locked summary.
        translate_library(self.komga, "lib", self.settings, lambda *args: None, lambda *args: None)
        self.assertEqual(sum(call[0] == "/v1/chat/completions" for call in self.calls), 1)

    def test_explicit_completion_url(self):
        settings = {**self.settings, "OPENAI_BASE_URL": self.url + "/v1/chat/completions"}
        self.assertIn("图书馆", translate_summary_to_zh("A library.", True, settings))

    def test_ai_test_endpoint_calls_translation_and_audits_both_results(self):
        import requests
        server = ThreadingHTTPServer(("127.0.0.1", 0), web_backend.Handler)
        thread = threading.Thread(target=server.serve_forever)
        thread.start()
        url = f"http://127.0.0.1:{server.server_port}/api/ai/test"
        try:
            with patch.object(web_backend, "_read_state", return_value={}), \
                 patch.object(web_backend, "SESSIONS", {"ai-test"}), \
                 patch.object(web_backend, "_write_activity") as audit, \
                 patch.object(web_backend, "save_state") as save:
                self.assertEqual(requests.post(url, json=self.settings).status_code, 401)
                response = requests.post(url, json=self.settings, cookies={"bk_session":"ai-test"})
                self.assertEqual(response.status_code, 200)
                self.assertIn("图书馆", response.json()["translation"])
                self.assertEqual(audit.call_args.args[0], "AI：测试翻译成功")
                self.assertNotIn("fixture-ai", str(audit.call_args))
                response = requests.post(url, json={**self.settings,"OPENAI_API_KEY":""}, cookies={"bk_session":"ai-test"})
                self.assertEqual(response.status_code, 400)
                self.assertEqual(audit.call_args.args[0], "AI：测试翻译失败")
                save.assert_not_called()
        finally:
            server.shutdown()
            server.server_close()
            thread.join()

    def test_strict_translation_rejects_empty_and_untranslated_output(self):
        from unittest.mock import Mock
        for content in ("", "A library.", "some unrelated English text"):
            response = Mock()
            response.json.return_value = {"choices":[{"message":{"content":content}}]}
            with patch("tools.summary_translation.requests.post", return_value=response):
                with self.assertRaises(ValueError):
                    translate_summary_to_zh("A library.", True, self.settings, strict=True)

    def test_task_dispatch_records_path_and_identity(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            state = {**self.settings, "KOMGA_LIBRARY_LIST": [{"SERVER_ID": "server", "LIBRARY": "lib"}]}
            context = {"server::lib": {"library_id": "lib", "server_id": "server", "server_name": "测试服务"}}
            with patch.object(web_backend, "ROOT", root), patch.object(web_backend, "_read_state", return_value=state), \
                 patch.object(web_backend, "_configured_library_context", return_value=context), \
                 patch.object(web_backend, "_load_komga", return_value=self.komga), \
                 patch.object(self.komga, "list_libraries", return_value=[{"id": "lib", "name": "测试库"}]), \
                 patch.object(web_backend, "_write_activity"):
                web_backend._translate_task_libraries(["server::lib"])
                _, conn = init_sqlite3(root / "recordsRefreshed.db")
                with closing(conn):
                    row = conn.execute("SELECT source_path,komga_id,server_id FROM scrape_records").fetchone()
                self.assertEqual(row, ("/data/漫画/原书名", "s1", "server"))

    def test_legacy_path_resolved_even_without_local_id_history(self):
        record = {"source_title": "原书名", "library_id": "lib", "event_kind": "series"}
        item = web_backend._find_legacy_record_item(self.komga, record, "series")
        self.assertEqual(item["id"], "s1")

    def test_identity_backfill_survives_renaming_and_is_read_by_ui(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            _, conn = init_sqlite3(root / "recordsRefreshed.db")
            with closing(conn):
                record_scrape_event(conn, "漫画", "匹配后书名", "lib", "测试库", ["summary"],
                                    source_title="曾经的书名", event_kind="series",
                                    komga_id="s1", server_id="server")
            state = {"KOMGA_LIBRARY_LIST": [{"SERVER_ID": "server", "LIBRARY": "lib"}]}
            with patch.object(web_backend, "ROOT", root), patch.object(web_backend, "_read_state", return_value=state), \
                 patch.object(web_backend, "_load_komga", return_value=self.komga):
                rows = web_backend._read_scrape_rows()
                self.assertEqual(rows[0]["komga_id"], "s1")
                web_backend._backfill_source_paths(rows)
                self.assertEqual(web_backend._read_scrape_rows()[0]["source_path"], "/data/漫画/原书名")

    def test_ambiguous_legacy_name_is_not_used(self):
        duplicate = {"id": "s1", "name": "重复书名"}
        with patch.object(self.komga, "iter_library_series", return_value=iter([duplicate, {**duplicate, "id": "s2"}])):
            self.assertIsNone(web_backend._find_legacy_record_item(
                self.komga, {"source_title": "重复书名", "library_id": "lib"}, "series"))

    def test_ai_failure_keeps_summary_unlocked(self):
        with patch.object(self.server.RequestHandlerClass, "do_POST", lambda handler: handler.reply({}, 401)):
            result = translate_summary_to_zh("English original.", True, self.settings)
        self.assertEqual(result, "English original.")
        self.assertFalse(self.metadata["summaryLock"])

    def test_ai_completion_uses_http_web_search_protocol(self):
        from tools.ai_completion import search_metadata
        result = search_metadata("书名", ["summary"], self.settings)
        self.assertEqual(result, {"summary": "联网检索简介"})
        call = next(call for call in self.calls if call[0] == "/v1/responses")
        self.assertEqual(call[1]["tool_choice"], "required")
        self.assertEqual(call[2], "Bearer fixture-ai")

    def test_correction_task_dispatch_writes_only_selected_field(self):
        self.metadata["summary"] = "這是漫畫簡介"
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            state = {"KOMGA_LIBRARY_LIST": [{"SERVER_ID": "server", "LIBRARY": "lib"}]}
            context = {"server::lib": {"library_id": "lib", "server_id": "server", "server_name": "测试服务"}}
            with patch.object(web_backend, "ROOT", root), patch.object(web_backend, "_read_state", return_value=state), \
                 patch.object(web_backend, "_configured_library_context", return_value=context), \
                 patch.object(web_backend, "_load_komga", return_value=self.komga), \
                 patch.object(self.komga, "list_libraries", return_value=[{"id": "lib", "name": "测试库"}]), \
                 patch.object(web_backend, "_write_activity"):
                web_backend._translate_task_libraries(["server::lib"], ["summary"], correction=["simplify"])
                self.assertEqual(self.metadata["summary"], "这是漫画简介")
                self.assertFalse(self.metadata["summaryLock"])
                _, conn = init_sqlite3(root / "recordsRefreshed.db")
                with closing(conn):
                    event = conn.execute("SELECT metadata_fields,match_source FROM scrape_records").fetchone()
                self.assertEqual(event, ("summary", "计划任务：元数据修正"))


if __name__ == "__main__":
    unittest.main()
