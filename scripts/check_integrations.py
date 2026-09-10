"""Read-only Komga probe plus one AI request; never writes library metadata."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import web_backend
from tools.komga_path import resolve_item_path
from tools.summary_translation import summary_is_chinese, translate_summary_to_zh


def main():
    state = web_backend._read_state()
    results = []
    settings_present = all(state.get(key) for key in ("OPENAI_BASE_URL", "OPENAI_API_KEY", "OPENAI_MODEL"))
    if settings_present:
        translated = translate_summary_to_zh("A young reader discovers a secret library.", True, state)
        results.append({"service": "AI", "success": summary_is_chinese(translated)})
    else:
        results.append({"service": "AI", "success": False, "reason": "AI URL、密钥或模型尚未配置"})
    cards = state.get("KOMGA_LIBRARY_LIST") or []
    if not cards:
        results.append({"service": "Komga", "success": False, "reason": "尚未配置媒体库卡片"})
    for card in cards:
        client = None
        try:
            client = web_backend._load_komga(card.get("SERVER_ID"))
            series = next(iter(client.iter_library_series(card["LIBRARY"])), None)
            book = next(iter(client.iter_series_books(series["id"])), None) if series else None
            series_path = resolve_item_path(client, series, "series") if series else ""
            book_path = resolve_item_path(client, book, "volume") if book else ""
            results.append({"service": "Komga", "library_id": card["LIBRARY"],
                            "success": bool(series_path), "series_path_available": bool(series_path),
                            "book_path_available": bool(book_path), "empty_library": series is None})
        except Exception as exc:
            results.append({"service": "Komga", "success": False, "error_type": type(exc).__name__})
        finally:
            if client:
                client.r.close()
    print(json.dumps(results, ensure_ascii=False, indent=2))
    return 0 if all(item["success"] for item in results) else 1


if __name__ == "__main__":
    sys.exit(main())
