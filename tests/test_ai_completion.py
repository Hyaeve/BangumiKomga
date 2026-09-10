import ast
import json
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import web_backend
from tools.ai_completion import search_metadata, complete_unmatched


class AICompletionTests(unittest.TestCase):
    settings = {"OPENAI_BASE_URL": "http://fixture/v1/chat/completions",
                "OPENAI_API_KEY": "test", "OPENAI_MODEL": "test"}

    def response(self, data, searched=True, cited=True):
        output = [{"type": "web_search_call", "status": "completed"}] if searched else []
        output.append({"type": "message", "content": [{
            "type": "output_text", "text": json.dumps(data),
            "annotations": [{"type": "url_citation", "url": "https://publisher.example/book"}] if cited else []}]})
        response = Mock()
        response.json.return_value = {"output": output}
        return response

    def test_requires_real_search_and_citation_for_each_selected_field(self):
        data = {
            "summary": {"value": "简介", "source_urls": ["https://publisher.example/book"]},
            "publisher": {"value": "无依据出版商", "source_urls": ["https://invented.example"]},
            "title": {"value": "未选中标题", "source_urls": ["https://publisher.example/book"]},
        }
        with patch("tools.ai_completion.requests.post", return_value=self.response(data)) as post:
            result = search_metadata("书", ["summary", "publisher"], self.settings)
        self.assertEqual(result, {"summary": "简介"})
        self.assertEqual(post.call_args.args[0], "http://fixture/v1/responses")
        self.assertEqual(post.call_args.kwargs["json"]["tools"], [{"type": "web_search"}])
        for searched, cited in [(False, True), (True, False)]:
            with patch("tools.ai_completion.requests.post", return_value=self.response(data, searched, cited)):
                self.assertEqual(search_metadata("书", ["summary"], self.settings), {})

    def test_missing_ai_and_invalid_value_do_not_write(self):
        with patch("tools.ai_completion.requests.post") as post:
            self.assertEqual(search_metadata("书", ["summary"], {}), {})
        post.assert_not_called()
        data = {"authors": {"value": [{"name": "张三", "role": "invented"}],
                            "source_urls": ["https://publisher.example/book"]}}
        with patch("tools.ai_completion.requests.post", return_value=self.response(data)):
            self.assertEqual(search_metadata("书", ["authors"], self.settings), {})

    def test_fill_only_selected_missing_unlocked_and_concurrent_guard(self):
        client = Mock()
        series = {"id": "s", "name": "书", "metadata": {"title": "现有", "summary": "", "publisher": "", "publisherLock": True}}
        book = {"id": "b", "name": "卷一", "metadata": {"summary": ""}}
        client.iter_series_books.return_value = iter([book])
        client.get_specific_series.return_value = {**series, "url": "/data/book"}
        client.get_specific_book.return_value = {**book, "metadata": {"summary": "期间用户填写"}}
        update = Mock()
        with patch("tools.ai_completion.search_metadata", return_value={"summary": "来源简介"}) as search:
            complete_unmatched(client, series, ["title", "summary", "publisher"], self.settings, False, update, Mock())
        self.assertEqual(search.call_args_list[0].args[1], ["summary"])
        client.update_series_metadata.assert_called_once_with("s", {"summary": "来源简介"})
        client.update_book_metadata.assert_not_called()
        self.assertEqual(update.call_args.args[0]["url"], "/data/book")

    def test_completion_dispatch_scopes_server_and_field_selection(self):
        context = {"a::lib": {"server_id": "a", "library_id": "lib"},
                   "b::lib": {"server_id": "b", "library_id": "lib"}}
        with patch.object(web_backend, "_configured_library_context", return_value=context), \
             patch.object(web_backend, "_run_managed") as run:
            web_backend._complete_task_libraries(["a::lib", "b::lib"], {"fields": ["summary"], "ai_completion": True})
        self.assertEqual(run.call_count, 2)
        values = [call.args[1] for call in run.call_args_list]
        self.assertEqual([value["server_id"] for value in values], ["a", "b"])
        self.assertTrue(all(value["fields"] == ["summary"] and value["ai_completion"] for value in values))

    def test_core_completion_filter_and_fallback_placement(self):
        tree = ast.parse((Path(__file__).parents[1] / "core/refresh_metadata.py").read_text(encoding="utf-8"))
        names = {"_metadata_write_payload", "_is_metadata_empty", "_metadata_field_locked"}
        functions = [node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name in names]
        scope = {"TASK_COMPLETION_FIELDS": {"summary", "title"}}
        exec(compile(ast.Module(body=functions, type_ignores=[]), "<completion-filter>", "exec"), scope)
        result = scope["_metadata_write_payload"](
            {"title": "", "titleLock": True, "summary": ""},
            {"title": "标题", "summary": "简介", "publisher": "非选中"}, ["title", "publisher"])
        self.assertEqual(result, {"summary": "简介"})
        # The fallback is inside the final unmatched branch, before failure recording.
        refresh = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "refresh_metadata")
        branches = [node for node in ast.walk(refresh) if isinstance(node, ast.If) and ast.unparse(node.test) == "subject_id is None"]
        self.assertTrue(any("_complete_unmatched_with_ai" in ast.unparse(node) and "no subject in bangumi" in ast.unparse(node) for node in branches))


if __name__ == "__main__":
    unittest.main()
