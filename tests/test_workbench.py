import json
import sqlite3
import tempfile
import threading
import unittest
from contextlib import ExitStack, closing
from copy import deepcopy
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest.mock import Mock, patch
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import web_backend as backend
from tools import workbench
from tools.correction_task import correct_library


class WorkbenchTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        folder = self.stack.enter_context(tempfile.TemporaryDirectory())
        self.root = Path(folder)
        self.client = Mock()
        self.item = {"id": "one", "libraryId": "lib", "name": "原书名", "url": "/books/原书名",
                     "metadata": {"title": "原书名", "titleLock": False, "summary": "简介", "summaryLock": True}}
        self.client.get_specific_series.side_effect = lambda _: deepcopy(self.item)
        def update(_id, values):
            self.item["metadata"].update(values)
            return True
        self.client.update_series_metadata.side_effect = update
        self.context = {"server::lib": {"library_id": "lib", "server_id": "server", "server_name": "服务"}}
        self.stack.enter_context(patch.object(backend, "ROOT", self.root))
        self.stack.enter_context(patch.object(backend, "_configured_library_context", return_value=self.context))
        self.stack.enter_context(patch.object(backend, "_read_state", return_value={
            "KOMGA_LIBRARY_LIST": [{"LIBRARY": "lib", "SERVER_ID": "server"}]}))
        self.load = self.stack.enter_context(patch.object(backend, "_load_komga", return_value=self.client))
        self.stack.enter_context(patch.object(backend, "_write_activity"))

    def test_paginated_search_and_total_are_scoped(self):
        self.client.list_library_page.side_effect = [
            {"content": [self.item, {**self.item, "libraryId": "other"}], "totalElements": 3},
            {"content": [], "totalElements": 100}]
        data = workbench.read_page(backend, {"card": "server::lib", "page": "1", "q": "书"})
        self.assertEqual(data["total"], 3)
        self.assertEqual(data["library_total"], 100)
        self.assertEqual(len(data["items"]), 1)
        self.client.list_library_page.assert_any_call("lib", 1, 48, "书")
        self.assertIn("/api/workbench/cover?", data["items"][0]["cover"])
        self.client.r.close.assert_called_once()
        self.load.assert_called_once_with("server", require_server=True)

    def test_metadata_save_records_snapshots_and_preserves_locks(self):
        data = workbench.read_item(backend, "server::lib", "one")
        self.assertEqual(data["record"]["source_path"], "/books/原书名")
        result = workbench.save_item(backend, {"card": "server::lib", "id": "one",
                                             "expected": data["current"], "changes": {"summary": "手动简介"}})
        self.assertEqual(result["after"]["summary"], "手动简介")
        self.assertTrue(result["after"]["summaryLock"])
        self.assertEqual(result["before"]["summary"], "简介")
        with closing(sqlite3.connect(self.root / "recordsRefreshed.db")) as conn:
            row = conn.execute("SELECT metadata_before,metadata_after,source_path FROM scrape_records").fetchone()
        self.assertEqual(json.loads(row[0])["summary"], "简介")
        self.assertEqual(json.loads(row[1])["summary"], "手动简介")
        self.assertEqual(row[2], "/books/原书名")

    def test_card_scope_item_scope_and_conflict_reject_before_write(self):
        with self.assertRaises(ValueError):
            workbench.read_item(backend, "unknown::lib", "one")
        self.item["libraryId"] = "other"
        with self.assertRaises(ValueError):
            workbench.read_item(backend, "server::lib", "one")
        self.item["libraryId"] = "lib"
        expected = deepcopy(self.item["metadata"])
        self.item["metadata"]["titleLock"] = True
        with self.assertRaisesRegex(ValueError, "已变化"):
            workbench.save_item(backend, {"card": "server::lib", "id": "one",
                                         "expected": expected, "changes": {"title": "新"}})
        self.client.update_series_metadata.assert_not_called()

    def test_failed_patch_has_no_success_record(self):
        self.client.update_series_metadata.side_effect = None
        self.client.update_series_metadata.return_value = False
        with self.assertRaisesRegex(ValueError, "写入失败"):
            workbench.save_item(backend, {"card": "server::lib", "id": "one",
                                         "expected": self.item["metadata"], "changes": {"title": "新"}})
        self.assertFalse((self.root / "recordsRefreshed.db").exists())

    def test_batch_uses_selected_ids_and_existing_library_queue(self):
        executor = Mock()
        with patch.object(backend, "TASK_EXECUTOR", executor), patch.object(backend, "_run_managed") as managed:
            result = workbench.start_action(backend, {"card": "server::lib", "ids": ["one"],
                                                    "action": "ai_completion", "fields": ["summary"]})
            args = executor.submit.call_args.args
            self.assertEqual(args[1], ["server::lib"])
            args[2]()
            module, payload = managed.call_args.args
            self.assertEqual(module, "services.metadata_task")
            self.assertEqual(payload["series_ids"], ["one"])
            self.assertFalse(payload["include_volumes"])
            self.assertTrue(payload["ai_completion"])
            self.assertTrue(result["started"])
        with self.assertRaises(ValueError):
            workbench.start_action(backend, {"card": "server::lib", "ids": ["one"] * 201,
                                            "action": "simplify", "fields": ["title"]})

    def test_correction_only_visits_selected_series(self):
        self.item["metadata"]["title"] = "繁體標題"
        updates = []
        correct_library(self.client, "lib", {}, lambda *args: updates.append(args), lambda *args: None,
                        ["title"], ["simplify"], include_volumes=False, series_items=[deepcopy(self.item)])
        self.assertEqual(self.item["metadata"]["title"], "繁体标题")
        self.client.iter_library_series.assert_not_called()
        self.client.iter_series_books.assert_not_called()
        self.assertEqual(len(updates), 1)

    def test_http_endpoints_require_authentication(self):
        with patch.object(backend.Handler, "_authorized", return_value=False):
            server = ThreadingHTTPServer(("127.0.0.1", 0), backend.Handler)
            thread = threading.Thread(target=server.serve_forever)
            thread.start()
            try:
                for route, data in [("items", None), ("item", None), ("cover", None), ("item", b"{}"), ("run", b"{}")]:
                    with self.assertRaises(HTTPError) as error:
                        urlopen(Request(f"http://127.0.0.1:{server.server_port}/api/workbench/{route}", data=data))
                    self.assertEqual(error.exception.code, 401)
            finally:
                server.shutdown()
                server.server_close()
                thread.join()

    def test_komga_page_request_uses_server_side_search(self):
        from api.komga_api import KomgaApi
        client = KomgaApi.__new__(KomgaApi)
        client.base_url = "http://fixture/api/v1"
        client.r = Mock()
        client.r.post.return_value.json.return_value = {"content": [], "totalElements": 0}
        client.list_library_page("lib", 2, 48, "漫画")
        kwargs = client.r.post.call_args.kwargs
        self.assertEqual(kwargs["params"]["size"], 48)
        self.assertEqual(kwargs["params"]["page"], 2)
        self.assertEqual(kwargs["json"]["fullTextSearch"], "漫画")
        self.assertEqual(kwargs["json"]["condition"]["allOf"][0]["libraryId"]["value"], "lib")

    def test_cover_is_original_bytes_and_requires_library_scope(self):
        with patch("tools.komga_cover.read_series_cover", return_value=(b"original", "image/png", {})) as read:
            self.assertEqual(workbench.read_cover(backend, "server::lib", "one")[0], b"original")
            read.assert_called_once_with(self.client, "one")
            self.item["libraryId"] = "other"
            with self.assertRaises(ValueError):
                workbench.read_cover(backend, "server::lib", "one")
            self.assertEqual(read.call_count, 1)

    def test_alias_cannot_bypass_canonical_library_queue_key(self):
        self.context["lib"] = self.context["server::lib"]
        with self.assertRaises(ValueError):
            workbench.start_action(backend, {"card": "lib", "ids": ["one"],
                                            "action": "simplify", "fields": ["title"]})
