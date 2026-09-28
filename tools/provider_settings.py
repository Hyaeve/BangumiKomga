"""Validated provider configuration shared by the Web and worker processes."""

DEFAULT_PROVIDERS = [
    {"name": name, "enabled": name == "MANGA_UPDATES", "priority": priority}
    for name, priority in (
        ("MANGA_UPDATES", 10), ("MAL", 20), ("ANILIST", 40), ("MANGADEX", 10),
        ("COMIC_VINE", 110), ("MANGA_BAKA", 10), ("BOOK_WALKER", 10),
        ("YEN_PRESS", 50), ("VIZ", 70), ("WEBTOONS", 130), ("EHENTAI", 10))
]
NAMES = {item["name"] for item in DEFAULT_PROVIDERS}
PRIORITIES = {item["name"]: item["priority"] for item in DEFAULT_PROVIDERS}
FIELDS = {"title", "summary", "publisher", "status", "genres", "tags", "alternateTitles",
          "ageRating", "totalBookCount", "language", "links", "thumbnail", "books",
          "authors", "releaseDate", "readingDirection", "titleSort"}


def validate_providers(value):
    if not isinstance(value, list) or len(value) > len(NAMES):
        raise ValueError("元数据提供商配置格式不正确")
    result, seen = [], set()
    for item in value:
        if not isinstance(item, dict) or item.get("name") not in NAMES or item["name"] in seen:
            raise ValueError("元数据提供商名称无效或重复")
        seen.add(item["name"])
        allowed = {"name", "enabled", "priority", "api_key", "token", "database",
                   "matching_mode", "fields", "tags_score_threshold", "tags_size_limit",
                   "title_language", "use_original_publisher", "tag_whitelist",
                   "book_fields", "id_format", "gid_only", "languages", "cover_languages", "author_roles", "artist_roles"}
        if set(item) - allowed:
            raise ValueError("元数据提供商存在不支持的配置项")
        clean = dict(item)
        if type(clean.get("enabled", False)) is not bool:
            raise ValueError("提供商启用状态必须为布尔值")
        priority = clean.get("priority", PRIORITIES[item["name"]])
        if type(priority) is not int or not -1000 <= priority <= 1000:
            raise ValueError("提供商优先级必须为 -1000 到 1000 的整数")
        clean["priority"] = priority
        for field in ("api_key", "token", "database", "title_language", "id_format"):
            if field in clean and (not isinstance(clean[field], str) or len(clean[field]) > 4096):
                raise ValueError("提供商配置文本格式不正确")
        if clean.get("matching_mode", "") not in ("", "EXACT", "CLOSEST_MATCH"):
            raise ValueError("提供商匹配模式无效")
        fields = clean.get("fields", {})
        if not isinstance(fields, dict) or set(fields) - FIELDS or any(type(v) is not bool for v in fields.values()):
            raise ValueError("提供商字段过滤配置无效")
        for field in ("tags_score_threshold", "tags_size_limit"):
            if field in clean and (type(clean[field]) is not int or not 0 <= clean[field] <= 100):
                raise ValueError("标签阈值和数量上限必须为 0 到 100")
        if "use_original_publisher" in clean and type(clean["use_original_publisher"]) is not bool:
            raise ValueError("出版商选择配置无效")
        if "gid_only" in clean and type(clean["gid_only"]) is not bool:
            raise ValueError("GID 匹配开关格式无效")
        book_fields = clean.get("book_fields", {})
        if (not isinstance(book_fields, dict)
                or set(book_fields) - {"title", "summary", "number", "numberSort", "releaseDate", "authors", "tags", "isbn", "links", "thumbnail"}
                or any(type(value) is not bool for value in book_fields.values())):
            raise ValueError("提供商卷册字段配置无效")
        languages = clean.get("languages", [])
        if not isinstance(languages, list) or len(languages) > 20 or any(not isinstance(value, str) or len(value) > 20 for value in languages):
            raise ValueError("提供商语言优先级格式无效")
        languages = clean.get("cover_languages", [])
        if not isinstance(languages, list) or len(languages) > 20 or any(not isinstance(value, str) or len(value) > 20 for value in languages):
            raise ValueError("提供商封面语言格式无效")
        for key in ("author_roles", "artist_roles"):
            roles = clean.get(key, [])
            if (not isinstance(roles, list) or len(roles) > 10
                    or any(not isinstance(role, str) or role not in {"writer", "penciller", "inker", "colorist", "letterer", "cover", "editor", "translator"} for role in roles)):
                raise ValueError("提供商作者职责配置无效")
        tags = clean.get("tag_whitelist", [])
        if not isinstance(tags, list) or len(tags) > 1000 or any(not isinstance(tag, str) or len(tag) > 100 for tag in tags):
            raise ValueError("标签白名单配置无效")
        result.append(clean)
    return result
