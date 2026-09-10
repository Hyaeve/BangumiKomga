import json
import tempfile
import threading
import unittest
from pathlib import Path
from http.server import ThreadingHTTPServer
from urllib.request import urlopen
from urllib.error import HTTPError
from unittest.mock import Mock, patch

import web_backend as backend


class LoginBackgroundTests(unittest.TestCase):
    def setUp(self):
        self.state = {"KOMGA_LIBRARY_LIST": [
            {"SERVER_ID": "s", "LIBRARY": "public", "LOGIN_BACKGROUND": True},
            {"SERVER_ID": "s", "LIBRARY": "private"}]}
        self.cache = {("s", name): {"items": [{"id": name + "-series", "url": "private-internal-url"}]}
                      for name in ("public", "private")}
        self.patches = [
            patch.object(backend, "_read_state", return_value=self.state),
            patch.object(backend, "PREVIEW_CACHE", self.cache),
            patch.object(backend, "_load_preview_cache"),
            patch.object(backend, "LOGIN_PREVIEW_PENDING", set()),
            patch.object(backend, "LOGIN_PREVIEW_RETRY_AT", {}),
        ]
        for item in self.patches:
            item.start()

    def tearDown(self):
        for item in reversed(self.patches):
            item.stop()

    def test_opt_in_only_and_revocation_is_immediate(self):
        entries = backend._login_background_entries()
        self.assertEqual(list(entries.values()), [("s", "public", "public-series")])
        token = next(iter(entries))
        self.assertEqual(len(token), 64)
        self.state["KOMGA_LIBRARY_LIST"][0]["LOGIN_BACKGROUND"] = False
        self.assertEqual(backend._login_background_entries(), {})
        with patch.object(backend, "_load_komga") as load:
            with self.assertRaises(ValueError):
                backend._login_cover(token)
            with self.assertRaises(ValueError):
                backend._login_cover("arbitrary-series")
            load.assert_not_called()

    def test_public_manifest_hides_library_ids_and_private_apis_stay_protected(self):
        server = ThreadingHTTPServer(("127.0.0.1", 0), backend.Handler)
        thread = threading.Thread(target=server.serve_forever)
        thread.start()
        url = f"http://127.0.0.1:{server.server_port}"
        try:
            payload = json.load(urlopen(url + "/api/login-background"))
            self.assertEqual(len(payload["items"]), 1)
            self.assertEqual(set(payload["items"][0]), {"url"})
            self.assertNotIn("public-series", json.dumps(payload))
            with self.assertRaises(HTTPError) as caught:
                urlopen(url + "/api/config")
            self.assertEqual(caught.exception.code, 401)
            self.assertEqual(json.load(urlopen(url + "/api/auth/session"))["username"], "")
            with patch.object(backend, "_login_cover", return_value=(b"cover", "image/png")):
                response = urlopen(url + payload["items"][0]["url"])
                self.assertEqual(response.headers["Cache-Control"], "no-store")
                self.assertEqual(response.read(), b"cover")
        finally:
            server.shutdown()
            server.server_close()
            thread.join()

    def test_partial_cache_updates_do_not_overwrite_other_worker_entries(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "covers.json"
            with patch.object(backend, "PREVIEW_CACHE_FILE", path):
                backend._persist_preview_cache(("s", "public"))
                with patch.object(backend, "PREVIEW_CACHE", {("s", "private"): self.cache[("s", "private")]}):
                    backend._persist_preview_cache(("s", "private"))
                saved = json.loads(path.read_text(encoding="utf-8"))
                self.assertEqual(len(saved), 2)

    def test_cold_login_initializes_only_opted_in_cards_once(self):
        self.cache.clear()
        with patch.object(backend.threading, "Thread") as thread:
            backend._prepare_login_previews()
            backend._prepare_login_previews()
            thread.assert_called_once()
            self.assertEqual(thread.call_args.kwargs["args"], (("s", "public"),))
            worker = thread.call_args.kwargs["target"]
        with patch.object(backend, "_preview_items") as preview:
            worker(("s", "public"))
            preview.assert_called_once_with("s", "public")
        self.assertEqual(backend.LOGIN_PREVIEW_PENDING, set())
        with patch.object(backend.threading, "Thread") as thread:
            backend._prepare_login_previews()
            thread.assert_not_called()

    def test_existing_collages_are_not_automatically_refreshed(self):
        with patch.object(backend.threading, "Thread") as thread:
            backend._prepare_login_previews()
            thread.assert_not_called()

    def test_slow_komga_does_not_hold_global_cache_lock(self):
        started, release = threading.Event(), threading.Event()
        def fetch(**kwargs):
            started.set()
            release.wait(5)
            return {"content": [{"id": "new-series"}]}
        client = Mock()
        client.get_latest_series.side_effect = fetch
        self.cache.clear()
        with patch.object(backend, "_load_komga", return_value=client), \
             patch.object(backend, "_persist_preview_cache"):
            worker = threading.Thread(target=backend._preview_items, args=("s", "public"))
            worker.start()
            try:
                self.assertTrue(started.wait(2))
                acquired = backend.PREVIEW_CACHE_LOCK.acquire(timeout=0.2)
                if acquired:
                    backend.PREVIEW_CACHE_LOCK.release()
                self.assertTrue(acquired)
            finally:
                release.set()
                worker.join(5)
            self.assertEqual(len(backend._login_background_entries()), 1)

    def test_default_runtime_mode_is_realtime(self):
        self.assertEqual(backend.DEFAULTS["BANGUMI_KOMGA_SERVICE_TYPE"], "sse")


if __name__ == "__main__":
    unittest.main()
