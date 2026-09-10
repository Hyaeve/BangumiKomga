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
    series = []
    for card in config.KOMGA_LIBRARY_LIST:
        for item in scraper.komga.iter_library_series(card["LIBRARY"]):
            item["is_novel"] = media_type(card) == "book"
            series.append(item)
            if len(series) >= 100:
                scraper.refresh_metadata(series)
                series = []
    if series:
        scraper.refresh_metadata(series)


if __name__ == "__main__":
    main()
