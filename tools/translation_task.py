"""Translate selected unlocked Komga fields independently of scrape timestamps."""
from copy import deepcopy

from tools.summary_translation import summary_is_chinese, translate_summary_to_zh
from tools.komga_path import item_path
from tools.execution_outcomes import record_outcome
from tools.task_lock_policy import locked

TRANSLATION_FIELDS = {"title": "标题", "summary": "简介", "publisher": "出版商", "authors": "作者"}


def translate_library(komga, library_id, settings, on_update, on_log, fields=None,
                      include_locked=False, lock_completed=True, include_volumes=True):
    if not all(settings.get(key) for key in ("OPENAI_BASE_URL", "OPENAI_API_KEY", "OPENAI_MODEL")):
        raise ValueError("请先保存完整的 AI URL、密钥和模型")
    selected = list(dict.fromkeys(["summary"] if fields is None else fields))
    if not selected or any(field not in TRANSLATION_FIELDS for field in selected):
        raise ValueError("请选择有效的 AI 翻译元数据项")
    counts = {"updated": 0, "skipped": 0, "failed": 0}

    def translate_text(text, field):
        if not isinstance(text, str) or not text.strip():
            raise ValueError("元数据文本为空或格式无效")
        text = text.strip()
        if summary_is_chinese(text):
            return text
        kwargs = {} if field == "summary" else {"field": field}
        result = translate_summary_to_zh(text, True, settings=settings, **kwargs)
        # Single-character Chinese names are valid, unlike empty/error responses.
        if not summary_is_chinese(result) and not (len(result) == 1 and "\u3400" <= result <= "\u9fff"):
            raise ValueError("翻译未成功，保留原文且不锁定")
        return result

    def translated_value(value, field):
        if field != "authors":
            return translate_text(value, field)
        if not isinstance(value, list):
            raise ValueError("作者列表格式无效")
        result = deepcopy(value)
        for author in result:
            if not isinstance(author, dict):
                raise ValueError("作者格式无效")
            author["name"] = translate_text(author.get("name"), field)
        return result

    def update(item, kind, series_name):
        metadata = item.get("metadata") or {}
        payload = {}
        changed_fields = []
        for field in selected:
            value = metadata.get(field)
            if (locked(metadata, field) and not include_locked) or not value:
                continue
            try:
                translated = translated_value(value, field)
            except ValueError as exc:
                record_outcome(kind, item["id"], failed=True)
                counts["failed"] += 1
                on_log(f"{item.get('name', item['id'])} / {TRANSLATION_FIELDS[field]}：{exc}", "error")
                continue
            if translated != value:
                payload[field] = translated
            if lock_completed and not locked(metadata, field):
                payload[field + "Lock"] = True
            changed_fields.append(field)
        if not payload:
            counts["skipped"] += 1
            return
        # Recheck each field separately so a concurrent edit only cancels that field.
        latest = komga.get_specific_series(item["id"]) if kind == "series" else komga.get_specific_book(item["id"])
        current = latest.get("metadata") or {}
        for field in changed_fields[:]:
            if (locked(current, field) and not include_locked) or current.get(field) != metadata.get(field):
                payload.pop(field, None)
                payload.pop(field + "Lock", None)
                changed_fields.remove(field)
        if not payload:
            counts["skipped"] += 1
            return
        success = (komga.update_series_metadata if kind == "series" else komga.update_book_metadata)(item["id"], payload)
        if not success:
            record_outcome(kind, item["id"], failed=True)
            counts["failed"] += 1
            on_log(f"{item.get('name', item['id'])}：翻译元数据写入失败", "error")
            return
        counts["updated"] += 1
        record_outcome(kind, item["id"])
        on_update({**item, "url": item_path(latest) or item_path(item)}, kind, series_name, changed_fields)
        on_log(f"{item.get('name', item['id'])}：已处理{'并锁定' if lock_completed else ''} {'、'.join(TRANSLATION_FIELDS[field] for field in changed_fields)}", "info")

    def process(item, kind, series_name):
        try:
            update(item, kind, series_name)
        except Exception as exc:
            counts["failed"] += 1
            record_outcome(kind, item["id"], failed=True)
            on_log(f"{item.get('name', item['id'])}：元数据处理失败：{exc}", "error")

    for series in komga.iter_library_series(library_id):
        process(series, "series", series.get("name", ""))
        if include_volumes:
            for book in komga.iter_series_books(series["id"]):
                process(book, "volume", series.get("name", ""))
    return counts
