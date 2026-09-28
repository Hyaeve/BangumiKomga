"""Bangumi tag filtering ported from komf-rs; see THIRD_PARTY_NOTICES.md."""
import json
from functools import lru_cache
from pathlib import Path

STATUS_TAGS = {"连载", "连载中", "完结", "已完结", "腰斩", "停刊", "长期休载", "停止连载", "休刊"}


@lru_cache(maxsize=1)
def bangumi_whitelist():
    path = Path(__file__).resolve().parents[1] / "corpus/bangumi_tag_whitelist.json"
    return frozenset(json.loads(path.read_text(encoding="utf-8")))


def bangumi_tags(tags, additional=()):
    whitelist = bangumi_whitelist() | set(additional)
    valid = [(tag["name"], int(tag.get("count") or 0)) for tag in tags or []
             if isinstance(tag, dict) and tag.get("name") in whitelist
             and tag.get("name") not in STATUS_TAGS]
    valid.sort(key=lambda tag: tag[1], reverse=True)
    if not valid:
        return []
    maximum = max(valid[0][1], 1)
    threshold = next((threshold for floor, threshold in
                      ((200, 35), (125, 25), (60, 15), (30, 10), (10, 5))
                      if maximum > floor), 3)
    selected = [tag for tag in valid if tag[1] >= threshold]
    if len(selected) < 10:
        selected = valid[:10]
    return [tag[0] for tag in selected]
