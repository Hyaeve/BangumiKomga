"""Resolve filesystem paths from Komga DTOs without fabricating directories."""


def item_path(item):
    if not isinstance(item, dict):
        return ""
    media = item.get("media") or {}
    for value in (item.get("url"), item.get("filePath"), item.get("path"), media.get("filePath")):
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def resolve_item_path(komga, item, kind):
    path = item_path(item)
    if path or not item.get("id"):
        return path
    detail = (komga.get_specific_series if kind == "series" else komga.get_specific_book)(item["id"])
    return item_path(detail)
