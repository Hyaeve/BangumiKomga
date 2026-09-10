"""Real HTTP cover forwarding: no mocked Komga client or login-cover handler."""
import json
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen
from unittest.mock import patch

import web_backend as backend


class LoginCoverHTTPTests(unittest.TestCase):
    def setUp(self):
        self.image = (Path(__file__).parents[1] / "web/logo-icon.png").read_bytes()
        self.fallback = False
        self.invalid_image = False
        self.calls = []
        owner = self

        class KomgaHandler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def reply(self, body, mime="application/json", status=200):
                self.send_response(status)
                self.send_header("Content-Type", mime)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_GET(self):
                owner.calls.append((self.path, self.headers.get("Accept")))
                if self.path == "/api/v2/users/me":
                    self.reply(b"{}")
                elif self.path == "/api/v1/login/set-cookie":
                    self.send_response(204)
                    self.send_header("Set-Cookie", "fixture=ok; Path=/")
                    self.end_headers()
                elif not (self.headers.get("X-API-Key") == "fixture-key" or self.headers.get("Cookie") == "fixture=ok"):
                    self.reply(b"{}", status=401)
                elif self.path.endswith("/thumbnails"):
                    self.reply(json.dumps([{"id": "other"}, {"id": "selected", "selected": True}]).encode())
                elif self.path.endswith("/thumbnail") or self.path.endswith("/thumbnails/selected"):
                    if "image/" not in (self.headers.get("Accept") or ""):
                        self.reply(b"{}", status=406)
                    elif owner.fallback and self.path.endswith("/thumbnail"):
                        self.reply(b"{}", status=404)
                    elif owner.invalid_image:
                        self.reply(b"<html>not a cover</html>", "text/html")
                    else:
                        self.reply(owner.image, "image/png; charset=binary")
                else:
                    self.reply(b"{}", status=404)

        self.komga = ThreadingHTTPServer(("127.0.0.1", 0), KomgaHandler)
        self.web = ThreadingHTTPServer(("127.0.0.1", 0), backend.Handler)
        self.state = {"KOMGA_SERVERS": [{"id": "s", "base_url": f"http://127.0.0.1:{self.komga.server_port}",
                                       "api_key": "fixture-key", "email": "", "password": ""}],
                      "KOMGA_LIBRARY_LIST": [{"SERVER_ID": "s", "LIBRARY": "lib", "LOGIN_BACKGROUND": True}]}
        self.patches = [
            patch.object(backend, "_read_state", return_value=self.state),
            patch.object(backend, "_load_preview_cache"),
            patch.object(backend, "PREVIEW_CACHE", {("s", "lib"): {"items": [{"id": "series", "url": "unused"}]}}),
            patch.object(backend, "SESSIONS", {"fixture-session"}),
        ]
        for item in self.patches:
            item.start()
        self.threads = [threading.Thread(target=server.serve_forever) for server in (self.komga, self.web)]
        for thread in self.threads:
            thread.start()
        self.url = f"http://127.0.0.1:{self.web.server_port}"

    def tearDown(self):
        for server in (self.web, self.komga):
            server.shutdown()
            server.server_close()
        for thread in self.threads:
            thread.join()
        for item in reversed(self.patches):
            item.stop()

    def public_cover_url(self):
        with urlopen(self.url + "/api/login-background") as response:
            return self.url + json.load(response)["items"][0]["url"]

    def test_public_and_private_routes_return_identical_original_images(self):
        public_url = self.public_cover_url()
        with urlopen(public_url) as response:
            self.assertEqual(response.read(), self.image)
            self.assertEqual(response.headers["Content-Type"], "image/png")
            self.assertEqual(response.headers["Cache-Control"], "no-store")
        private = Request(self.url + "/api/komga/cover?server_id=s&series_id=series",
                          headers={"Cookie": "bk_session=fixture-session"})
        with urlopen(private) as response:
            self.assertEqual(response.read(), self.image)
        self.assertTrue(all("image/" in accept for path, accept in self.calls if path.endswith("/thumbnail")))
        with self.assertRaises(HTTPError) as error:
            urlopen(private.full_url)
        self.assertEqual(error.exception.code, 401)
        self.state["KOMGA_LIBRARY_LIST"][0]["LOGIN_BACKGROUND"] = False
        with self.assertRaises(HTTPError) as error:
            urlopen(public_url)
        self.assertEqual(error.exception.code, 404)

    def test_selected_thumbnail_fallback_works_with_password_auth(self):
        self.fallback = True
        self.state["KOMGA_SERVERS"][0].update(api_key="", email="fixture", password="fixture")
        with urlopen(self.public_cover_url()) as response:
            self.assertEqual(response.read(), self.image)
        self.assertTrue(any(path.endswith("/thumbnails/selected") for path, _ in self.calls))

    def test_non_image_and_oversized_responses_are_not_exposed(self):
        public_url = self.public_cover_url()
        self.invalid_image = True
        with self.assertRaises(HTTPError) as error:
            urlopen(public_url)
        self.assertEqual(error.exception.code, 404)
        self.invalid_image = False
        with patch("tools.komga_cover.MAX_COVER_BYTES", 8):
            with self.assertRaises(HTTPError) as error:
                urlopen(public_url)
            self.assertEqual(error.exception.code, 404)


if __name__ == "__main__":
    unittest.main()
