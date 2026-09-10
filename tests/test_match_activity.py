"""Exercise match control flow without importing live scraper configuration."""
import ast
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock


class MatchActivityTests(unittest.TestCase):
    def run_match(self, cached=False, needs_refresh=False, found=True, valid=True, write=True, available=True):
        tree = ast.parse((Path(__file__).parents[1] / "core/refresh_metadata.py").read_text(encoding="utf-8"))
        functions = [node for node in tree.body if isinstance(node, ast.FunctionDef)
                     and node.name in {"refresh_metadata", "_log_match_result"}]
        cursor = Mock()
        cursor.execute.return_value.fetchall.return_value = [("s", 42, 1)] if cached else []
        cursor.execute.return_value.fetchone.return_value = [42]
        metadata = SimpleNamespace(**{key: "" for key in
            ("status", "summary", "publisher", "genres", "tags", "title", "alternateTitles",
             "ageRating", "links", "totalBookCount", "language", "titleSort")})
        metadata.isvalid, metadata.title = valid, "匹配标题"
        bgm = Mock()
        bgm.search_subjects.return_value = [{"id": 42, "platform": "漫画"}] if found else []
        bgm.get_subject_metadata.return_value = {"platform": "漫画"} if available else None
        komga = Mock()
        komga.update_series_metadata.return_value = write
        scope = dict(cursor=cursor, conn=Mock(), logger=Mock(), bgm=bgm, komga=komga,
                     process_metadata=Mock(), RECHECK_FAILED_SERIES=True, FUZZ_SCORE_THRESHOLD=80,
                     TASK_AI_COMPLETION=False, TASK_COMPLETION_FIELDS=None,
                     USE_BANGUMI_THUMBNAIL=False, CREATE_FAILED_COLLECTION=False,
                     SubjectPlatform=SimpleNamespace(parse=lambda _: "comic", Comic="comic"),
                     get_title_candidates=lambda _: ["书名"], recognize_title=Mock(),
                     record_activity_log=Mock(), record_scrape_event=Mock(),
                     record_series_status=Mock(return_value=(1, "")),
                     refresh_book_metadata=Mock(), send_notification=Mock(),
                     strftime=Mock(return_value=""), localtime=Mock(),
                     _media_type_for_library=lambda _: "comic", _required_fields_for_series=lambda _: [],
                     _series_needs_refresh=lambda *_: needs_refresh,
                     _ai_recognition_enabled_for_library=lambda _: False,
                     _overwrite_fields_for_library=lambda _: ["title"],
                     _apply_summary_translation_policy=Mock(), _translation_enabled_for_library=lambda _: False,
                     _metadata_write_payload=lambda *_: {"title": "匹配标题"},
                     _is_scrape_card_library=lambda _: True, _library_name=lambda _: "漫画库",
                     _record_path=lambda *_: "/books/book", _record_server_id=lambda _: "server")
        scope["process_metadata"].set_komga_series_metadata.return_value = metadata
        exec(compile(ast.Module(body=functions, type_ignores=[]), "<match-test>", "exec"), scope)
        scope["refresh_metadata"]([{"id": "s", "name": "原书名", "libraryId": "lib",
                                    "is_novel": False, "metadata": {"links": []}}])
        return scope

    def test_cached_match_logs_skip_without_search(self):
        for needs_refresh in (False, True):
            scope = self.run_match(cached=True, needs_refresh=needs_refresh)
            scope["bgm"].search_subjects.assert_not_called()
            call = scope["record_activity_log"].call_args
            self.assertEqual(call.args[1], "跳过匹配")
            self.assertIn("原书名", call.args[2])

    def test_new_match_logs_success(self):
        scope = self.run_match()
        scope["record_activity_log"].assert_called_once()
        call = scope["record_activity_log"].call_args
        self.assertEqual(call.args[1], "成功匹配")
        self.assertIn("匹配标题", call.args[2])
        self.assertEqual(call.kwargs["level"], "info")

    def test_failure_branches_log_failure(self):
        for options in ({"found": False}, {"valid": False}, {"write": False},
                        {"cached": True, "needs_refresh": True, "available": False}):
            scope = self.run_match(**options)
            call = scope["record_activity_log"].call_args
            self.assertEqual(call.args[1], "匹配失败")
            self.assertEqual(call.kwargs["level"], "error")


if __name__ == "__main__":
    unittest.main()
