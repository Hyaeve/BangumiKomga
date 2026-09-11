"""Optional OpenAI-compatible translation for Bangumi summaries.

This module is deliberately isolated from the scraper and uses ``requests``,
which is already a project dependency. Removing this file and the four related
config values cleanly disables the optional integration.
"""

from __future__ import annotations

import requests
from tools.proxy_settings import proxy_kwargs
import re
from urllib.parse import urlsplit

from tools.log import logger


def summary_is_chinese(value):
    text = str(value or "").strip()
    if not text or re.search(r"[\u3040-\u30ff\uac00-\ud7af]", text):
        return False
    chinese = len(re.findall(r"[\u3400-\u9fff]", text))
    letters = len(re.findall(r"[A-Za-z]", text))
    return chinese >= 2 and chinese >= letters


def translate_summary_to_zh(summary: str, enabled_override=None, settings=None, field="summary", strict=False) -> str:
    """Return a Simplified Chinese translation, or the source on any failure."""
    text = (summary or "").strip()
    if settings is None:
        from config import config as app_config
        settings = vars(app_config)
    base_url = str(settings.get("OPENAI_BASE_URL", "") or "").strip().rstrip("/")
    api_key = str(settings.get("OPENAI_API_KEY", "") or "").strip()
    model = str(settings.get("OPENAI_MODEL", "") or "").strip()
    enabled = bool(settings.get("TRANSLATE_SUMMARY_TO_ZH", False)) if enabled_override is None else bool(enabled_override)

    if not text or not enabled or not (base_url and api_key and model):
        if strict:
            raise ValueError("请填写 AI 接口地址、密钥和模型")
        return text
    if not urlsplit(base_url).path.strip("/"):
        base_url += "/v1"
    endpoint = base_url if base_url.endswith("/chat/completions") else f"{base_url}/chat/completions"
    payload = {
        "model": model,
        "messages": [
            {
                "role": "system",
                "content": (
                    "Translate the supplied book or comic summary into Simplified Chinese. "
                    "Return only the complete translation; preserve names, dates, and line breaks."
                    if field == "summary" else
                    "Translate the supplied " + {"title": "book or comic title", "publisher": "publisher name", "authors": "author name"}.get(field, "metadata")
                    + " into Simplified Chinese. Use the established Chinese name when known. "
                    "Return only the translated value, without explanations, additional titles, or invented details."
                ),
            },
            {"role": "user", "content": text},
        ],
    }
    try:
        response = requests.post(
            endpoint,
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json=payload,
            timeout=(10, 120),
            **proxy_kwargs(endpoint, settings),
        )
        response.raise_for_status()
        content = response.json()["choices"][0]["message"]["content"]
        if isinstance(content, list):
            content = "\n".join(part.get("text", "") for part in content if isinstance(part, dict))
        translated = content.strip() if isinstance(content, str) else ""
        if strict and (not translated or translated == text or not summary_is_chinese(translated)):
            raise ValueError("接口未返回有效中文译文")
        return translated or text
    except (KeyError, IndexError, TypeError, ValueError, requests.RequestException) as exc:
        if strict:
            raise ValueError("AI 翻译测试失败，请检查接口、密钥、模型及返回的中文译文") from None
        logger.warning("简介中文翻译失败，保留原文：%s", exc)
        return text
