import ast
import hashlib
import json
import os
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import web_backend
from services.media_policy import media_type, scrape_enabled
from services.library_selection import is_configured_library
from services.runtime_service import configure_automatic_libraries, configure_server
from tools.resort_search_results_list import resort_search_list


class MediaPolicyTests(unittest.TestCase):
    def test_defaults_and_migration(self):
        self.assertEqual(media_type({}), "comic")
        self.assertEqual(media_type({"IS_NOVEL_ONLY": True}), "book")
        self.assertEqual(media_type({"MEDIA_TYPE": "mixed", "IS_NOVEL_ONLY": True}), "mixed")
        self.assertTrue(scrape_enabled({}))
        self.assertFalse(scrape_enabled({"SCRAPE_ENABLED": False}))

    def test_runtime_filters_disabled_without_changing_saved_cards(self):
        cards = [{"LIBRARY": "active", "SERVER_ID": "a"}, {"LIBRARY": "disabled", "SERVER_ID": "a", "SCRAPE_ENABLED": False},
                 {"LIBRARY": "other", "SERVER_ID": "b"}]
        config = SimpleNamespace(KOMGA_SERVERS=[{"id": "a"}], KOMGA_LIBRARY_LIST=cards, KOMGA_COLLECTION_LIST=["old"])
        configure_server(config, "a")
        self.assertTrue(configure_automatic_libraries(config))
        self.assertEqual([card["LIBRARY"] for card in config.KOMGA_LIBRARY_LIST], ["active"])
        self.assertEqual(len(cards), 3)
        self.assertEqual(config.KOMGA_COLLECTION_LIST, [])
        self.assertFalse(is_configured_library(cards, "disabled"))
        self.assertTrue(is_configured_library(cards, "active"))
        self.assertFalse(configure_automatic_libraries(SimpleNamespace(KOMGA_LIBRARY_LIST=[cards[1]])))

    def test_media_modes_restrict_search_candidates(self):
        results = [{"id": index, "type": 1, "series": True, "name": "同名作品", "name_cn": "",
                    "infobox": [], "platform": platform} for index, platform in enumerate([1001, 1002, 1003, "其他", 1])]
        self.assertEqual([r["id"] for r in resort_search_list("同名作品", results, 80, "comic")], [0])
        self.assertEqual([r["id"] for r in resort_search_list("同名作品", results, 80, "book")], [1, 2, 3])
        self.assertEqual([r["id"] for r in resort_search_list("同名作品", results, 80, "mixed")], [0, 1, 2, 3])

    def test_manual_refresh_scopes_card_and_does_not_require_auto_enabled(self):
        context = {"a::lib": {"server_id": "a", "library_id": "lib"},
                   "b::lib": {"server_id": "b", "library_id": "lib"}}
        with patch.object(web_backend, "_configured_library_context", return_value=context), \
             patch.object(web_backend, "_run_managed") as run:
            web_backend._manual_refresh_targets(["b::lib"], False)
        run.assert_called_once()
        self.assertEqual(run.call_args.args[1],
                         {"server_id": "b", "library_ids": ["lib"], "full": False})

    def test_sse_disabled_library_is_rejected_before_fetch(self):
        tree = ast.parse((Path(__file__).parents[1] / "services/sse_service.py").read_text(encoding="utf-8"))
        function = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "series_update_sse_handler")
        scope = {"_is_surveilled_library": lambda _: False, "get_series_metadata": Mock(),
                 "refresh_metadata": Mock(), "logger": Mock()}
        exec(compile(ast.Module(body=[function], type_ignores=[]), "<sse-handler>", "exec"), scope)
        scope["series_update_sse_handler"]({"event_type": "SeriesAdded", "event_data": {"seriesId": "s", "libraryId": "off"}})
        scope["get_series_metadata"].assert_not_called()
        scope["refresh_metadata"].assert_not_called()

    def test_watermarks_are_isolated_by_server_and_library(self):
        tree = ast.parse((Path(__file__).parents[1] / "core/refresh_metadata.py").read_text(encoding="utf-8"))
        function = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "_watermark_path")
        scope = {"komga": SimpleNamespace(base_url="http://first/api/v1"),
                 "hashlib": hashlib, "os": os, "ARCHIVE_FILES_DIR": "archive"}
        exec(compile(ast.Module(body=[function], type_ignores=[]), "<watermark>", "exec"), scope)
        first = scope["_watermark_path"]("one")
        self.assertNotEqual(first, scope["_watermark_path"]("two"))
        scope["komga"].base_url = "http://second/api/v1"
        self.assertNotEqual(first, scope["_watermark_path"]("one"))


if __name__ == "__main__":
    unittest.main()
