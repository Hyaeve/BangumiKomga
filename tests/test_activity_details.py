import unittest
from tools.activity_details import config_changes, task_details


class ActivityDetailsTests(unittest.TestCase):
    def test_config_changes_identify_actions_without_secret_values(self):
        state = {
            "OPENAI_API_KEY":"secret-ai", "BANGUMI_ACCESS_TOKEN":"secret-bgm",
            "KOMGA_SERVERS":[{"id":"s","name":"家庭书库","password":"secret-password","api_key":"secret-komga"}],
            "KOMGA_LIBRARY_LIST":[{"SERVER_ID":"s","LIBRARY":"l","REQUIRED_FIELDS":["summary"],
                                   "OVERWRITE_FIELDS":["title"],"LOGIN_BACKGROUND":True}],
            "RECORD_RETENTION_DAYS":60,
        }
        detail = config_changes({}, state)
        for secret in ("secret-ai","secret-bgm","secret-password","secret-komga"):
            self.assertNotIn(secret, detail)
        for label in ("添加Komga 服务：家庭书库","添加媒体卡片","简介","标题","登录背景：开启","60"):
            self.assertIn(label, detail)
        self.assertIn("删除媒体卡片", config_changes(state, {}))
        self.assertIn("\n", detail)

    def test_task_details_include_scope_and_policy(self):
        task = dict(name="夜间翻译",functions=["summary_translation"],fields=["summary","authors"],
                    include_locked=True,lock_completed=False,card_ids=["s::l"],cron="0 2 * * *")
        result = task_details(task,{"KOMGA_SERVERS":[{"id":"s","name":"家庭书库"}]})
        for label in ("夜间翻译","AI翻译","简介、作者","家庭书库","媒体库 ID：l","0 2 * * *","包含锁定：开启","完成锁定：关闭"):
            self.assertIn(label,result)

    def test_task_enable_change_and_reorder_are_described(self):
        first = {"id":"one","name":"任务一","enabled":True}
        second = {"id":"two","name":"任务二","enabled":True}
        before={"METADATA_TASKS":[first,second]}
        self.assertIn("调整排列顺序",config_changes(before,{"METADATA_TASKS":[second,first]}))
        self.assertIn("定时状态：停用",config_changes(before,{"METADATA_TASKS":[{**first,"enabled":False},second]}))


if __name__ == "__main__":
    unittest.main()
