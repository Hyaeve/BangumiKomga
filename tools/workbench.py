"""Authenticated, saved-card-scoped workbench operations."""
import hashlib
import json
from contextlib import closing
from urllib.parse import urlencode

from tools.komga_path import item_path
from tools.record_edit import editable_fields, same_value, validate_changes

ACTIONS = {"simplify", "extract_title", "ai_completion", "summary_translation"}


def target(backend, key):
    context = backend._configured_library_context()
    if key not in context or key != f"{context[key]['server_id']}::{context[key]['library_id']}":
        raise ValueError("媒体卡片不存在或已移除")
    return context[key]


def validate_id(item_id):
    if not isinstance(item_id, str) or not item_id or len(item_id) > 200 or any(c in item_id for c in "/\\?#"):
        raise ValueError("无效的作品标识")


def checked_item(client, library_id, item_id):
    validate_id(item_id)
    item = client.get_specific_series(item_id)
    if (not isinstance(item, dict) or str(item.get("id")) != item_id
            or str(item.get("libraryId")) != library_id or item.get("deleted")):
        raise ValueError("作品已删除或不属于所选媒体库")
    if not isinstance(item.get("metadata"), dict):
        raise ValueError("无法读取作品元数据")
    return item


def comparison(item, key):
    metadata = item["metadata"]
    return {
        "workbench": True, "card_key": key,
        "record": {"id": item["id"], "item_title": metadata.get("title") or item.get("name", ""),
                   "source_path": item_path(item)},
        "before": metadata, "after": metadata, "current": metadata,
        "editable_fields": sorted(editable_fields("series")),
        "revision": hashlib.sha256(json.dumps(metadata, sort_keys=True).encode()).hexdigest(),
    }


def read_page(backend, query):
    key = query.get("card", "")
    scope = target(backend, key)
    page = max(0, int(query.get("page", 0)))
    search = str(query.get("q", "")).strip()[:200]
    client = backend._load_komga(scope["server_id"], require_server=True)
    try:
        payload = client.list_library_page(scope["library_id"], page, 48, search)
        # Keep only the current page; never expose service credentials to the browser.
        items = []
        for item in payload.get("content", [])[:48]:
            if str(item.get("libraryId")) != scope["library_id"] or item.get("deleted"):
                continue
            item_id = str(item["id"])
            items.append({"id": item_id, "title": (item.get("metadata") or {}).get("title") or item.get("name", ""),
                          "path": item_path(item),
                          "cover": "/api/workbench/cover?" + urlencode({"card": key, "id": item_id})})
        total = int(payload.get("totalElements", len(items)))
        library_total = total
        if search:
            library_total = int(client.list_library_page(scope["library_id"], 0, 1, "").get("totalElements", 0))
        return {"items": items, "total": total, "library_total": library_total, "page": page, "page_size": 48}
    finally:
        client.r.close()


def read_item(backend, key, item_id):
    scope = target(backend, key)
    client = backend._load_komga(scope["server_id"], require_server=True)
    try:
        return comparison(checked_item(client, scope["library_id"], item_id), key)
    finally:
        client.r.close()


def read_cover(backend, key, item_id):
    from tools.komga_cover import read_series_cover
    scope = target(backend, key)
    client = backend._load_komga(scope["server_id"], require_server=True)
    try:
        checked_item(client, scope["library_id"], item_id)
        return read_series_cover(client, item_id)
    finally:
        client.r.close()


