"""Optional OpenAI-compatible title extraction for scrape-card matching.

This integration is isolated from title parsing and Bangumi search. If the
endpoint is absent, unavailable, or returns unusable text, callers simply
continue with their final raw-name fallback.
"""

from __future__ import annotations

import re

import requests

from config import config as app_config
from tools.log import logger


def recognize_title(name: str, only_novel: bool = False) -> str:
    raw = (name or "").strip()
    base_url = str(getattr(app_config, "OPENAI_BASE_URL", "") or "").strip().rstrip("/")
    api_key = str(getattr(app_config, "OPENAI_API_KEY", "") or "").strip()
    model = str(getattr(app_config, "OPENAI_MODEL", "") or "").strip()
    if not raw or not (base_url and api_key and model):
        return ""

    kind = "小说" if only_novel else "漫画或小说"
    endpoint = base_url if base_url.endswith("/chat/completions") else f"{base_url}/chat/completions"
    payload = {
        "model": model,
        "temperature": 0,
        "messages": [
            {
                "role": "system",
                "content": f"从文件名中提取一个最可能的{kind}正式名称。只输出名称本身，不要解释，不要书名号，不要方括号，不要作者或出版社。",
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
        value = re.sub(r"^[\s\"'《【\[]+|[\s\"'》】\]]+$", "", str(value).strip())
        return value.splitlines()[0].strip() if value else ""
    except (KeyError, IndexError, TypeError, ValueError, requests.RequestException) as exc:
        logger.warning("AI 标题识别失败，继续使用普通标题匹配：%s", exc)
        return ""
