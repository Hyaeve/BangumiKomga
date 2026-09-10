"""Optional OpenAI-compatible title extraction for scrape-card matching.

This integration is isolated from title parsing and Bangumi search. If the
endpoint is absent, unavailable, or returns unusable text, callers simply
continue with their final raw-name fallback.
"""

from __future__ import annotations

import re
from urllib.parse import urlsplit

import requests

from tools.log import logger


def recognize_title(name: str, only_novel: bool = False, settings=None) -> str:
    raw = (name or "").strip()
    if settings is None:
        from config import config as app_config
        settings = vars(app_config)
    base_url = str(settings.get("OPENAI_BASE_URL") or "").strip().rstrip("/")
    api_key = str(settings.get("OPENAI_API_KEY") or "").strip()
    model = str(settings.get("OPENAI_MODEL") or "").strip()
    if not raw or not (base_url and api_key and model):
        return ""

    kind = {"comic": "漫画", "book": "非漫画书籍（小说、画集等）", "mixed": "漫画或书籍"}.get(
        only_novel, "小说" if only_novel else "漫画或小说")
    if not urlsplit(base_url).path.strip("/"):
        base_url += "/v1"
    endpoint = base_url if base_url.endswith("/chat/completions") else f"{base_url}/chat/completions"
    payload = {
        "model": model,
        "messages": [
            {
                "role": "system",
                "content": f"从文件名中提取一个最可能的{kind}正式名称。只输出名称本身，不要解释，不要书名号，不要方括号，不要作者或出版社。无法识别则输出空字符串，不要猜测。",
            },
            {"role": "user", "content": raw},
        ],
    }
    try:
        response = requests.post(
            endpoint,
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json=payload,
            timeout=30,
        )
        response.raise_for_status()
        value = response.json()["choices"][0]["message"]["content"]
        if not isinstance(value, str):
            return ""
        value = re.sub(r"^[\s\"'《【\[]+|[\s\"'》】\]]+$", "", value.strip())
        if "\n" in value or len(value) > 200 or value.lower() in ("null", "none", "unknown", "无法识别", "无法提取", "未知"):
            return ""
        return value
    except (KeyError, IndexError, TypeError, ValueError, requests.RequestException) as exc:
        logger.warning("AI 标题识别失败，继续使用普通标题匹配：%s", exc)
        return ""
