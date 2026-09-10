"""Backwards-compatible card policy shared by UI persistence and workers."""


def media_type(card):
    value = card.get("MEDIA_TYPE")
    return value if value in ("comic", "book", "mixed") else ("book" if card.get("IS_NOVEL_ONLY") else "comic")


def scrape_enabled(card):
    return card.get("SCRAPE_ENABLED", True) is not False
