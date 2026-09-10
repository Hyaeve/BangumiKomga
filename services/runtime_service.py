"""Isolated scraper worker managed by the Web process."""

import argparse
from services.media_policy import scrape_enabled


def configure_server(config, server_id):
    """Select one Komga connection before importing the scraper modules."""
    if not server_id:
        return
    server = next((item for item in config.KOMGA_SERVERS if str(item.get("id")) == server_id), None)
    if not server:
        raise ValueError(f"未找到 Komga 服务: {server_id}")
    config.KOMGA_BASE_URL = server.get("base_url", "")
    config.KOMGA_EMAIL = server.get("email", "")
    config.KOMGA_EMAIL_PASSWORD = server.get("password", "")
    config.KOMGA_API_KEY = server.get("api_key", "")
    config.KOMGA_LIBRARY_LIST = [
        item for item in config.KOMGA_LIBRARY_LIST
        if str(item.get("SERVER_ID")) == server_id
    ]


def configure_automatic_libraries(config):
    """Disabled media cards remain saved, but never enter automatic workers."""
    config.KOMGA_LIBRARY_LIST = [card for card in config.KOMGA_LIBRARY_LIST if scrape_enabled(card)]
    config.KOMGA_COLLECTION_LIST = []
    return bool(config.KOMGA_LIBRARY_LIST)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--server-id", default="")
    parser.add_argument("--with-archive", action="store_true")
    parser.add_argument("--archive-only", action="store_true")
    args = parser.parse_args()
    if args.archive_only:
        import threading
        from bangumi_archive.periodic_archive_checker import periodical_archive_check_service
        periodical_archive_check_service()
        threading.Event().wait()

    import config.config as config
    configure_server(config, args.server_id)
    if not configure_automatic_libraries(config):
        import threading
        threading.Event().wait()

    from services.service_runner import run_service
    run_service(include_archive=args.with_archive)
