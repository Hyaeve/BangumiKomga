"""Selected-field metadata correction; existing lock states are preserved."""
from copy import deepcopy

from zhconv import convert
from tools.title_rules import explicit_title, title_filter_rules
from tools.title_recognition import recognize_title
from tools.komga_path import item_path
from tools.execution_outcomes import record_outcome
from tools.task_lock_policy import locked

FIELDS = {"title", "summary", "publisher", "authors"}
OPERATIONS = {"simplify", "extract_title", "include_locked"}


def correct_library(komga, library_id, settings, on_update, on_log, fields, operations, only_novel=False,
                    include_locked=False, lock_completed=False, include_volumes=True, filter_terms=None, filter_regex=False):
    selected = list(dict.fromkeys(fields))
    options = set(operations)
    include_locked = include_locked or "include_locked" in options
    if not selected or not set(selected) <= FIELDS:
        raise ValueError("请选择有效的修正元数据")
    if not options <= OPERATIONS or not options & {"simplify", "extract_title"}:
        raise ValueError("请选择繁转简或标题提取")
    if options & {"extract_title"} and "simplify" not in options and "title" not in selected:
        raise ValueError("标题提取需要选择标题元数据")
    counts = {"updated": 0, "skipped": 0, "failed": 0}
    rules = title_filter_rules(filter_terms, filter_regex) if "extract_title" in options and "title" in selected else []

    def filtered_title(value, matched=None):
        if not rules:
            return value
        def remove(match):
            if matched is not None and match.group():
                matched.add(match.group())
            return ""
        # Anchored regex rules run once; only literal terms may be removed repeatedly.
        if matched is not None:
            for pattern, is_regex in rules:
                value = pattern.sub(remove, value)
        while True:
            filtered = value
            for pattern, is_regex in rules:
                if not is_regex:
                    filtered = pattern.sub(remove, filtered)
            if filtered == value:
                return filtered.strip()
            value = filtered

    def corrected(value, field):
        completed = True
        matched = set()
        if field == "authors":
            if not isinstance(value, list):
                raise ValueError("作者数据格式无效")
            result = deepcopy(value)
            if "simplify" in options:
                for author in result:
                    if not isinstance(author, dict) or not isinstance(author.get("name"), str):
                        raise ValueError("作者数据格式无效")
                    author["name"] = convert(author["name"], "zh-cn")
            return result, completed
        if not isinstance(value, str):
            raise ValueError("文本数据格式无效")
        result = value
        if field == "title" and "extract_title" in options:
            result = filtered_title(result, matched)
            if not result.strip():
                raise ValueError("过滤后标题为空，保留当前标题且不锁定")
            filtered = result
            title = explicit_title(result)
            if not title:
                title = recognize_title(result, only_novel=only_novel, settings=settings)
            if title:
                result = title
                if not result.strip():
                    result, completed = filtered, False
            elif filtered != value:
                result, completed = filtered, False
            else:
                raise ValueError("标题提取失败或未配置 AI，保留当前标题且不锁定")
        if "simplify" in options:
            result = convert(result, "zh-cn")
        if field == "title" and "extract_title" in options:
            for term in sorted(matched, key=len, reverse=True):
                result = result.replace(term, "")
            result = filtered_title(result).strip()
            if not result.strip():
                raise ValueError("过滤后标题为空，保留当前标题且不锁定")
        return result, completed

    def update(item, kind, series_name):
        original = item.get("metadata") or {}
        payload = {}
        for field in selected:
            value = original.get(field)
            if not value or (locked(original, field) and not include_locked):
                continue
            if "simplify" not in options and field != "title":
                continue
            try:
                result, completed = corrected(value, field)
                if result != value:
                    payload[field] = result
                if not completed:
                    record_outcome(kind, item["id"], failed=True)
                    counts["failed"] += 1
                    on_log(f"{item.get('name', '')} / 标题：标题提取未成功，仍应用过滤词条，不新增锁定", "warning")
                if completed and lock_completed and not locked(original, field):
                    payload[field + "Lock"] = True
            except ValueError as exc:
                record_outcome(kind, item["id"], failed=True)
                counts["failed"] += 1
                on_log(f"{item.get('name', '')} / {field}：{exc}", "error")
        if not payload:
            counts["skipped"] += 1
            return
        latest = (komga.get_specific_series if kind == "series" else komga.get_specific_book)(item["id"])
        current = latest.get("metadata") or {}
        payload = {key: value for key, value in payload.items()
                   if current.get(key[:-4] if key.endswith("Lock") else key) == original.get(key[:-4] if key.endswith("Lock") else key)
                   and (not locked(current, key[:-4] if key.endswith("Lock") else key) or include_locked)}
        if not payload:
            counts["skipped"] += 1
            return
        if not (komga.update_series_metadata if kind == "series" else komga.update_book_metadata)(item["id"], payload):
            record_outcome(kind, item["id"], failed=True)
            counts["failed"] += 1
            on_log(f"{item.get('name', '')}：元数据修正写入失败", "error")
            return
        counts["updated"] += 1
        record_outcome(kind, item["id"])
        on_update({**item, "url": item_path(latest) or item_path(item)}, kind, series_name, list(payload))
        on_log(f"{item.get('name', '')}：元数据修正完成（{', '.join(payload)}）", "info")

    def process(item, kind, series_name):
        try:
            update(item, kind, series_name)
        except Exception as exc:
            counts["failed"] += 1
            record_outcome(kind, item["id"], failed=True)
            on_log(f"{item.get('name', item['id'])}：元数据修正失败：{exc}", "error")

    for series in komga.iter_library_series(library_id):
        process(series, "series", series.get("name", ""))
        if include_volumes:
            for book in komga.iter_series_books(series["id"]):
                process(book, "volume", series.get("name", ""))
    return counts
