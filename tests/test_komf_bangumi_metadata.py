import unittest
from tools.komf_bangumi_metadata import series_fields, book_fields


class BangumiMappingTests(unittest.TestCase):
    def test_sparse_metadata_has_no_legacy_defaults_or_score_genre(self):
        fields = series_fields({"id": 1, "name": "Title", "platform": "漫画", "rating": {"score": 9}})
        self.assertEqual(fields["genres"], ["漫画"])
        for key in ("ageRating", "language", "status", "totalBookCount", "titleSort"):
            self.assertNotIn(key, fields)

    def test_counts_status_publishers_and_aliases(self):
        fields = series_fields({"id": 1, "name": "Original", "name_cn": "标题", "platform": "小说",
                                "infobox": [{"key": "册数", "value": "12卷"},
                                            {"key": "出版社", "value": "第一社、第二社"},
                                            {"key": "资料", "value": [{"k": "版本名", "v": "Match only"}, {"k": "别名", "v": "Alias"}]}]})
        self.assertEqual(fields["status"], "ENDED")
        self.assertEqual(fields["totalBookCount"], 12)
        self.assertEqual(fields["publisher"], "第一社")
        self.assertNotIn("Match only", str(fields["alternateTitles"]))

    def test_book_tags_date_isbn_and_title_are_source_values(self):
        fields = book_fields({"id": 1, "name": "Title (2)", "name_cn": "中文标题",
                              "date": "2019年7月25日", "tags": [{"name": "A", "count": 3}, {"name": "B", "count": 1}],
                              "infobox": [{"key": "ISBN", "value": "0-306-40615-2"}]})
        self.assertEqual(fields["title"], "Title (2)")
        self.assertEqual(fields["tags"], ["A"])
        self.assertEqual(fields["releaseDate"], "2019-07-25")
        self.assertEqual(fields["isbn"], "9780306406157")
        self.assertEqual(fields["numberSort"], 2)
