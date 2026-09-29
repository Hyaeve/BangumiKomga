"""Explicit provider selection and expiring server-side previews for manual matching."""
from copy import deepcopy
import secrets
import threading
import time

from api.bangumi_api import BangumiArchiveDataSource
from api.provider_source import ProviderDataSource, native_metadata
from tools.komf_bangumi_metadata import mapped_subject
from tools.komf_matching import eligible
from tools.native_core import core_request
from tools.provider_settings import DEFAULT_PROVIDERS, validate_providers
from tools.record_edit import editable_fields, validate_changes
from tools.task_lock_policy import locked
from tools import workbench

LABELS = {
    "BANGUMI_OFFLINE": "Bangumi 离线库", "MANGA_UPDATES": "MangaUpdates", "MAL": "MyAnimeList",
    "ANILIST": "AniList", "MANGADEX": "MangaDex", "COMIC_VINE": "ComicVine", "MANGA_BAKA": "MangaBaka",
    "BOOK_WALKER": "BookWalker", "YEN_PRESS": "Yen Press", "VIZ": "VIZ", "WEBTOONS": "Webtoons", "EHENTAI": "eHentai",
}
PREVIEWS = {}
PREVIEW_LOCK = threading.RLock()


def context(backend, body):
    scope = workbench.target(backend, body.get("card", ""))
    state = backend._read_state()
    card = next(c for c in state["KOMGA_LIBRARY_LIST"] if str(c.get("LIBRARY")) == scope["library_id"]
                and str(c.get("SERVER_ID") or "") == scope["server_id"])
    client = backend._load_komga(scope["server_id"], require_server=True)
    try:
        item = workbench.checked_item(client, scope["library_id"], body.get("id"))
    finally:
        client.r.close()
    return state, scope, card, item


def provider_config(state, name):
    if name not in LABELS:
        raise ValueError("未知元数据提供商")
    configured = validate_providers(state.get("METADATA_PROVIDERS", DEFAULT_PROVIDERS))
    selected = next((deepcopy(p) for p in configured if p["name"] == name), {"name": name, "priority": 0})
    selected["enabled"] = True  # Only this explicit operation; never persist automatic provider settings.
    return {"providers": [selected], "proxy": state.get("OUTBOUND_PROXY_URL", "")}


def search(backend, body):
    state, scope, card, item = context(backend, body)
    name = body.get("provider", "BANGUMI_OFFLINE")
    if name not in LABELS:
        raise ValueError("未知元数据提供商")
    query = str(body.get("query") or "").strip()
    if not 1 <= len(query) <= 200:
        raise ValueError("请输入 1 至 200 字的搜索名称")
    media = backend.media_type(card)
    if name == "BANGUMI_OFFLINE":
        source = BangumiArchiveDataSource(state.get("ARCHIVE_FILES_DIR", "./archivedata/"))
        if not source.store.ready():
            raise ValueError("Bangumi 离线库尚未就绪，请先在系统设置更新离线库")
        results = [dict(id=str(hit["id"]), title=hit.get("name_cn") or hit.get("name", ""),
                        subtitle=hit.get("name", ""), summary=hit.get("summary", "")[:500])
                   for hit in source._get_search_results_from_archive(query) if eligible(hit, media)][:30]
    else:
        data = core_request("providers.search", {"provider_config": provider_config(state, name),
                            "provider": name, "query": query, "media_type": media}, expected=list)
        if data is None:
            raise ValueError("Go 提供商核心不可用")
        results = [{"id": entry["id"], "title": entry.get("fields", {}).get("title") or
                    next((title["name"] for title in entry.get("titles", []) if title.get("name")), entry["id"]),
                    "subtitle": "", "summary": str(entry.get("fields", {}).get("summary", ""))[:500]}
                   for entry in data[:30]]
    backend._write_activity("工作平台：搜索匹配", f"作品：{item.get('name', '')}\n提供商：{LABELS[name]}\n关键词：{query}\n候选：{len(results)}")
    return {"items": results, "provider": name}


