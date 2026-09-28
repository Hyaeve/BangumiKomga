import unittest
from unittest.mock import Mock, patch

from api.provider_source import ProviderDataSource, encode_id, decode_id
from tools.provider_settings import validate_providers
from tools.provider_filters import bangumi_tags


class ProviderSourceTests(unittest.TestCase):
    def test_identity_and_get_routing(self):
        primary = Mock()
        source = ProviderDataSource(primary, [{"name": "ANILIST", "enabled": True, "priority": 40}])
        item = {"provider": "ANILIST", "id": "42", "media_type": "comic",
                "titles": [{"name": "Test"}], "fields": {"title": "Test", "summary": "Summary"}}
        with patch("api.provider_source.core_request", return_value=item) as native:
            self.assertEqual(source.get_subject_metadata("provider:ANILIST:42")["name"], "Test")
            native.assert_called_once()
        primary.get_subject_metadata.assert_not_called()
        source.get_subject_metadata(42)
        primary.get_subject_metadata.assert_called_once_with(42)
        self.assertEqual(source.get_related_subjects("provider:ANILIST:42"), [])
        self.assertEqual(decode_id(encode_id("WEBTOONS", "/en/test/list?title_no=42")), ("WEBTOONS", "/en/test/list?title_no=42"))

    def test_fallback_is_separate_from_bangumi_search(self):
        primary = Mock()
        source = ProviderDataSource(primary)
        source.search_subjects("Title", 80, "comic")
        primary.search_subjects.assert_called_once_with("Title", 80, "comic")
        with patch("api.provider_source.core_request", return_value={"match": None, "errors": []}) as native:
            self.assertIsNone(source.search_other_providers(["a", "b", "a"], "mixed"))
            self.assertEqual(native.call_args.args[1]["queries"], ["a", "b"])

    def test_configuration_rejects_unsupported_fields_and_duplicates(self):
        for value in [
            [{"name": "FAKE"}], [{"name": "MAL"}, {"name": "MAL"}],
            [{"name": "MAL", "enabled": "yes"}], [{"name": "MAL", "fields": {"titleLock": True}}],
            [{"name": "ANILIST", "tags_size_limit": -1}], [{"name": "MAL", "base_url": "http://localhost"}],
        ]:
            with self.subTest(value=value), self.assertRaises(ValueError):
                validate_providers(value)

    def test_provider_default_priorities_are_preserved(self):
        self.assertEqual(validate_providers([{"name": "ANILIST"}])[0]["priority"], 40)
        self.assertEqual(validate_providers([{"name": "COMIC_VINE"}])[0]["priority"], 110)

    def test_cover_uses_proxy_and_rejects_redirects_or_non_images(self):
        source = ProviderDataSource(Mock(), [], proxy="http://localhost:7890")
        metadata = {"provider": "ANILIST", "name": "Test", "_provider_cover": "https://s4.anilist.co/test.jpg"}
        response = Mock(status_code=200, headers={"Content-Type": "image/jpeg"})
        response.iter_content.return_value = [b"image"]
        response.__enter__ = Mock(return_value=response)
        response.__exit__ = Mock(return_value=False)
        with patch("api.provider_source.requests.get", return_value=response) as fetch:
            self.assertEqual(source.get_subject_thumbnail(metadata, "large")["file"], ("Test", b"image"))
            self.assertFalse(fetch.call_args.kwargs["allow_redirects"])
            self.assertEqual(fetch.call_args.kwargs["proxies"]["https"], "http://localhost:7890")
            response.status_code = 302
            self.assertEqual(source.get_subject_thumbnail(metadata, "large"), {})
            response.status_code = 200
            response.headers = {"Content-Type": "text/html"}
            self.assertEqual(source.get_subject_thumbnail(metadata, "large"), {})
            fetch.reset_mock()
            for address in ("http://localhost/cover", "https://127.0.0.1/cover",
                            "https://anilist.co.evil/cover", "https://s4.anilist.co:8443/cover"):
                metadata["_provider_cover"] = address
                self.assertEqual(source.get_subject_thumbnail(metadata, "large"), {})
            fetch.assert_not_called()

    def test_bangumi_reference_tag_filter(self):
        tags = [{"name": "漫画", "count": 999}, {"name": "热血", "count": 500},
                {"name": "连载", "count": 500}, {"name": "搞笑", "count": 2},
                {"name": "陌生标签", "count": 999}]
        self.assertEqual(bangumi_tags(tags), ["热血", "搞笑"])
        self.assertEqual(bangumi_tags(tags, ["陌生标签"]), ["陌生标签", "热血", "搞笑"])
