import json
import sqlite3
from contextlib import closing
from unittest.mock import patch
from tests.test_workbench import WorkbenchTests
from tools import workbench_match
import web_backend as backend


class WorkbenchMatchingTests(WorkbenchTests):
    def setUp(self):
        super().setUp()
        workbench_match.PREVIEWS.clear()
        self.client.iter_series_books.return_value = []

    def test_match_options_default_on_and_can_disable_both(self):
        hit = {"provider": "MANGADEX", "id": "md-1", "media_type": "comic",
               "titles": [{"name": "New"}], "fields": {"publisher": "Publisher"}}
        with patch.object(workbench_match, "core_request", return_value=hit):
            preview = workbench_match.preview(backend, {"card": "server::lib", "id": "one",
                                                       "provider": "MANGADEX", "subject_id": "md-1"})
        entry = workbench_match.PREVIEWS[preview["token"]]
        self.assertTrue(entry["include_cover"])
        self.assertTrue(entry["include_volumes"])
        entry["poster"] = {"after": {"id": "not-read"}, "before": None}
        with patch("tools.workbench_match_books.apply_books") as volumes, \
             patch("tools.workbench.save_poster") as poster:
            workbench_match.apply(backend, {"token": preview["token"], "include_volumes": False, "include_cover": False})
            volumes.assert_not_called()
            poster.assert_not_called()

    def test_volume_scope_cover_disabled_and_snapshot(self):
        from copy import deepcopy
        from tools.workbench_match_books import apply_books
        book = {"id": "v1", "seriesId": "one", "libraryId": "lib", "name": "第一卷",
                "metadata": {"title": "原卷名", "titleLock": True, "summary": ""}}
        self.client.iter_series_books.return_value = [book, {**book, "id": "foreign", "seriesId": "other"}]
        self.client.get_specific_book.side_effect = lambda _: deepcopy(book)
        def update(identity, fields):
            self.assertEqual(identity, "v1")
            book["metadata"].update(fields)
            return True
        self.client.update_book_metadata.side_effect = update
        entry = {"card": "server::lib", "id": "one", "provider": "MANGADEX", "subject_id": "MANGADEX:md-1"}
        with patch("tools.workbench_match_books.ProviderDataSource") as source:
            source.return_value.associate_books.return_value = {"v1": "remote1", "foreign": "remote2"}
            source.return_value.get_book_metadata.return_value = {"fields": {"title": "不能覆盖", "summary": "新简介"}, "cover": "https://example.com/image.jpg"}
            count, warnings = apply_books(backend, entry, False)
            source.return_value.get_subject_thumbnail.assert_not_called()
        self.assertEqual((count, warnings), (1, []))
        self.assertEqual(book["metadata"]["title"], "原卷名")
        self.assertTrue(book["metadata"]["titleLock"])
        with closing(sqlite3.connect(self.root / "recordsRefreshed.db")) as conn:
            row = conn.execute("SELECT event_kind,metadata_before,metadata_after,metadata_provider FROM scrape_records").fetchone()
        self.assertEqual(row[0], "volume")
        self.assertEqual(json.loads(row[1])["summary"], "")
        self.assertEqual(json.loads(row[2])["summary"], "新简介")
        self.assertEqual(row[3], "MANGADEX")

    def test_offline_volume_association_does_not_guess_unmatched_books(self):
        from copy import deepcopy
        from tools.workbench_match_books import apply_books
        book = {"id": "v1", "seriesId": "one", "libraryId": "lib", "name": "作品 vol.1",
                "metadata": {"title": "旧标题", "summary": ""}}
        self.client.iter_series_books.return_value = [book, {**book, "id": "v2", "name": "未编号文件"}]
        self.client.get_specific_book.side_effect = lambda _: deepcopy(book)
        self.client.update_book_metadata.side_effect = lambda _, values: book["metadata"].update(values) or True
        entry = {"card": "server::lib", "id": "one", "provider": "BANGUMI_OFFLINE", "subject_id": "10"}
        with patch("tools.workbench_match_books.BangumiArchiveDataSource") as source:
            source.return_value.get_related_subjects.return_value = [
                {"id": 11, "name": "作品 vol.1", "name_cn": "", "relation": "单行本"}]
            source.return_value.get_subject_metadata.return_value = {"id": 11, "name": "作品 (1)", "summary": "分卷简介", "infobox": []}
            count, warnings = apply_books(backend, entry, True)
            source.return_value.get_subject_metadata.assert_called_once_with(11)
        self.assertEqual((count, warnings), (1, []))
        self.client.update_book_thumbnail.assert_not_called()
        self.assertEqual(book["metadata"]["summary"], "分卷简介")

    def test_offline_candidates_and_preview_never_use_online_api(self):
        hit = {"id": 10, "name": "作品", "name_cn": "作品", "platform": "漫画",
               "series": True, "summary": "简介", "infobox": []}
        with patch.object(workbench_match, "BangumiArchiveDataSource") as source, \
             patch.object(workbench_match, "core_request") as native:
            source.return_value.store.ready.return_value = True
            source.return_value._get_search_results_from_archive.return_value = [hit]
            source.return_value.get_subject_metadata.return_value = hit
            query = {"card": "server::lib", "id": "one", "query": "作品"}
            result = workbench_match.search(backend, query)
            self.assertEqual(result["items"][0]["id"], "10")
            query["subject_id"] = "10"
            preview = workbench_match.preview(backend, query)
            self.assertEqual(preview["provider"], "BANGUMI_OFFLINE")
            self.assertNotIn("summary", preview["fields"])  # Locked field.
            native.assert_not_called()

    def test_explicit_provider_does_not_change_automatic_config(self):
        with patch.object(workbench_match, "core_request", return_value=[
            {"id": "md-1", "titles": [{"name": "Comic"}], "fields": {}}
        ]) as native:
            result = workbench_match.search(backend, {"card": "server::lib", "id": "one",
                                                     "provider": "MANGADEX", "query": "Comic"})
            self.assertEqual(result["items"][0]["id"], "md-1")
            self.assertEqual(native.call_args.args[0], "providers.search")
            self.assertEqual(native.call_args.args[1]["provider_config"]["providers"][0]["enabled"], True)

    def test_confirm_writes_source_snapshots_and_rejects_replay(self):
        hit = {"provider": "MANGADEX", "id": "md-1", "media_type": "comic",
               "titles": [{"name": "New"}], "fields": {"title": "New", "publisher": "Publisher", "summary": "Do not overwrite"}}
        with patch.object(workbench_match, "core_request", return_value=hit):
            preview = workbench_match.preview(backend, {"card": "server::lib", "id": "one",
                                                       "provider": "MANGADEX", "subject_id": "md-1"})
        self.assertNotIn("title", preview["fields"])  # No card overwrite opt-in.
        self.assertNotIn("summary", preview["fields"])
        self.assertEqual(preview["fields"]["publisher"], "Publisher")
        result = workbench_match.apply(backend, {"token": preview["token"]})
        self.assertEqual(result["after"]["publisher"], "Publisher")
        with closing(sqlite3.connect(self.root / "recordsRefreshed.db")) as conn:
            row = conn.execute("SELECT metadata_provider,metadata_before,metadata_after FROM scrape_records").fetchone()
            self.assertEqual(row[0], "MANGADEX")
            self.assertNotIn("publisher", json.loads(row[1]))
            self.assertEqual(json.loads(row[2])["publisher"], "Publisher")
        self.assertEqual(backend._read_scrape_rows()[0]["metadata_provider"], "MANGADEX")
        with self.assertRaises(ValueError):
            workbench_match.apply(backend, {"token": preview["token"]})

    def test_preview_conflict_and_scope_revalidation(self):
        hit = {"provider": "MANGADEX", "id": "md-1", "media_type": "comic",
               "titles": [{"name": "New"}], "fields": {"publisher": "Publisher"}}
        with patch.object(workbench_match, "core_request", return_value=hit):
            preview = workbench_match.preview(backend, {"card": "server::lib", "id": "one",
                                                       "provider": "MANGADEX", "subject_id": "md-1"})
        self.item["metadata"]["publisherLock"] = True
        with self.assertRaisesRegex(ValueError, "已变化"):
            workbench_match.apply(backend, {"token": preview["token"]})
        self.client.update_series_metadata.assert_not_called()
