import json
import tempfile
import threading
import unittest
from pathlib import Path
from http.server import ThreadingHTTPServer
from urllib.request import Request, urlopen
from unittest.mock import patch

import web_backend as backend


class RememberLoginTests(unittest.TestCase):
    def test_persistence_expiry_revocation_and_digest_storage(self):
        with tempfile.TemporaryDirectory() as folder, \
                patch.object(backend, "CONFIG_DIR", Path(folder)), \
                patch.object(backend, "_read_auth", return_value={"username": "user", "password_hash": "hash"}) as auth:
            with patch.object(backend.time, "time", return_value=100):
                backend._remembered_session("secret-token", create=True)
                self.assertTrue(backend._remembered_session("secret-token"))
                self.assertFalse(backend._remembered_session("invalid"))
                self.assertNotIn(b"secret-token", (Path(folder) / "web_sessions.db").read_bytes())
            with patch.object(backend.time, "time", return_value=101 + backend.REMEMBER_SECONDS):
                self.assertFalse(backend._remembered_session("secret-token"))
            backend._remembered_session("logout-token", create=True)
            backend._remembered_session("logout-token", remove=True)
            self.assertFalse(backend._remembered_session("logout-token"))
            backend._remembered_session("changed-account", create=True)
            auth.return_value = {"username": "new-user", "password_hash": "new-hash"}
            self.assertFalse(backend._remembered_session("changed-account"))

    def test_login_cookie_modes_restart_and_logout(self):
        with tempfile.TemporaryDirectory() as folder, \
                patch.object(backend, "CONFIG_DIR", Path(folder)), \
                patch.object(backend, "SESSIONS", set()), \
                patch.object(backend, "_read_auth", return_value={"username": "user", "password_hash": backend._password_hash("pass")}), \
                patch.object(backend, "_write_activity"):
            server = ThreadingHTTPServer(("127.0.0.1", 0), backend.Handler)
            thread = threading.Thread(target=server.serve_forever)
            thread.start()
            def request(path, data=None, cookie=""):
                req = Request(f"http://127.0.0.1:{server.server_port}{path}",
                              data=json.dumps(data).encode() if data is not None else None,
                              headers={"Content-Type": "application/json", "Cookie": cookie})
                with urlopen(req) as response:
                    self.assertEqual(response.headers.get("Cache-Control"), "no-store")
                    return response.headers.get("Set-Cookie", ""), json.load(response)
            try:
                ordinary, _ = request("/api/auth/login", {"username": "user", "password": "pass"})
                self.assertNotIn("Max-Age", ordinary)
                remembered, _ = request("/api/auth/login", {"username": "user", "password": "pass", "remember": True})
                self.assertIn(f"Max-Age={backend.REMEMBER_SECONDS}", remembered)
                self.assertIn("HttpOnly", remembered)
                server.shutdown()
                server.server_close()
                thread.join()
                backend.SESSIONS.clear()
                server = ThreadingHTTPServer(("127.0.0.1", 0), backend.Handler)
                thread = threading.Thread(target=server.serve_forever)
                thread.start()
                self.assertTrue(request("/api/auth/session", cookie=remembered.split(";")[0])[1]["authenticated"])
                self.assertFalse(request("/api/auth/session", cookie=ordinary.split(";")[0])[1]["authenticated"])
                cleared, _ = request("/api/auth/logout", {}, remembered.split(";")[0])
                self.assertIn("Max-Age=0", cleared)
                self.assertFalse(request("/api/auth/session", cookie=remembered.split(";")[0])[1]["authenticated"])
            finally:
                server.shutdown()
                server.server_close()
                thread.join()
