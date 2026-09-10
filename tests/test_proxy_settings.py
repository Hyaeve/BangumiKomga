import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import requests
import web_backend
from tools.proxy_settings import proxy_kwargs, test_proxy, validate_proxy
from tools.ai_completion import search_metadata
from tools.summary_translation import translate_summary_to_zh
from tools.title_recognition import recognize_title


class ProxySettingsTests(unittest.TestCase):
    proxy = "http://user:secret@127.0.0.1:7890"

    def test_validation_and_no_proxy(self):
        self.assertEqual(validate_proxy("  " + self.proxy + " "), self.proxy)
        for invalid in ("bad", "file:///tmp/a", "http://host:bad", "http://host/path", "http://host:0"):
            with self.assertRaises(ValueError):
                validate_proxy(invalid)
        with patch.dict(os.environ, {"NO_PROXY": "localhost,127.0.0.1", "no_proxy": "localhost,127.0.0.1"}):
            settings = {"OUTBOUND_PROXY_URL": self.proxy}
            self.assertEqual(proxy_kwargs("http://127.0.0.1/v1", settings), {})
            self.assertEqual(proxy_kwargs("https://api.bgm.tv", settings)["proxies"]["https"], self.proxy)
            self.assertEqual(proxy_kwargs("https://api.bgm.tv", {}), {})

    def test_proxy_test_uses_fixed_target_without_tokens_and_hides_errors(self):
        with patch("tools.proxy_settings.requests.Session") as session:
            client = session.return_value.__enter__.return_value
            client.get.return_value.__enter__.return_value.status_code = 200
            self.assertTrue(test_proxy(self.proxy)["ok"])
            self.assertFalse(client.trust_env)
            self.assertEqual(client.get.call_args.args[0], "https://api.bgm.tv/v0/subjects/1")
            self.assertEqual(client.get.call_args.kwargs["proxies"]["https"], self.proxy)
            client.get.side_effect = requests.ConnectionError(self.proxy)
            with self.assertRaises(ValueError) as caught:
                test_proxy(self.proxy)
            self.assertNotIn("secret", str(caught.exception))

    def test_save_reload_and_clear_proxy_in_config(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            with patch.object(web_backend, "CONFIG_DIR", root), \
                 patch.object(web_backend, "CONFIG_FILE", root / "config.py"), \
                 patch.object(web_backend, "WEB_STATE", root / "state.json"):
                web_backend.save_state({"OUTBOUND_PROXY_URL": self.proxy})
                self.assertEqual(web_backend._read_state()["OUTBOUND_PROXY_URL"], self.proxy)
                self.assertIn("OUTBOUND_PROXY_URL", (root / "config.py").read_text())
                web_backend.save_state({"OUTBOUND_PROXY_URL": ""})
                self.assertEqual(web_backend._read_state()["OUTBOUND_PROXY_URL"], "")

    def test_all_ai_requests_use_configured_proxy(self):
        settings = {"OPENAI_BASE_URL": "https://ai.example/v1", "OPENAI_API_KEY": "key",
                    "OPENAI_MODEL": "model", "OUTBOUND_PROXY_URL": self.proxy}
        response = Mock()
        response.json.return_value = {"choices": [{"message": {"content": "中文标题"}}], "output": []}
        with patch.dict(os.environ, {"NO_PROXY": "", "no_proxy": ""}), \
             patch("requests.post", return_value=response) as post:
            recognize_title("Book", settings=settings)
            translate_summary_to_zh("Summary", enabled_override=True, settings=settings)
            search_metadata("Book", ["summary"], settings)
            self.assertEqual(post.call_count, 3)
            self.assertTrue(all(call.kwargs["proxies"]["https"] == self.proxy for call in post.call_args_list))

    def test_bangumi_factory_passes_proxy_to_metadata_request(self):
        from api.bangumi_api import BangumiDataSourceFactory
        with patch.dict(os.environ, {"NO_PROXY": "", "no_proxy": ""}), \
             patch("api.bangumi_api.requests.Session") as session:
            source = BangumiDataSourceFactory.create({"proxy_url": self.proxy})
            source.get_subject_metadata(1)
            self.assertEqual(session.return_value.get.call_args.kwargs["proxies"]["https"], self.proxy)


if __name__ == "__main__":
    unittest.main()
