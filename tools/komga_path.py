"""Resolve filesystem paths from Komga DTOs without fabricating directories."""
from itertools import islice
from pathlib import PurePosixPath
from urllib.parse import urlsplit, unquote


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


def title_path_context(path, is_file=True):
    """Keep the filename and its nearest two folders, never the full root."""
    if not isinstance(path, str) or not path.strip():
        return ""
    path = path.strip().replace("\\", "/")
    if path.lower().startswith("file:"):
        path = unquote(urlsplit(path).path)
    elif "://" in path:
        return ""
    parts = [part for part in PurePosixPath(path).parts
             if part not in ("/", "//", ".", "..") and not part.endswith(":")]
    return "/".join(parts[-3:] if is_file else parts[-2:])


def series_title_path(komga, series):
    """Use a real book path where available, falling back to the series folder."""
    try:
        for book in islice(komga.iter_series_books(series["id"]), 3):
            context = title_path_context(resolve_item_path(komga, book, "volume"))
            if context:
                return context
    except Exception:
        pass
    try:
        return title_path_context(resolve_item_path(komga, series, "series"), is_file=False)
    except Exception:
        return ""
