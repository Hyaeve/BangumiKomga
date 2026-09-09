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


if __name__ == "__main__":
    unittest.main()
