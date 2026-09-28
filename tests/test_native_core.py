import json
import os
from pathlib import Path
import subprocess
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from bangumi_archive.sqlite_store import ArchiveStore, normalize
from tools.native_core import archive_request, executable, ROOT


class NativeCoreBoundaryTests(unittest.TestCase):
    def test_explicit_disable_and_missing_binary(self):
        with patch.dict(os.environ, {"BANGUMIKOMGA_CORE": "off"}):
            self.assertIsNone(archive_request("search", ".", query="test"))
        with patch.dict(os.environ, {"BANGUMIKOMGA_CORE": str(ROOT / "missing-core.exe")}):
            with self.assertRaises(RuntimeError):
                executable()

    def test_errors_are_not_silently_returned_as_no_match(self):
        with patch("tools.native_core.executable", return_value=Path("native.exe")):
            for response in [
                {"protocol": 1, "error": "bad index"},
                {"protocol": 2, "data": []},
                {"protocol": 1, "data": {}},
            ]:
                completed = subprocess.CompletedProcess([], 0, json.dumps(response), "")
                with patch("tools.native_core.subprocess.run", return_value=completed):
                    with self.assertRaises(RuntimeError):
                        archive_request("search", ".", query="test")
            with patch("tools.native_core.subprocess.run", side_effect=subprocess.TimeoutExpired("native", 25)):
                with self.assertRaises(RuntimeError):
                    archive_request("search", ".", query="test")


class NativeCoreIntegrationTests(unittest.TestCase):
    def test_provider_book_association_and_detail(self):
        from api.provider_source import ProviderDataSource
        from unittest.mock import Mock
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "books.sqlite"
            db = sqlite3.connect(path)
            db.executescript("""
                CREATE TABLE products(id TEXT,series_id TEXT,display_title TEXT,display_order REAL,title TEXT,description TEXT,on_sale_at TEXT);
                CREATE TABLE product_external_ids(product_id TEXT,type INTEGER,external_id TEXT);
                INSERT INTO products VALUES ('b1','s1','Title Vol. 1',1.0,'First','<p>Book summary</p>','2020-01-02');
                INSERT INTO products VALUES ('b2','s1','Title Vol. 2',2.0,'Second','Summary','2021-01-02');
                INSERT INTO product_external_ids VALUES ('b1',3,'9780000000001');
            """)
            db.close()
            source = ProviderDataSource(Mock(), [{"name": "BOOK_WALKER", "enabled": True, "database": str(path),
                                                "book_fields": {"title": False}}])
            result = source.associate_books("provider:BOOK_WALKER:s1", [
                {"id": "local1", "name": "Title Vol. 1"}, {"id": "chapter", "name": "Title c1"}
            ], "comic")
            self.assertEqual(result, {"local1": "b1"})
            detail = source.get_book_metadata("provider:BOOK_WALKER:s1", "b1")
            self.assertNotIn("title", detail["fields"])
            self.assertEqual(detail["fields"]["summary"], "Book summary")
            self.assertEqual(detail["fields"]["number"], "1")
            with self.assertRaises(RuntimeError):
                source.get_book_metadata("provider:BOOK_WALKER:s2", "b1")

    def test_native_provider_match_get_and_field_filter(self):
        from api.provider_source import ProviderDataSource
        from unittest.mock import Mock
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "provider.sqlite"
            db = sqlite3.connect(path)
            db.executescript("""
                CREATE TABLE series(id INTEGER,type TEXT,titles TEXT,description TEXT,status TEXT);
                INSERT INTO series VALUES (1,'manga','[{"title":"Test","language":"en"}]','<p>Summary</p>','completed');
                CREATE VIRTUAL TABLE titles_fts USING fts5(id UNINDEXED,title,type UNINDEXED);
                INSERT INTO titles_fts VALUES (1,'Test','manga');
            """)
            db.close()
            source = ProviderDataSource(Mock(), [{
                "name": "MANGA_BAKA", "enabled": True, "priority": 10,
                "database": str(path), "fields": {"title": False},
            }])
            item = source.search_other_providers(["Test"], "comic")
            self.assertEqual(item["id"], "provider:MANGA_BAKA:1")
            self.assertEqual(item["name"], "Test")
            self.assertNotIn("title", item["_provider_fields"])
            self.assertEqual(item["_provider_fields"]["summary"], "Summary")
            self.assertEqual(source.get_subject_metadata(item["id"]), {
                key: value for key, value in item.items() if key != "_match_query"
            })
            self.assertIsNone(source.search_other_providers(["Test"], "book"))

    @classmethod
    def setUpClass(cls):
        cls.binary = executable()
        if not cls.binary:
            raise unittest.SkipTest("build Go core before running cross-language tests")

    def test_python_index_is_readable_by_go(self):
        with tempfile.TemporaryDirectory(prefix="离线库-") as folder:
            source = Path(folder) / "subject.jsonlines"
            subjects = [
                {"id": 1, "type": 1, "name": "萬古之王", "name_cn": "万古之王",
                 "summary": "完整简介", "platform": 1001, "series": True,
                 "infobox": "{{Infobox animanga/Manga\n|别名=Ancient King\n}}"},
                {"id": 2, "type": 1, "name": "万古之王 第一卷", "series": False},
            ]
            source.write_text("\n".join(json.dumps(item, ensure_ascii=False) for item in subjects), encoding="utf-8")
            (Path(folder) / "subject-relations.jsonlines").write_text(
                '{"subject_id":1,"related_subject_id":2,"relation_type":1003}', encoding="utf-8")
            store = ArchiveStore(folder)
            store.build()
            with patch.dict(os.environ, {"BANGUMIKOMGA_CORE": str(self.binary)}):
                for query in ["萬古", "万古之王", "Ancient", "%", '"']:
                    query = normalize(query)
                    native = archive_request("search", folder, query=query)
                    expected = store.search(query)
                    self.assertEqual(sorted(native, key=lambda x: x["id"]),
                                     sorted(expected, key=lambda x: x["id"]))
                for item_id in [1, 2, 999]:
                    self.assertEqual(archive_request("get", folder, id=item_id), store.get(item_id))
                    self.assertEqual(archive_request("relations", folder, id=item_id), store.relations(item_id))
                from api.bangumi_api import BangumiArchiveDataSource
                data_source = BangumiArchiveDataSource(folder)
                with patch.object(data_source.store, "get", side_effect=AssertionError("Python fallback used")):
                    self.assertEqual(data_source.get_subject_metadata(1)["summary"], "完整简介")

    def test_missing_database_is_not_created(self):
        with tempfile.TemporaryDirectory() as folder:
            with patch.dict(os.environ, {"BANGUMIKOMGA_CORE": str(self.binary)}):
                self.assertEqual(archive_request("search", folder, query="test"), [])
            self.assertEqual(list(Path(folder).iterdir()), [])
