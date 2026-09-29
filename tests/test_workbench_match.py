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
