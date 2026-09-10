"""Translate existing Komga summaries independently of incremental scrape state."""
from tools.summary_translation import summary_is_chinese, translate_summary_to_zh
from tools.komga_path import item_path


def translate_library(komga, library_id, settings, on_update, on_log):
    if not all(settings.get(key) for key in ("OPENAI_BASE_URL", "OPENAI_API_KEY", "OPENAI_MODEL")):
        raise ValueError("请先保存完整的 AI URL、密钥和模型")
    counts = {"updated": 0, "skipped": 0, "failed": 0}

    def update(item, kind, series_name):
        metadata = item.get("metadata") or {}
        text = str(metadata.get("summary") or "").strip()
        if metadata.get("summaryLock") or not text:
            counts["skipped"] += 1
            return
        payload = {"summaryLock": True}
        if not summary_is_chinese(text):
            translated = translate_summary_to_zh(text, True, settings=settings)
            if not summary_is_chinese(translated):
                counts["failed"] += 1
                on_log(f"{item.get('name', item['id'])}：翻译未成功，保留原文且不锁定", "error")
                return
            payload["summary"] = translated
        # Check the current lock again after a potentially slow AI request.
        latest = komga.get_specific_series(item["id"]) if kind == "series" else komga.get_specific_book(item["id"])
        current = latest.get("metadata") or {}
        if current.get("summaryLock") or current.get("summary") != metadata.get("summary"):
            counts["skipped"] += 1
            return
        success = (komga.update_series_metadata if kind == "series" else komga.update_book_metadata)(item["id"], payload)
        if not success:
            counts["failed"] += 1
            on_log(f"{item.get('name', item['id'])}：简介写入失败", "error")
            return
        counts["updated"] += 1
        on_update({**item, "url": item_path(latest) or item_path(item)}, kind, series_name, list(payload))
        on_log(f"{item.get('name', item['id'])}：{'翻译并锁定简介' if 'summary' in payload else '中文简介已锁定'}", "info")

    for series in komga.iter_library_series(library_id):
        update(series, "series", series.get("name", ""))
        for book in komga.iter_series_books(series["id"]):
            update(book, "volume", series.get("name", ""))
    return counts
