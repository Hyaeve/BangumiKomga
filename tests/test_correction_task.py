import unittest
import io
import json
from copy import deepcopy
from unittest.mock import Mock, patch

from tools.correction_task import correct_library
from tools.title_rules import explicit_title
from tools.get_title import get_title_candidates
from services import task_worker


class CorrectionTests(unittest.TestCase):
    def setUp(self):
        self.series = {"id": "s", "name": "原系列", "metadata": {
            "title": "[萬古之王][作者]", "summary": "這是漫畫簡介", "publisher": "臺灣出版社",
            "titleLock": False, "summaryLock": True, "alternateTitles": [{"title": "副標題"}]}}
        self.book = {"id": "b", "name": "第一卷", "metadata": {
            "title": "《第一冊》", "authors": [{"name": "張學友", "role": "writer"}]}}
        self.client = Mock()
        self.updated, self.log = Mock(), Mock()

    def run_task(self, fields, operations, **kwargs):
        self.client.iter_library_series.return_value = iter([self.series])
        self.client.iter_series_books.return_value = iter([self.book])
        if not isinstance(self.client.get_specific_series.return_value, dict):
            self.client.get_specific_series.return_value = deepcopy(self.series)
        if not isinstance(self.client.get_specific_book.return_value, dict):
            self.client.get_specific_book.return_value = deepcopy(self.book)
        return correct_library(self.client, "library", {}, self.updated, self.log, fields, operations, True, **kwargs)

    def test_exact_title_rules(self):
        for value, expected in [
            ("作者《真正標題》[其他]", "真正標題"),
            ("[萬古之王][若鸿文化]", "萬古之王"),
            (" [唯一標題] ", "唯一標題"),
            ("標題[作者]", ""), ("[作者]標題", ""), ("普通名稱", ""),
            ("[作者]《書名優先》", "書名優先"),
            ("[Vchan] 你的女友", ""), ("[你的女友][Vchan]", "你的女友"),
        ]:
            with self.subTest(value=value):
                self.assertEqual(explicit_title(value), expected)

    def test_matching_candidates_do_not_treat_single_prefix_as_title(self):
        self.assertEqual(get_title_candidates("[Vchan] 你的女友"), [])
        self.assertEqual(get_title_candidates("[你的女友][Vchan]"), ["你的女友"])
        self.assertEqual(get_title_candidates("[你的女友]"), ["你的女友"])

    def test_worker_forwards_saved_filter_terms(self):
        request = {"function": "metadata_correction", "task": {"fields": ["title"],
                   "operations": ["extract_title"], "card_ids": ["s::l"], "filter_terms": "[Vchan]\n广告"}}
        with patch("services.task_worker.sys.stdin", io.StringIO(json.dumps(request))), \
             patch("web_backend._translate_task_libraries") as run:
            task_worker.main()
        self.assertEqual(run.call_args.kwargs["filter_terms"], "[Vchan]\n广告")

    def test_prefix_bracket_enters_ai_stage(self):
        self.series["metadata"]["title"] = "[Vchan] 你的女友"
        with patch("tools.correction_task.recognize_title", return_value="你的女友") as ai:
            self.run_task(["title"], ["extract_title"], include_volumes=False)
        ai.assert_called_once_with("[Vchan] 你的女友", only_novel=True, settings={})
        self.client.update_series_metadata.assert_called_once_with("s", {"title": "你的女友"})

    def test_filter_precedes_extraction_and_is_literal(self):
        self.series["metadata"]["title"] = "[广告][真正标题][作者]"
        with patch("tools.correction_task.recognize_title") as ai:
            self.run_task(["title"], ["extract_title"], filter_terms="[广告]\n.*", include_volumes=False)
        ai.assert_not_called()
        self.client.update_series_metadata.assert_called_once_with("s", {"title": "真正标题"})

    def test_failed_extraction_still_removes_terms_without_locking(self):
        self.series["metadata"]["title"] = "[Vchan] 你的女友 [广告]"
        with patch("tools.correction_task.recognize_title", return_value="") as ai:
            result = self.run_task(["title"], ["extract_title"], filter_terms="[Vchan]\n[广告]",
                                   lock_completed=True, include_volumes=False)
        ai.assert_called_once_with("你的女友", only_novel=True, settings={})
        self.client.update_series_metadata.assert_called_once_with("s", {"title": "你的女友"})
        self.assertEqual(result["failed"], 1)

    def test_filter_cannot_be_reintroduced_by_ai(self):
        self.series["metadata"]["title"] = "你的女友[广告]"
        with patch("tools.correction_task.recognize_title", return_value="正式标题[广告]"):
            self.run_task(["title"], ["extract_title"], filter_terms="[广告]", include_volumes=False)
        self.client.update_series_metadata.assert_called_once_with("s", {"title": "正式标题"})

    def test_filter_scope_locks_and_empty_safety(self):
        for operations, fields, locked_title, include, title, terms, expected in [
            (["simplify"], ["title"], False, False, "广告標題", "广告", {"title": "广告标题"}),
            (["extract_title"], ["title"], True, False, "广告标题", "广告", None),
            (["extract_title"], ["title"], True, True, "广告标题", "广告", {"title": "标题"}),
            (["extract_title"], ["title"], False, False, "广告", "广告", None),
            (["simplify", "extract_title"], ["summary"], False, False, "广告标题", "广告", None),
        ]:
            with self.subTest(operations=operations, fields=fields, locked_title=locked_title, include=include, title=title):
                self.setUp()
                self.series["metadata"].update(title=title, titleLock=locked_title)
                with patch("tools.correction_task.recognize_title", return_value=""):
                    self.run_task(fields, operations, filter_terms=terms, include_locked=include, include_volumes=False)
                if expected:
                    self.client.update_series_metadata.assert_called_once_with("s", expected)
                else:
                    self.client.update_series_metadata.assert_not_called()

    def test_scope_locks_roles_and_subtitles(self):
        before = deepcopy(self.series)
        with patch("tools.correction_task.recognize_title") as ai:
            result = self.run_task(["title", "summary", "authors"], ["extract_title", "simplify"])
        ai.assert_not_called()
        self.assertEqual(result["updated"], 2)
        self.client.update_series_metadata.assert_called_once_with("s", {"title": "万古之王"})
        self.client.update_book_metadata.assert_called_once_with("b", {
            "title": "第一册", "authors": [{"name": "张学友", "role": "writer"}]})
        self.assertEqual(self.series, before)

    def test_include_locked_retains_original_lock(self):
        self.run_task(["summary"], ["simplify", "include_locked"])
        self.client.update_series_metadata.assert_called_once_with("s", {"summary": "这是漫画简介"})
        self.assertNotIn("summaryLock", self.client.update_series_metadata.call_args.args[1])

    def test_ai_fallback_respects_novel_and_failed_title_unchanged(self):
        self.series["metadata"]["title"] = "未識別原始名稱"
        with patch("tools.correction_task.recognize_title", return_value="") as ai:
            self.run_task(["title"], ["extract_title", "simplify"])
        ai.assert_called_once_with("未識別原始名稱", only_novel=True, settings={})
        self.client.update_series_metadata.assert_not_called()

    def test_ai_title_success(self):
        self.series["metadata"]["title"] = "原始檔案名稱"
        with patch("tools.correction_task.recognize_title", return_value="正式名稱"):
            self.run_task(["title"], ["extract_title"])
        self.client.update_series_metadata.assert_called_once_with("s", {"title": "正式名稱"})

    def test_concurrent_edit_and_new_lock_respected(self):
        self.client.get_specific_series.return_value = deepcopy(self.series)
        self.client.get_specific_series.return_value["metadata"]["titleLock"] = True
        self.run_task(["title"], ["extract_title"])
        self.client.update_series_metadata.assert_not_called()

    def test_invalid_operation_combinations_rejected(self):
        for fields, ops in [(["summary"], ["extract_title"]), (["title"], ["include_locked"]),
                            (["alternateTitles"], ["simplify"]), ([], ["simplify"])]:
            with self.assertRaises(ValueError):
                self.run_task(fields, ops)


if __name__ == "__main__":
    unittest.main()
