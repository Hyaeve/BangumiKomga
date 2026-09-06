"""Optional OpenAI-compatible translation for Bangumi summaries.

This module is deliberately isolated from the scraper and uses ``requests``,
which is already a project dependency. Removing this file and the four related
config values cleanly disables the optional integration.
"""

from __future__ import annotations

import requests

from config import config as app_config
from tools.log import logger


def translate_summary_to_zh(summary: str) -> str:
    """Return a Simplified Chinese translation, or the source on any failure."""
    text = (summary or "").strip()
    base_url = str(getattr(app_config, "OPENAI_BASE_URL", "") or "").strip().rstrip("/")
    api_key = str(getattr(app_config, "OPENAI_API_KEY", "") or "").strip()
    model = str(getattr(app_config, "OPENAI_MODEL", "") or "").strip()
    enabled = bool(getattr(app_config, "TRANSLATE_SUMMARY_TO_ZH", False))

    if not text or not enabled or not (base_url and api_key and model):
        return text
    endpoint = base_url if base_url.endswith("/chat/completions") else f"{base_url}/chat/completions"
    payload = {
        "model": model,
        "temperature": 0.1,
        "messages": [
            {
                "role": "system",
                "content": "Translate the supplied book or comic summary into concise Simplified Chinese. Return only the translation; preserve names, dates, and line breaks.",
            },
            {"role": "user", "content": text},
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
        translated = response.json()["choices"][0]["message"]["content"].strip()
        return translated or text
    except (KeyError, IndexError, TypeError, ValueError, requests.RequestException) as exc:
        logger.warning("简介中文翻译失败，保留原文：%s", exc)
        return text
