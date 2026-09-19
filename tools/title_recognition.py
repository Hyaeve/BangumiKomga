"""Optional OpenAI-compatible title extraction for scrape-card matching.

This integration is isolated from title parsing and Bangumi search. If the
endpoint is absent, unavailable, or returns unusable text, callers simply
continue with their final raw-name fallback.
"""

from __future__ import annotations

import re
from urllib.parse import urlsplit

import requests
from tools.proxy_settings import proxy_kwargs

from tools.log import logger


def normalize_extracted_title(value):
    """Reject empty responses and model failure markers before metadata writes."""
    if not isinstance(value, str):
        return ""
    value = value.strip()
    if "\n" in value or "\r" in value:
        return ""
    wrappers = {'"': '"', "'": "'", "`": "`", "“": "”", "‘": "’", "《": "》", "【": "】", "[": "]"}
    while len(value) >= 2 and wrappers.get(value[0]) == value[-1]:
        value = value[1:-1].strip()
    visible = re.sub(r"[\s\u200b-\u200f\u202a-\u202e\u2060\ufeff]", "", value)
    if not visible or not any(char.isalnum() for char in visible) or len(value) > 200 or value.casefold().strip("。.!！：:") in (
        "null", "none", "unknown", "n/a", "empty", "empty string",
        "空", "空字符串", "（空字符串）", "(空字符串)", "无法识别", "无法提取", "未知",
    ):
        return ""
    return value


def recognize_title(name: str, only_novel: bool = False, settings=None, *, from_path=False) -> str:
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
                "content": (
                    f"从文件路径中最近两层文件夹和文件名提取一个最可能的{kind}正式名称，优先考虑代表作品的目录，忽略卷号、分类目录和文件扩展名。"
                    if from_path else f"从文件名中提取一个最可能的{kind}正式名称。"
                ) + "只输出名称本身，不要解释，不要书名号，不要方括号，不要作者或出版社。无法识别则输出空字符串，不要猜测。",
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
            **proxy_kwargs(endpoint, settings),
        )
        response.raise_for_status()
        value = response.json()["choices"][0]["message"]["content"]
        return normalize_extracted_title(value)
    except (KeyError, IndexError, TypeError, ValueError, requests.RequestException) as exc:
        logger.warning("AI 标题识别失败，继续使用普通标题匹配：%s", exc)
        return ""
