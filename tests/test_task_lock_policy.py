import unittest
from copy import deepcopy
from unittest.mock import Mock, patch

from tools.task_lock_policy import completion_payload, lock_existing_completion, task_lock_options
from tools.correction_task import correct_library
from tools.translation_task import translate_library
from tools.ai_completion import complete_unmatched


class TaskLockPolicyTests(unittest.TestCase):
    def client(self, metadata):
        item = {"id": "s", "name": "测试漫画", "metadata": metadata}
        client = Mock()
        client.iter_library_series.return_value = iter([item])
        client.iter_series_books.return_value = iter([])
        client.get_specific_series.return_value = deepcopy(item)
        client.update_series_metadata.return_value = True
        return client, item

    def test_legacy_defaults_and_explicit_off(self):
        self.assertEqual(task_lock_options({"functions":["summary_translation"]}),
                         dict(include_locked=False, lock_completed=True))
        self.assertTrue(task_lock_options({"operations":["include_locked"]})["include_locked"])
        self.assertEqual(task_lock_options({"functions":["summary_translation"],
                         "include_locked":False,"lock_completed":False,"operations":["include_locked"]}),
                         dict(include_locked=False, lock_completed=False))

    def test_completion_scope_empty_values_and_locks(self):
        original = dict(title="已有标题", summary="", summaryLock=True, publisher="")
        candidates = dict(title="新标题", summary="简介", publisher="", authors=[{"name":"作者"}])
        self.assertEqual(completion_payload(original,candidates,["title","summary","publisher"]), {})
        self.assertEqual(completion_payload(original,candidates,["title","summary","publisher"],True,True),
                         {"titleLock":True,"summary":"简介"})
        self.assertEqual(completion_payload({"summary":""},{"summary":"简介"},["summary"],False,True),
                         {"summary":"简介","summaryLock":True})

    def test_correction_can_lock_already_simplified_and_include_locked(self):
        client, item = self.client({"title":"已经简体标题","summary":"繁體簡介","summaryLock":True})
        correct_library(client,"l",{},Mock(),Mock(),["title","summary"],["simplify"],
                        include_locked=True, lock_completed=True)
        client.update_series_metadata.assert_called_once_with("s",{"titleLock":True,"summary":"繁体简介"})

    def test_failed_extraction_does_not_lock_or_touch_other_fields(self):
        client, item = self.client({"title":"原始名称","summary":"繁體簡介"})
        with patch("tools.correction_task.recognize_title", return_value=""):
            correct_library(client,"l",{},Mock(),Mock(),["title","summary"],["extract_title"], lock_completed=True)
        client.update_series_metadata.assert_not_called()

    def test_translation_include_locked_and_lock_switch_off(self):
        client, item = self.client({"summary":"English summary","summaryLock":True,"publisher":"中文出版社"})
        settings = dict(OPENAI_BASE_URL="url",OPENAI_API_KEY="key",OPENAI_MODEL="model")
        with patch("tools.translation_task.translate_summary_to_zh",return_value="中文简介"):
            translate_library(client,"l",settings,Mock(),Mock(),["summary","publisher"],
                              include_locked=True,lock_completed=False)
        client.update_series_metadata.assert_called_once_with("s",{"summary":"中文简介"})

    def test_translation_partial_failure_only_locks_successful_field(self):
        client, item = self.client({"summary":"English","publisher":"中文出版社"})
        settings = dict(OPENAI_BASE_URL="url",OPENAI_API_KEY="key",OPENAI_MODEL="model")
        with patch("tools.translation_task.translate_summary_to_zh",return_value=""):
            translate_library(client,"l",settings,Mock(),Mock(),["summary","publisher"], lock_completed=True)
        client.update_series_metadata.assert_called_once_with("s",{"publisherLock":True})

    def test_failed_patch_is_not_followed_by_lock_request(self):
        client, item = self.client({"summary":"繁體簡介"})
        client.update_series_metadata.return_value = False
        update = Mock()
        result = correct_library(client,"l",{},update,Mock(),["summary"],["simplify"],lock_completed=True)
        self.assertEqual(result["failed"],1)
        self.assertEqual(client.update_series_metadata.call_count,1)
        update.assert_not_called()

    def test_completion_of_existing_field_rechecks_concurrent_changes(self):
        client, item = self.client({"title":"已有标题","summary":""})
        client.get_specific_series.return_value["metadata"]["title"] = "用户修改"
        lock_existing_completion(client,item,"series",["title","summary"],Mock(),Mock())
        client.update_series_metadata.assert_not_called()
        client.get_specific_series.return_value = deepcopy(item)
        lock_existing_completion(client,item,"series",["title","summary"],Mock(),Mock())
        client.update_series_metadata.assert_called_once_with("s",{"titleLock":True})

    def test_ai_completion_uses_same_lock_policy(self):
        client, item = self.client({"summary":"","summaryLock":True,"publisher":""})
        with patch("tools.ai_completion.search_metadata",return_value={"summary":"简介","publisher":"出版商"}):
            complete_unmatched(client,item,["summary","publisher"],{},False,Mock(),Mock(),
                               include_locked=True,lock_completed=True)
        client.update_series_metadata.assert_called_once_with("s",
            {"summary":"简介","publisher":"出版商","publisherLock":True})


if __name__ == "__main__":
    unittest.main()