def preview(backend, body):
    state, scope, card, item = context(backend, body)
    name, identity = body.get("provider", "BANGUMI_OFFLINE"), str(body.get("subject_id", ""))
    if name not in LABELS or not identity or len(identity) > 1000:
        raise ValueError("请选择有效的匹配结果")
    if name == "BANGUMI_OFFLINE":
        if not identity.isdigit():
            raise ValueError("Bangumi 条目标识无效")
        source = BangumiArchiveDataSource(state.get("ARCHIVE_FILES_DIR", "./archivedata/"))
        metadata = mapped_subject(source.get_subject_metadata(identity))
        if not eligible(metadata, backend.media_type(card)):
            raise ValueError("条目不属于当前媒体类型或不在离线库中")
    else:
        config = provider_config(state, name)
        data = core_request("providers.get", {"provider_config": config, "provider": name, "provider_id": identity})
        if data is None or (backend.media_type(card) != "mixed" and data.get("media_type") != backend.media_type(card)):
            raise ValueError("条目不可用或不属于当前媒体类型")
        metadata = native_metadata(data)
    if not metadata:
        raise ValueError("无法读取匹配条目的元数据")
    fields = {}
    overwrite = set(card.get("OVERWRITE_FIELDS") or [])
    for field, value in (metadata.get("_provider_fields") or {}).items():
        if field not in editable_fields("series") or value in (None, "", [], {}):
            continue
        if locked(item["metadata"], field):
            continue
        if field not in overwrite and item["metadata"].get(field) not in (None, "", [], {}):
            continue
        try:
            validate_changes({field: value}, "series")
        except ValueError:
            continue
        fields[field] = value
    poster = None
    cover_warning = ""
    if name != "BANGUMI_OFFLINE" and "thumbnail" in overwrite:
        from tools import posters
        client = backend._load_komga(scope["server_id"], require_server=True)
        try:
            if not posters.protected(client, item, "series"):
                thumbnail = ProviderDataSource(None, config["providers"], config["proxy"]).get_subject_thumbnail(metadata, "large")
                if thumbnail:
                    poster = {"after": posters.store(thumbnail["file"][1]),
                              "before": posters.try_capture(client, item["id"], "series")}
        except (ValueError, OSError):
            cover_warning = "封面无法验证，保留当前海报。"
        finally:
            client.r.close()
    token = secrets.token_urlsafe(32)
    with PREVIEW_LOCK:
        now = time.monotonic()
        for key in list(PREVIEWS):
            if PREVIEWS[key]["expires"] < now:
                del PREVIEWS[key]
        if len(PREVIEWS) >= 100:
            del PREVIEWS[next(iter(PREVIEWS))]
        PREVIEWS[token] = {"expires": now + 600, "card": body["card"], "id": item["id"],
                           "provider": name, "subject_id": metadata["id"], "before": item["metadata"],
                           "fields": fields, "poster": poster, "title": metadata.get("name_cn") or metadata["name"]}
    return {"token": token, "title": metadata.get("name_cn") or metadata["name"], "fields": fields,
            "provider": name, "poster": poster["after"] if poster else None,
            "notice": "按媒体卡片覆盖选项写入，已锁定字段跳过；Bangumi 离线库不提供封面。" + cover_warning}


def apply(backend, body):
    with PREVIEW_LOCK, backend.RECORD_EDIT_LOCK:
        entry = PREVIEWS.get(body.get("token"))
        if not entry or entry["expires"] < time.monotonic():
            raise ValueError("匹配预览已过期，请重新搜索")
        _, _, _, current = context(backend, entry)
        if current["metadata"] != entry["before"]:
            raise ValueError("元数据或锁定状态已变化，请重新预览")
        result = workbench.save_item(backend, {
            "card": entry["card"], "id": entry["id"],
            "expected": {**{field: None for field in entry["fields"]}, **entry["before"]}, "changes": entry["fields"],
        }, provider=entry["provider"], source="工作平台：手动刮削匹配", subject_id=str(entry["subject_id"]))
        del PREVIEWS[body["token"]]
        if entry["poster"]:
            from tools import posters
            import base64
            try:
                data, _ = posters.read(entry["poster"]["after"]["id"])
                workbench.save_poster(backend, {
                    "card": entry["card"], "id": entry["id"],
                    "expected": (entry["poster"]["before"] or {}).get("id"), "image": base64.b64encode(data).decode(),
                }, provider=entry["provider"])
                result["poster_url"] = "/api/posters/" + entry["poster"]["after"]["id"]
            except Exception as exc:
                result["warning"] = f"文本元数据已保存，海报未更新：{exc}"
                backend._write_activity("工作平台：匹配海报失败", result["warning"], level="error")
        return result
