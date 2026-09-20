"""Validation for explicit user edits, separate from automatic scraping policy."""
import math
from datetime import date
from urllib.parse import urlsplit

SERIES_FIELDS = {
    "title", "titleSort", "summary", "publisher", "status", "language",
    "ageRating", "totalBookCount", "genres", "tags", "alternateTitles", "links",
}
BOOK_FIELDS = {
    "title", "summary", "number", "numberSort", "releaseDate", "isbn",
    "authors", "tags", "links", "readingDirection",
}
ENUMS = {
    "status": {"ONGOING", "ENDED", "ABANDONED", "HIATUS"},
    "readingDirection": {"LEFT_TO_RIGHT", "RIGHT_TO_LEFT", "VERTICAL", "WEBTOON"},
}
ROLES = {"writer", "penciller", "inker", "colorist", "letterer", "cover", "editor", "translator"}
OBJECT_FIELDS = {"authors": {"name", "role"}, "links": {"label", "url"}, "alternateTitles": {"label", "title"}}


def editable_fields(kind):
    return SERIES_FIELDS if kind == "series" else BOOK_FIELDS


def same_value(field, left, right):
    if field in {"tags", "genres"} and isinstance(left, list) and isinstance(right, list):
        return set(left) == set(right)
    return left == right


def validate_changes(changes, kind):
    if not isinstance(changes, dict) or not changes or not set(changes) <= editable_fields(kind):
        raise ValueError("请选择可编辑的元数据字段；锁定状态和系统字段不在编辑范围内")
    for field, value in changes.items():
        valid = True
        if field in {"ageRating", "totalBookCount", "numberSort"}:
            valid = value is None or (
                type(value) in (int, float) and math.isfinite(value) and value >= 0
                and (field == "numberSort" or type(value) is int)
                and (field != "ageRating" or value <= 99)
                and (field != "totalBookCount" or value > 0))
        elif field in ENUMS:
            valid = (value is None and field == "readingDirection") or (isinstance(value, str) and value in ENUMS[field])
        elif field in {"tags", "genres"}:
            valid = isinstance(value, list) and len(value) <= 1000 and all(
                isinstance(item, str) and 0 < len(item.strip()) <= 200 for item in value)
        elif field in OBJECT_FIELDS:
            valid = isinstance(value, list) and len(value) <= 1000
            if valid:
                for item in value:
                    if not isinstance(item, dict) or set(item) != OBJECT_FIELDS[field] or not all(
                            isinstance(text, str) and 0 < len(text.strip()) <= 2000 for text in item.values()):
                        valid = False
                        break
                    if field == "authors" and item["role"] not in ROLES:
                        valid = False
                    if field == "links":
                        url = urlsplit(item["url"])
                        valid = url.scheme in {"http", "https"} and bool(url.netloc) and not url.username and not url.password
                    if not valid:
                        break
        elif field == "releaseDate":
            valid = value is None or isinstance(value, str)
            if valid and value:
                try:
                    date.fromisoformat(value)
                except ValueError:
                    valid = False
        else:
            valid = isinstance(value, str) and len(value) <= (200000 if field == "summary" else 2000)
            if field == "title":
                valid = valid and bool(value.strip())
        if not valid:
            raise ValueError(f"元数据字段 {field} 的格式或内容无效，标题不能为空")
    return changes
