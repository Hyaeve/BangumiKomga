import unittest
from tools.komf_matching import match_bangumi, name_matches


class KomfMatchingTests(unittest.TestCase):
    def subject(self, item_id, name, **extra):
        return {"id": item_id, "name": name, "platform": "漫画", "series": True, **extra}

    def test_length_threshold_and_order_not_percentage_ranking(self):
        self.assertFalse(name_matches("Nar", "Nart"))
        self.assertTrue(name_matches("Berserk", "Berserku"))
        first = self.subject(1, "Berserku")
        exact = self.subject(2, "Berserk")
        self.assertEqual(match_bangumi("Berserk", [first, exact]), [first])

    def test_alias_variant_and_nested_version(self):
        item = self.subject(1, "Original", infobox=[{"key": "资料", "value": [{"k": "版本名", "v": "三月的獅子"}]}])
        self.assertEqual(match_bangumi("三月的狮子", [item]), [item])

    def test_online_primary_match_precedes_alias_fetch(self):
        alias = self.subject(1, "Original")
        primary = self.subject(2, "Test")
        calls = []
        def get(item_id):
            calls.append(item_id)
            return primary
        self.assertEqual(match_bangumi("Test", [alias, primary], offline=False, detail_loader=get), [primary])
        self.assertEqual(calls, [2])

    def test_online_and_offline_series_filter_differ(self):
        item = self.subject(1, "Test", series=False)
        self.assertEqual(match_bangumi("Test", [item]), [])
        self.assertEqual(match_bangumi("Test", [item], offline=False), [item])
        item["tags"] = [{"name": "漫画单行本"}]
        self.assertEqual(match_bangumi("Test", [item], offline=False), [])
