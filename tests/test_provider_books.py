import ast
from pathlib import Path
from unittest.mock import Mock
import unittest
from api.provider_source import ProviderDataSource


class ProviderBookPipelineTests(unittest.TestCase):
    def scope(self):
        tree = ast.parse((Path(__file__).parents[1] / "core/refresh_metadata.py").read_text(encoding="utf-8"))
        fn = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "refresh_book_metadata")
        source = ProviderDataSource(Mock(), [])
        source.associate_books = Mock(return_value={"a": "1", "b": "2"})
        source.get_book_metadata = Mock(side_effect=[RuntimeError("failed"), {"fields": {"title": "New"}}])
        komga = Mock()
        komga.get_series_books.return_value = {"content": [
            {"id": "a", "name": "Title Vol. 1", "metadata": {}},
            {"id": "b", "name": "Title Vol. 2", "metadata": {}},
            {"id": "c", "name": "Unmatched", "metadata": {}},
        ]}
        conn = Mock()
        conn.cursor.return_value.execute.return_value.fetchall.return_value = []
        scope = {
            "TASK_INCLUDE_VOLUMES": True, "komga": komga, "conn": conn, "bgm": source, "logger": Mock(),
            "_is_novel_series": lambda _: False, "_media_type_for_library": lambda _: "comic",
            "_record_path": lambda *_: "/books/title", "update_book_metadata": Mock(),
            "_book_needs_refresh": lambda *_: False,
        }
        exec(compile(ast.Module(body=[fn], type_ignores=[]), "<provider-books>", "exec"), scope)
        return scope

    def test_only_associated_books_are_updated_and_failure_isolated(self):
        scope = self.scope()
        scope["refresh_book_metadata"]("provider:COMIC_VINE:42", "series", False, [], "lib")
        update = scope["update_book_metadata"]
        update.assert_called_once()
        self.assertEqual(update.call_args.args[0], "b")
        self.assertEqual(update.call_args.kwargs["provider_book"]["fields"]["title"], "New")
        self.assertEqual(scope["bgm"].get_book_metadata.call_count, 2)

    def test_include_volumes_false_performs_no_queries(self):
        scope = self.scope()
        scope["TASK_INCLUDE_VOLUMES"] = False
        scope["refresh_book_metadata"]("provider:COMIC_VINE:42", "series", False)
        scope["komga"].get_series_books.assert_not_called()

    def test_series_authors_inherit_without_inventing_volume_summary(self):
        scope = self.scope()
        scope["bgm"].associate_books.return_value = {}
        scope["bgm"].metadata_cache["provider:ANILIST:42"] = {
            "_provider_shared": {"authors": [{"name": "Author", "role": "writer"}], "releaseDate": "2020-01-01"},
            "_provider_fields": {"summary": "Series summary"},
        }
        scope["refresh_book_metadata"]("provider:ANILIST:42", "series", False, [], "lib")
        self.assertEqual(scope["update_book_metadata"].call_count, 3)
        fields = scope["update_book_metadata"].call_args.kwargs["provider_book"]["fields"]
        self.assertEqual(set(fields), {"authors"})
        scope["bgm"].get_book_metadata.assert_not_called()
