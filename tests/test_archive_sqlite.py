import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock

from bangumi_archive.sqlite_store import ArchiveStore
from api.bangumi_api import BangumiArchiveDataSource, OfflineFirstDataSource
from services.event_batcher import EventBatcher


class ArchiveSQLiteTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.rows = [
            {"id": 1, "type": 1, "name": "Original Name", "name_cn": "测试漫画", "platform": 1001, "series": True,
             "summary": "离线简介", "infobox": "{{Infobox animanga/Manga\n|别名= {[别称|测试别名]}\n|出版社=某出版社\n}}"},
            {"id": 2, "type": 1, "name": "Volume 1", "platform": 1001, "series": False, "summary": "分卷简介"},
            {"id": 3, "type": 2, "name": "不是书籍", "series": True},
        ]
        self.write_subjects()
        (self.root / "subject-relations.jsonlines").write_text(
            json.dumps({"subject_id": 1, "related_subject_id": 2, "relation_type": 1})+"\n", encoding="utf-8")
        self.store = ArchiveStore(self.root)

    def write_subjects(self):
        (self.root / "subject.jsonlines").write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in self.rows)+"\n", encoding="utf-8")

    def test_build_aliases_relations_and_short_queries(self):
        self.assertFalse(self.store.ready())
        self.assertTrue(self.store.build())
        self.assertFalse(self.store.build())
        self.assertEqual(self.store.get(1)["summary"], "离线简介")
        self.assertEqual(self.store.get(3), {})
        self.assertEqual(self.store.search("测试别名")[0]["id"], 1)
        self.assertEqual(self.store.search("漫画")[0]["id"], 1)
        self.assertEqual(self.store.relations(1)[0]["id"], 2)
        self.assertEqual(self.store.search('" OR *'), [])
        self.assertEqual(self.store.search("%"), [])
        source = BangumiArchiveDataSource(str(self.root))
        self.assertEqual(source.search_subjects("测试漫画")[0]["id"], 1)
        self.assertEqual(source.get_subject_metadata(1)["summary"], "离线简介")

    def test_atomic_rebuild_and_failed_build_preserves_old_index(self):
        self.store.build()
        self.rows[0]["summary"] = "新简介"
        self.write_subjects()
        self.assertTrue(self.store.build())
        self.assertEqual(self.store.get(1)["summary"], "新简介")
        (self.root / "subject.jsonlines").write_text("{invalid", encoding="utf-8")
        with self.assertRaises(ValueError):
            self.store.build()
        self.assertEqual(self.store.get(1)["summary"], "新简介")
        self.assertFalse(list(self.root.glob("bangumi-build-*")))

    def test_only_search_can_fallback_never_online_metadata(self):
        self.store.build()
        online = Mock()
        source = OfflineFirstDataSource(BangumiArchiveDataSource(str(self.root)), online)
        self.assertEqual(source.search_subjects("测试漫画")[0]["id"], 1)
        online.search_subjects.assert_not_called()
        online.search_subjects.return_value = [{"id": 99}]
        self.assertEqual(source.search_subjects("缺失作品"), [])
        online.search_subjects.assert_called_once()
        self.assertEqual(source.get_subject_metadata(99), {})
        self.assertEqual(source.get_related_subjects(99), [])
        self.assertEqual(source.get_subject_thumbnail({"id":1},"large"), {})
        online.get_subject_metadata.assert_not_called()
        online.get_related_subjects.assert_not_called()
        online.get_subject_thumbnail.assert_not_called()

    def test_online_hit_is_rehydrated_from_archive_not_online_payload(self):
        self.store.build()
        offline = BangumiArchiveDataSource(str(self.root))
        offline.search_subjects = Mock(return_value=[])
        online = Mock()
        online.search_subjects.return_value = [{"id":1, "summary":"不能使用这个简介"}]
        source = OfflineFirstDataSource(offline, online)
        result = source.search_subjects("测试漫画")
        self.assertEqual(result[0]["summary"], "离线简介")
        online.get_subject_metadata.assert_not_called()


class EventBatcherTests(unittest.TestCase):
    def test_coalesces_and_keeps_late_new_books(self):
        dispatched = []
        batch = EventBatcher(dispatched.append, quiet_seconds=1000, max_wait=3000)
        self.addCleanup(batch.close)
        event = {"event_type":"BookAdded","event_data":{"seriesId":"s1","libraryId":"lib","id":"b1"}}
        batch.add(event, now=0)
        batch.add({**event,"event_data":{**event["event_data"],"id":"b2"}}, now=1)
        batch.flush(force=True)
        self.assertEqual(len(dispatched),1)
        self.assertEqual(dispatched[0]["event_data"]["id"],"b2")
        batch.add(event, now=2)
        batch.flush(force=True)
        self.assertEqual(len(dispatched),2)

    def test_series_added_id_and_scan_completion(self):
        dispatched = []
        batch = EventBatcher(dispatched.append, quiet_seconds=1000)
        self.addCleanup(batch.close)
        event = {"event_type":"SeriesAdded","event_data":{"id":"s1","libraryId":"lib"}}
        batch.add(event, now=0)
        batch.add({**event,"event_type":"SeriesChanged"}, now=1)
        batch.flush(now=2)
        self.assertEqual(dispatched,[])
        batch.flush(force=True)
        self.assertEqual(dispatched[0]["event_type"],"SeriesAdded")
        batch.close()
        batch.add(event)
        batch.flush(force=True)
        self.assertEqual(len(dispatched),1)