def save_item(backend, body):
    from tools.db import init_sqlite3, record_scrape_event
    scope = target(backend, body.get("card", ""))
    expected = body.get("expected")
    if not isinstance(expected, dict):
        raise ValueError("缺少编辑基准，请重新进入编辑")
    changes = validate_changes(body.get("changes"), "series")
    with backend.RECORD_EDIT_LOCK:
        client = backend._load_komga(scope["server_id"], require_server=True)
        try:
            item = checked_item(client, scope["library_id"], body.get("id"))
            original = item["metadata"]
            for field in changes:
                if field not in expected or any(not same_value(k, original.get(k), expected.get(k))
                                               for k in (field, field + "Lock", field + "Locked")):
                    raise ValueError("元数据或锁定状态已变化，请重新进入编辑")
            changes = {k: v for k, v in changes.items() if not same_value(k, original.get(k), v)}
            if not changes:
                return comparison(item, body["card"])
            if not client.update_series_metadata(item["id"], changes):
                raise ValueError("Komga 写入失败，未更新记录")
            try:
                saved = checked_item(client, scope["library_id"], item["id"])
            except Exception:
                raise ValueError("Komga 已接受修改，但无法回读确认，记录尚未更新，请检查 Komga") from None
            if any(not same_value(k, saved["metadata"].get(k), v) for k, v in changes.items()):
                raise ValueError("Komga 已接受修改，但回读未确认，请检查实际数据")
            if any(saved["metadata"].get(k) != original.get(k) for f in changes for k in (f + "Lock", f + "Locked")):
                raise ValueError("保存期间锁定状态已变化，请检查 Komga")
            try:
                _, conn = init_sqlite3(backend.ROOT / "recordsRefreshed.db")
                with closing(conn):
                    card = next(c for c in backend._read_state()["KOMGA_LIBRARY_LIST"]
                                if str(c.get("LIBRARY")) == scope["library_id"] and str(c.get("SERVER_ID") or "") == scope["server_id"])
                    record_scrape_event(conn, "小说" if backend.media_type(card) == "book" else "漫画",
                                        item.get("name", ""), scope["library_id"], card.get("NAME") or scope["library_id"],
                                        list(changes), source_title=item.get("name", ""),
                                        matched_title=saved["metadata"].get("title", ""),
                                        match_source="工作平台：手动修订", event_kind="series", source_path=item_path(saved),
                                        komga_id=item["id"], server_id=scope["server_id"],
                                        metadata_before=original, metadata_after=saved["metadata"])
            except Exception:
                raise ValueError("Komga 已更新，但本地记录保存失败，请检查存储空间后重新进入编辑") from None
            backend._write_activity("工作平台：手动修订", f"作品：{item.get('name', '')}\n字段：{', '.join(changes)}")
            result = comparison(saved, body["card"])
            result["before"] = original
            return result
        finally:
            client.r.close()


def start_action(backend, body):
    scope = target(backend, body.get("card", ""))
    action, ids = body.get("action"), body.get("ids")
    if action not in ACTIONS or not isinstance(ids, list) or not 1 <= len(ids) <= 200:
        raise ValueError("请选择功能及 1 至 200 本作品")
    if any(not isinstance(i, str) for i in ids):
        raise ValueError("作品标识无效")
    ids = list(dict.fromkeys(ids))
    fields = body.get("fields", [])
    allowed = {"title", "summary", "publisher"} if action == "simplify" else editable_fields("series")
    if action == "extract_title":
        fields = ["title"]
    elif action == "summary_translation":
        fields = ["summary"]
    if not isinstance(fields, list) or not fields or any(not isinstance(f, str) or f not in allowed for f in fields):
        raise ValueError("请选择有效的元数据字段")
    for item_id in ids:
        validate_id(item_id)
    job_id = "workbench-" + backend.secrets.token_hex(8)
    payload = {"card": body["card"], "server_id": scope["server_id"], "library_ids": [scope["library_id"]],
               "series_ids": ids, "fields": fields, "action": action, "ai_completion": True,
               "include_volumes": False, "include_locked": False, "lock_completed": action == "summary_translation"}

    def worker():
        backend._write_activity("工作平台：开始", f"功能：{action}\n媒体库：{scope['library_id']}\n作品：{', '.join(ids)}")
        try:
            module = "services.metadata_task" if action == "ai_completion" else "services.workbench_task"
            backend._run_managed(module, payload)
            backend._write_activity("工作平台：完成", f"功能：{action}\n已处理所选 {len(ids)} 本作品")
        except Exception as exc:
            backend._write_activity("工作平台：失败", f"功能：{action}\n{exc}", level="error")
            raise
    backend.TASK_EXECUTOR.submit(job_id, [body["card"]], worker, timeout_seconds=7200)
    return {"id": job_id, "started": True}
