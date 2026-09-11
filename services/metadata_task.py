"""Isolated completion worker, scoped to one saved Komga server and its cards."""
import json
import sys
from services.media_policy import media_type


def main():
    from config import config
    from services.runtime_service import configure_server
    request = json.load(sys.stdin)
    configure_server(config, request["server_id"])
    fields = request["fields"]
    library_ids = set(request["library_ids"])
    config.KOMGA_LIBRARY_LIST = [
        {**card, "REQUIRED_FIELDS": fields, "OVERWRITE_FIELDS": [],
         "TRANSLATE_SUMMARY_TO_ZH": False, "SORT_VOLUMES": bool(set(fields) & {"number", "numberSort"})}
        for card in config.KOMGA_LIBRARY_LIST if card["LIBRARY"] in library_ids
    ]
    if not config.KOMGA_LIBRARY_LIST:
        raise ValueError("没有可执行的媒体库卡片")
    config.KOMGA_COLLECTION_LIST = []
    config.RECHECK_FAILED_SERIES = True
    config.CREATE_FAILED_COLLECTION = False
    from core import refresh_metadata as scraper
    scraper.TASK_COMPLETION_FIELDS = set(fields)
    scraper.TASK_AI_COMPLETION = bool(request.get("ai_completion"))
    scraper.TASK_INCLUDE_LOCKED = bool(request.get("include_locked"))
    scraper.TASK_LOCK_COMPLETED = bool(request.get("lock_completed"))
    scraper.TASK_INCLUDE_VOLUMES = bool(request.get("include_volumes", True))
    def lock_existing(item, card, kind, series_name):
        if not scraper.TASK_LOCK_COMPLETED:
            return
        from tools.task_lock_policy import lock_existing_completion
        from tools.db import record_scrape_event, record_activity_log
        def record(updated, event_kind, changed):
            record_scrape_event(scraper.conn, "小说" if media_type(card) == "book" else "漫画",
                                updated.get("name", ""), card["LIBRARY"], scraper._library_name(card["LIBRARY"]),
                                changed, source_title=series_name, event_kind=event_kind,
                                source_path=updated.get("url", ""), komga_id=updated["id"],
                                server_id=request["server_id"], match_source="计划任务：已完整元数据锁定")
        def log(detail, level):
            record_activity_log(scraper.conn, "计划任务：元数据补全", detail, level=level, source="scheduler")
        try:
            lock_existing_completion(scraper.komga, item, kind, fields, record, log)
        except Exception as exc:
            log(f"{item.get('name', item['id'])}：完成状态检查失败：{exc}", "error")
    series = []
    for card in config.KOMGA_LIBRARY_LIST:
        for item in scraper.komga.iter_library_series(card["LIBRARY"]):
            item["is_novel"] = media_type(card) == "book"
            lock_existing(item, card, "series", item.get("name", ""))
            if scraper.TASK_LOCK_COMPLETED and scraper.TASK_INCLUDE_VOLUMES:
                for book in scraper.komga.iter_series_books(item["id"]):
                    lock_existing(book, card, "volume", item.get("name", ""))
            series.append(item)
            if len(series) >= 100:
                scraper.refresh_metadata(series)
                series = []
    if series:
        scraper.refresh_metadata(series)


if __name__ == "__main__":
    main()
