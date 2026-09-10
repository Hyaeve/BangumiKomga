import unittest
from unittest.mock import Mock, patch

from tools.translation_task import translate_library


class TranslationTaskTests(unittest.TestCase):
    def setUp(self):
        self.settings = {"OPENAI_BASE_URL": "http://fixture", "OPENAI_API_KEY": "test", "OPENAI_MODEL": "test"}
        self.komga = Mock()
        self.series = {"id": "s1", "name": "书籍", "url": "/books/书籍", "metadata": {"summary": "English summary", "summaryLock": False}}
        self.book = {"id": "b1", "name": "第一卷", "metadata": {"summary": "已经是中文简介", "summaryLock": False}}
        self.komga.iter_library_series.return_value = iter([self.series])
        self.komga.iter_series_books.return_value = iter([self.book])
        self.komga.get_specific_series.return_value = self.series
        self.komga.get_specific_book.return_value = self.book
        self.updated = Mock()
        self.log = Mock()

    def test_translates_existing_series_and_locks_chinese_volume(self):
        with patch("tools.translation_task.translate_summary_to_zh", return_value="翻译后的中文简介") as translate:
            counts = translate_library(self.komga, "library", self.settings, self.updated, self.log)
        self.assertEqual(counts, {"updated": 2, "skipped": 0, "failed": 0})
        translate.assert_called_once_with("English summary", True, settings=self.settings)
        self.komga.update_series_metadata.assert_called_once_with("s1", {"summaryLock": True, "summary": "翻译后的中文简介"})
        self.komga.update_book_metadata.assert_called_once_with("b1", {"summaryLock": True})

    def test_locked_summaries_are_never_sent_to_ai(self):
        self.series["metadata"]["summaryLock"] = True
        self.book["metadata"]["summaryLock"] = True
        with patch("tools.translation_task.translate_summary_to_zh") as translate:
            counts = translate_library(self.komga, "library", self.settings, self.updated, self.log)
        translate.assert_not_called()
        self.assertEqual(counts["skipped"], 2)
        self.updated.assert_not_called()

    def test_failure_keeps_source_unlocked_and_logs_error(self):
        with patch("tools.translation_task.translate_summary_to_zh", return_value="English summary"):
            counts = translate_library(self.komga, "library", self.settings, self.updated, self.log)
        self.assertEqual(counts["failed"], 1)
        self.komga.update_series_metadata.assert_not_called()

    def test_lock_changed_during_translation_is_respected(self):
        self.komga.get_specific_series.return_value = {"metadata": {"summaryLock": True}}
        with patch("tools.translation_task.translate_summary_to_zh", return_value="中文简介"):
            counts = translate_library(self.komga, "library", self.settings, self.updated, self.log)
        self.assertEqual(counts["skipped"], 1)
        self.komga.update_series_metadata.assert_not_called()

    def test_missing_ai_settings_is_actionable_error(self):
        with self.assertRaisesRegex(ValueError, "AI"):
            translate_library(self.komga, "library", {}, self.updated, self.log)

    def test_selected_fields_only_and_author_roles_preserved(self):
        self.series["metadata"].update({"title": "A Book", "titleLock": False,
                                        "publisher": "Publisher", "publisherLock": True,
                                        "alternateTitles": [{"title": "Subtitle"}]})
        self.book["metadata"]["authors"] = [{"name": "John", "role": "writer"}, {"name": "Mary", "role": "penciller"}]
        with patch("tools.translation_task.translate_summary_to_zh", return_value="中文名称"):
            translate_library(self.komga, "library", self.settings, self.updated, self.log,
                              fields=["title", "publisher", "authors"])
        self.komga.update_series_metadata.assert_called_once_with("s1", {"title": "中文名称", "titleLock": True})
        self.komga.update_book_metadata.assert_called_once_with("b1", {
            "authors": [{"name": "中文名称", "role": "writer"}, {"name": "中文名称", "role": "penciller"}],
            "authorsLock": True})
        self.assertEqual(self.updated.call_args_list[0].args[-1], ["title"])

    def test_one_field_failure_does_not_block_other_fields(self):
        self.series["metadata"]["title"] = "English title"
        with patch("tools.translation_task.translate_summary_to_zh", side_effect=lambda value, *args, **kwargs: value if kwargs.get("field") == "title" else "中文简介"):
            result = translate_library(self.komga, "library", self.settings, self.updated, self.log,
                                       fields=["title", "summary"])
        self.assertEqual(result["failed"], 1)
        self.komga.update_series_metadata.assert_called_once_with("s1", {"summary": "中文简介", "summaryLock": True})

    def test_concurrent_field_edit_preserved_while_other_field_updates(self):
        self.series["metadata"]["title"] = "Old"
        self.komga.get_specific_series.return_value = {"metadata": {**self.series["metadata"], "title": "User edit"}}
        with patch("tools.translation_task.translate_summary_to_zh", return_value="中文内容"):
            translate_library(self.komga, "library", self.settings, self.updated, self.log, fields=["title", "summary"])
        self.komga.update_series_metadata.assert_called_once_with("s1", {"summary": "中文内容", "summaryLock": True})

    def test_author_failure_keeps_entire_authors_field_unlocked(self):
        self.book["metadata"]["authors"] = [{"name": "John", "role": "writer"}, {"name": "Mary", "role": "penciller"}]
        with patch("tools.translation_task.translate_summary_to_zh", side_effect=["约翰", "Mary"]):
            translate_library(self.komga, "library", self.settings, self.updated, self.log, fields=["authors"])
        self.komga.update_book_metadata.assert_not_called()
        self.assertEqual(self.book["metadata"]["authors"][0]["name"], "John")

    def test_empty_or_unsupported_selection_rejected(self):
        for fields in ([], ["alternateTitles"], ["titleSort"]):
            with self.assertRaises(ValueError):
                translate_library(self.komga, "library", self.settings, self.updated, self.log, fields=fields)


if __name__ == "__main__":
    unittest.main()
