"""Explicit archive update in an isolated process with current saved config."""
from bangumi_archive.archive_autoupdater import check_archive


if __name__ == "__main__":
    if not check_archive():
        raise SystemExit("Bangumi 离线库更新未完成，请检查容器日志")
