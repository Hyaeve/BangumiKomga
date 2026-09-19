import unittest
from unittest.mock import Mock, patch

from tools.komga_path import title_path_context, series_title_path
from tools.title_recognition import recognize_title


class TitlePathTests(unittest.TestCase):
    def test_only_two_parent_folders_and_filename_are_kept(self):
        for path, expected in [
            ("/private/root/作品/卷册/01.cbz", "作品/卷册/01.cbz"),
            (r"C:\private\作品\卷册\01.epub", "作品/卷册/01.epub"),
            ("file:///private/%E4%BD%9C%E5%93%81/卷册/01.cbz", "作品/卷册/01.cbz"),
            ("01.cbz", "01.cbz"), ("", ""), (None, ""),
            ("https://server.invalid/api/books/1?secret=key", ""),
        ]:
            with self.subTest(path=path):
                self.assertEqual(title_path_context(path), expected)
        self.assertEqual(title_path_context("/private/分类/作品/", False), "分类/作品")

    def test_real_book_path_and_directory_fallback(self):
        client = Mock()
        client.iter_series_books.return_value = iter([{"id": "book"}])
        client.get_specific_book.return_value = {"url": "/private/作品/卷册/01.cbz"}
        self.assertEqual(series_title_path(client, {"id": "series"}), "作品/卷册/01.cbz")
        client.iter_series_books.side_effect = RuntimeError("unavailable")
        self.assertEqual(series_title_path(client, {"id": "series", "url": "/private/分类/作品"}), "分类/作品")
        client.get_specific_series.side_effect = RuntimeError("unavailable")
        self.assertEqual(series_title_path(client, {"id": "series"}), "")

    def test_ai_prompt_receives_media_type_and_path_context(self):
        response = Mock()
        response.json.return_value = {"choices": [{"message": {"content": "作品"}}]}
        with patch("tools.title_recognition.requests.post", return_value=response) as post:
            result = recognize_title("作品/卷册/01.epub", only_novel="book", from_path=True,
                                     settings={"OPENAI_BASE_URL": "http://fixture.invalid",
                                               "OPENAI_API_KEY": "fixture", "OPENAI_MODEL": "fixture"})
        self.assertEqual(result, "作品")
        messages = post.call_args.kwargs["json"]["messages"]
        self.assertIn("最近两层", messages[0]["content"])
        self.assertIn("非漫画书籍", messages[0]["content"])
        self.assertEqual(messages[1]["content"], "作品/卷册/01.epub")
