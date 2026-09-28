import unittest
from unittest.mock import MagicMock, patch
from tempfile import TemporaryDirectory
from unittest.mock import patch
from tools.log import logger
from tools.resort_search_results_list import resort_search_list, compute_name_score_by_fuzzy


class TestSearchResort(unittest.TestCase):
    def setUp(self):
        """设置测试环境"""
        self.data_source = MagicMock()
        self.mock_metadata = {
            "id": 1,
            "name": "Test Series",
            "series": True,
            "platform": 1,
            "infobox": [],
            "name_cn": ""
        }

    def test_threshold_filtering(self):
        """测试搜索结果排序器 - 阈值过滤"""
        results = [{
            "id": 1,
            "name": "Test Series",
            "series": True,
            "platform": 1,  # 假设是 Comic
            "infobox": [],
            "name_cn": ""
        }]
        self.data_source.get_subject_metadata.return_value = self.mock_metadata
        filtered = resort_search_list("Test", results, 90, False)
        # 验证低分结果被过滤
        self.assertEqual(len(filtered), 0, "应过滤掉低于阈值的结果")

    def test_sorting_accuracy(self):
        """测试搜索结果排序器 - 排序准确性"""
        # 创建多个测试结果并验证排序顺序
        # 创建测试元数据集合
        from api.bangumi_model import SubjectPlatform
        results = [
            # 高分条目（完全匹配中文名）
            {
                "id": 1,
                "name": "English1",
                "series": True,
                "platform": SubjectPlatform.Comic.value,  # 明确使用枚举值
                "infobox": [],
                "name_cn": "中文匹配"
            },
            # 中等分数条目（部分匹配中文名）
            {
                "id": 2,
                "name": "English2",
                "series": True,
                "platform": SubjectPlatform.Comic.value,
                "infobox": [],
                "name_cn": "中文匹配集"
            },
            # 低分条目（别名匹配）
            {
                "id": 3,
                "name": "Base Name",
                "series": True,
                "platform": SubjectPlatform.Comic.value,
                "infobox": [{"key": "别名", "value": [{"v": "中文件名"}]}],
                "name_cn": ""
            }
        ]

        # 配置数据源返回
        sorted_results = resort_search_list("中文匹配", results, 30, False)

        # 验证基础条件
        self.assertEqual([item["id"] for item in sorted_results], [1])
        self.assertNotIn("fuzzScore", sorted_results[0])
        # Reference selects the first eligible match, without percentage ranking.
        self.assertEqual([item["id"] for item in resort_search_list("中文匹配", results[1::-1], 99)], [2])


class TestFuzzyNameScoring(unittest.TestCase):
    def test_exact_match(self):
        """测试模糊名称评分器 - 完全匹配"""
        self.assertEqual(compute_name_score_by_fuzzy(
            "Test", "", [], "Test"), 100)

    def test_chinese_name_priority(self):
        """测试模糊名称评分器 - 中文名优先级"""
        score = compute_name_score_by_fuzzy("English", "中文", [], "中文")
        self.assertEqual(score, 100)

    def test_aliases_scoring(self):
        """测试模糊名称评分器 - 别名匹配"""
        infobox = [{"key": "别名", "value": [{"v": "Alias1"}, {"v": "Alias2"}]}]
        score = compute_name_score_by_fuzzy("Base", "", infobox, "Alias2")
        self.assertGreater(score, 80)  # 根据实际fuzz结果调整
