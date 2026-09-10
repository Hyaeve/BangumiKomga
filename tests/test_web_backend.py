import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

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


if __name__ == "__main__":
    unittest.main()
