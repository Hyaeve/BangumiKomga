"""Explicit manual refresh, isolated to the selected server and media card."""
import json
import sys


def main():
    from config import config
    from services.runtime_service import configure_server
    from services.media_policy import media_type

    request = json.load(sys.stdin)
    configure_server(config, request["server_id"])
    selected = set(request["library_ids"])
    config.KOMGA_LIBRARY_LIST = [card for card in config.KOMGA_LIBRARY_LIST if card["LIBRARY"] in selected]
    config.KOMGA_COLLECTION_LIST = []
    if not config.KOMGA_LIBRARY_LIST:
        raise ValueError("所选媒体卡片不存在")
    from core import refresh_metadata as scraper
    if not request["full"]:
        scraper.refresh_partial_metadata(library_ids=list(selected))
        return
    for card in config.KOMGA_LIBRARY_LIST:
        batch = []
        for item in scraper.komga.iter_library_series(card["LIBRARY"]):
            item["is_novel"] = media_type(card) == "book"
            batch.append(item)
            if len(batch) >= 100:
                scraper.refresh_metadata(batch)
                batch = []
        if batch:
            scraper.refresh_metadata(batch)


if __name__ == "__main__":
    main()
