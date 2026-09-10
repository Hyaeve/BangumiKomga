"""Proxy routing for external metadata providers; Komga is intentionally unchanged."""
import os
from urllib.parse import urlsplit

import requests


def validate_proxy(value):
    value = str(value or "").strip()
    if not value:
        return ""
    try:
        parsed = urlsplit(value)
        if (parsed.scheme not in {"http", "https"} or not parsed.hostname
                or parsed.port == 0 or parsed.path not in {"", "/"}
                or parsed.query or parsed.fragment or any(c.isspace() for c in value)):
            raise ValueError
    except ValueError:
        raise ValueError("代理地址格式无效，请填写 http://主机:端口 或 https://主机:端口") from None
    return value


def proxy_kwargs(url, settings):
    proxy = validate_proxy(settings.get("OUTBOUND_PROXY_URL", ""))
    bypass = os.environ.get("no_proxy") or os.environ.get("NO_PROXY") or ""
    if not proxy or (bypass and requests.utils.should_bypass_proxies(url, no_proxy=bypass)):
        return {}
    return {"proxies": {"http": proxy, "https": proxy}}


def test_proxy(value):
    proxy = validate_proxy(value)
    if not proxy:
        raise ValueError("请先填写代理地址")
    # A fixed destination prevents this test from becoming an arbitrary URL fetcher.
    try:
        with requests.Session() as session:
            session.trust_env = False
            with session.get("https://api.bgm.tv/v0/subjects/1",
                             proxies={"http": proxy, "https": proxy},
                             timeout=(5, 12), stream=True, allow_redirects=False) as response:
                response.raise_for_status()
                if response.status_code != 200:
                    raise ValueError("代理测试失败：目标服务未返回正常响应")
    except requests.RequestException:
        raise ValueError("代理测试失败，请检查代理地址、连通性和认证信息") from None
    return {"ok": True, "message": "代理连接成功"}
