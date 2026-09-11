"""Embedded configuration and control web server for BangumiKomga.

This module intentionally uses only the Python standard library so the Docker
image remains small and the original scraper can still be used unchanged.
"""
from __future__ import annotations

import ast
import hashlib
import hmac
import json
import os
import re
import random
import secrets
import sqlite3
import threading
import time
from contextlib import closing
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse
from tools.komga_path import item_path
from services.media_policy import media_type, scrape_enabled
from services.task_execution import TaskExecutor, TaskStopped, TaskTimedOut, task_time_limit
from tools.task_lock_policy import task_lock_options
from tools.activity_details import config_changes, task_details, target_names
from tools.komga_cover import read_series_cover


ROOT = Path(__file__).resolve().parent
CONFIG_DIR = ROOT / "config"
WEB_DIR = ROOT / "web"
WEB_STATE = CONFIG_DIR / "web_config.json"
DATA_DIR = Path(os.getenv("BANGUMI_KOMGA_DATA_DIR", str(CONFIG_DIR)))
# Credentials intentionally live beside the generated config so the existing
# /app/config volume is the single persistence boundary.
AUTH_STATE = CONFIG_DIR / "web_auth.json"
CONFIG_FILE = CONFIG_DIR / "config.py"
PORT = int(os.getenv("BANGUMI_KOMGA_WEB_PORT", "15600"))

DEFAULTS = {
    "WEB_ADMIN_USERNAME": "admin",
    "WEB_ADMIN_PASSWORD_HASH": "",
    "BANGUMI_ACCESS_TOKEN": "",
    "OPENAI_BASE_URL": "",
    "OPENAI_API_KEY": "",
    "OPENAI_MODEL": "",
    "OUTBOUND_PROXY_URL": "",
    "TRANSLATE_SUMMARY_TO_ZH": False,
    "KOMGA_BASE_URL": "",
    "KOMGA_EMAIL": "",
    "KOMGA_EMAIL_PASSWORD": "",
    "KOMGA_API_KEY": "",
    "KOMGA_SERVERS": [],
    "KOMGA_LIBRARY_LIST": [],
    "AI_RECOGNITION": False,
    "SORT_VOLUMES": False,
    "KOMGA_COLLECTION_LIST": [],
    "USE_BANGUMI_ARCHIVE": False,
    "ARCHIVE_FILES_DIR": "./archivedata/",
    "ARCHIVE_UPDATE_INTERVAL": 168,
    "BANGUMI_KOMGA_SERVICE_TYPE": "sse",
    "BANGUMI_KOMGA_SERVICE_POLL_INTERVAL": 20,
    "BANGUMI_KOMGA_SERVICE_POLL_REFRESH_ALL_METADATA_INTERVAL": 10000,
    "RECORD_RETENTION_DAYS": 30,
    "LOG_RETENTION_DAYS": 30,
    "METADATA_TASKS": [],
    "USE_BANGUMI_THUMBNAIL": False,
    "USE_BANGUMI_THUMBNAIL_FOR_BOOK": False,
    "SORT_TITLE": False,
    "FUZZ_SCORE_THRESHOLD": 80,
    "RECHECK_FAILED_SERIES": False,
    "RECHECK_FAILED_BOOKS": False,
    "CREATE_FAILED_COLLECTION": False,
    "ADD_LOCAL_VERSION": False,
    "NOTIF_TYPE_ENABLE": [],
    "NOTIF_GOTIFY_ENDPOINT": "http://IP:PORT",
    "NOTIF_GOTIFY_TOKEN": "TOKEN",
    "NOTIF_GOTIFY_PRIORITY": 1,
    "NOTIF_GOTIFY_TIMEOUT": 10,
    "NOTIF_WEBHOOK_ENDPOINT": "http://IP:PORT",
    "NOTIF_WEBHOOK_METHOD": "POST",
    "NOTIF_WEBHOOK_HEADER": '{"Content-Type": "application/json"}',
    "NOTIF_WEBHOOK_TIMEOUT": 10,
    "NOTIF_HEALTHCHECKS_ENDPOINT": "http://IP:PORT",
    "NOTIF_HEALTHCHECKS_TIMEOUT": 10,
}

STATE_LOCK = threading.RLock()
TASK_EXECUTOR = TaskExecutor(ROOT)
LOGIN_BACKGROUND_SECRET = secrets.token_bytes(32)


def _run_managed(module, payload):
    TASK_EXECUTOR.run_process(module, payload)


def _stop_task(task_id):
    return TASK_EXECUTOR.stop(task_id)
SESSIONS = set()
PREVIEW_CACHE = {}
PREVIEW_CACHE_FILE = DATA_DIR / "cover_collage_cache.json"
PREVIEW_CACHE_LOCK = threading.RLock()
PREVIEW_CACHE_LOADED = False
LOGIN_PREVIEW_PENDING = set()
LOGIN_PREVIEW_RETRY_AT = {}
TASK_SCHEDULER_STARTED = False
TASK_LAST_RUN = {}
PATH_BACKFILL_LOCK = threading.Lock()
PATH_BACKFILL_ATTEMPTS = {}


def _preview_cache_disk_key(server_id, library_id):
    return json.dumps([str(server_id or ""), str(library_id or "")], ensure_ascii=False)


def _load_preview_cache():
    """Load collage selections once so a process restart does not refresh them."""
    global PREVIEW_CACHE_LOADED
    with PREVIEW_CACHE_LOCK:
        if PREVIEW_CACHE_LOADED:
            return
        PREVIEW_CACHE_LOADED = True
        try:
            payload = json.loads(PREVIEW_CACHE_FILE.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError):
            return
        if not isinstance(payload, dict):
            return
        for disk_key, entry in payload.items():
            try:
                server_id, library_id = json.loads(disk_key)
            except (TypeError, ValueError):
                continue
            if not isinstance(entry, dict) or not isinstance(entry.get("items"), list):
                continue
            items = [item for item in entry["items"] if isinstance(item, dict) and item.get("id") and item.get("url")]
            # Keep an empty selection too: a library with no covers should not
            # trigger a network refresh on every page load.
            PREVIEW_CACHE[(str(server_id), str(library_id))] = {
                "created": float(entry.get("created") or 0),
                "version": str(entry.get("version") or ""),
                "items": items,
            }


def _persist_preview_cache(changed_key):
    from tools.file_lock import exclusive_file_lock
    with PREVIEW_CACHE_LOCK:
        try:
            PREVIEW_CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
            with exclusive_file_lock(PREVIEW_CACHE_FILE.with_suffix(".lock")):
                try:
                    payload = json.loads(PREVIEW_CACHE_FILE.read_text(encoding="utf-8"))
                except (OSError, ValueError):
                    payload = {}
                if not isinstance(payload, dict):
                    payload = {}
                payload[_preview_cache_disk_key(*changed_key)] = PREVIEW_CACHE[changed_key]
                temporary = PREVIEW_CACHE_FILE.with_suffix(".tmp")
                temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
                temporary.replace(PREVIEW_CACHE_FILE)
        except OSError:
            # A read-only data directory should not make preview requests fail.
            pass


def _password_hash(password):
    return hashlib.sha256(password.encode("utf-8")).hexdigest()


def _read_auth():
    with STATE_LOCK:
        state = _read_state()
        if state.get("WEB_ADMIN_USERNAME") and state.get("WEB_ADMIN_PASSWORD_HASH"):
            return {
                "username": state["WEB_ADMIN_USERNAME"],
                "password_hash": state["WEB_ADMIN_PASSWORD_HASH"],
            }
        if CONFIG_FILE.exists():
            try:
                values = ast.parse(CONFIG_FILE.read_text(encoding="utf-8"))
                found = {
                    node.targets[0].id: ast.literal_eval(node.value)
                    for node in values.body
                    if isinstance(node, ast.Assign)
                    and len(node.targets) == 1
                    and isinstance(node.targets[0], ast.Name)
                    and node.targets[0].id in {"WEB_ADMIN_USERNAME", "WEB_ADMIN_PASSWORD_HASH"}
                }
                if found.get("WEB_ADMIN_USERNAME") and found.get("WEB_ADMIN_PASSWORD_HASH"):
                    return {"username": found["WEB_ADMIN_USERNAME"], "password_hash": found["WEB_ADMIN_PASSWORD_HASH"]}
            except (OSError, ValueError, SyntaxError):
                pass
        return {"username": "admin", "password_hash": _password_hash("password")}


def _save_auth(username, password):
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    data = {"username": username, "password_hash": _password_hash(password)}
    state = _read_state()
    state["WEB_ADMIN_USERNAME"] = username
    state["WEB_ADMIN_PASSWORD_HASH"] = data["password_hash"]
    _write_config(state)
    return {"username": username}


def _read_state() -> dict:
    with STATE_LOCK:
        config_values = {}
        if CONFIG_FILE.exists():
            try:
                tree = ast.parse(CONFIG_FILE.read_text(encoding="utf-8"))
                for node in tree.body:
                    if (isinstance(node, ast.Assign) and len(node.targets) == 1
                            and isinstance(node.targets[0], ast.Name)
                            and node.targets[0].id in DEFAULTS):
                        config_values[node.targets[0].id] = ast.literal_eval(node.value)
            except (OSError, ValueError, SyntaxError):
                config_values = {}
        if WEB_STATE.exists():
            try:
                data = json.loads(WEB_STATE.read_text(encoding="utf-8"))
                merged = {**DEFAULTS, **config_values, **data}
                for key in ("WEB_ADMIN_USERNAME", "WEB_ADMIN_PASSWORD_HASH"):
                    if config_values.get(key):
                        merged[key] = config_values[key]
                return merged
            except (OSError, ValueError):
                pass
        return {**DEFAULTS, **config_values}


def _python_value(value):
    if isinstance(value, bool):
        return "True" if value else "False"
    if value is None:
        return "None"
    return repr(value)


def _write_config(data: dict):
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    lines = ["# Generated by BangumiKomga Web UI. Edit via the Web UI when possible.", ""]
    for key, default in DEFAULTS.items():
        lines.append(f"{key} = {_python_value(data.get(key, default))}")
    CONFIG_FILE.write_text("\n".join(lines) + "\n", encoding="utf-8")


def save_state(data: dict) -> dict:
    merged = {**DEFAULTS, **data}
    from tools.proxy_settings import validate_proxy
    merged["OUTBOUND_PROXY_URL"] = validate_proxy(merged.get("OUTBOUND_PROXY_URL"))
    try:
        merged["RECORD_RETENTION_DAYS"] = max(1, min(int(merged.get("RECORD_RETENTION_DAYS", 30)), 365))
    except (TypeError, ValueError):
        merged["RECORD_RETENTION_DAYS"] = 30
    try:
        merged["LOG_RETENTION_DAYS"] = max(1, min(int(merged.get("LOG_RETENTION_DAYS", 30)), 365))
    except (TypeError, ValueError):
        merged["LOG_RETENTION_DAYS"] = 30
    servers = []
    for item in merged.get("KOMGA_SERVERS", []) or []:
        if not item.get("base_url") or not item.get("name"):
            continue
        servers.append({
            "id": str(item.get("id") or secrets.token_hex(8)),
            "name": str(item["name"]).strip(),
            "base_url": str(item["base_url"]).strip().rstrip("/"),
            "email": str(item.get("email", "")).strip(),
            "password": str(item.get("password", "")),
            "api_key": str(item.get("api_key", "")),
            "auth_mode": "key" if item.get("auth_mode") == "key" or item.get("api_key") else "password",
        })
        if servers[-1]["auth_mode"] == "key":
            servers[-1]["email"] = ""
            servers[-1]["password"] = ""
        else:
            servers[-1]["api_key"] = ""
    merged["KOMGA_SERVERS"] = servers
    if servers:
        primary = servers[0]
        merged["KOMGA_BASE_URL"] = primary["base_url"]
        merged["KOMGA_EMAIL"] = primary["email"]
        merged["KOMGA_EMAIL_PASSWORD"] = primary["password"]
        merged["KOMGA_API_KEY"] = primary["api_key"]
    # Normalize card values and keep the config file safe to import.
    libraries = []
    for item in merged.get("KOMGA_LIBRARY_LIST", []) or []:
        if not item.get("LIBRARY"):
            continue
        libraries.append({
            "LIBRARY": str(item["LIBRARY"]),
            "SERVER_ID": str(item.get("SERVER_ID", "")),
            "IS_NOVEL_ONLY": media_type(item) == "book",
            "MEDIA_TYPE": media_type(item),
            "SCRAPE_ENABLED": scrape_enabled(item),
            "LOGIN_BACKGROUND": bool(item.get("LOGIN_BACKGROUND", False)),
            "REQUIRED_FIELDS": list(item.get("REQUIRED_FIELDS", []) or []),
            "OVERWRITE_FIELDS": list(item.get("OVERWRITE_FIELDS", []) or []),
            "TRANSLATE_SUMMARY_TO_ZH": False,
            "AI_RECOGNITION": bool(item.get("AI_RECOGNITION", False)),
            "SORT_VOLUMES": bool(item.get("SORT_VOLUMES", False)),
        })
    merged["KOMGA_LIBRARY_LIST"] = libraries
    merged["KOMGA_COLLECTION_LIST"] = [
        {"COLLECTION": str(x["COLLECTION"]), "IS_NOVEL_ONLY": bool(x.get("IS_NOVEL_ONLY", False)),
         "REQUIRED_FIELDS": list(x.get("REQUIRED_FIELDS", []) or []),
         "OVERWRITE_FIELDS": list(x.get("OVERWRITE_FIELDS", []) or [])}
        for x in (merged.get("KOMGA_COLLECTION_LIST", []) or []) if x.get("COLLECTION")
    ]
    merged["METADATA_TASKS"] = [
        {
            "id": str(item.get("id") or secrets.token_hex(6)),
            "name": str(item.get("name") or "元数据补全"),
            "type": str(item.get("type") or ((item.get("functions") or ["metadata_completion"])[0])),
            "functions": [str(value) for value in (item.get("functions") or ([item.get("type")] if item.get("type") else []))],
            "fields": [str(field) for field in (item.get("fields") or [])],
            "operations": [str(value) for value in (item.get("operations") or []) if value != "include_locked"],
            "ai_completion": bool(item.get("ai_completion", False)),
            **task_lock_options(item),
            "card_ids": [str(card_id) for card_id in (item.get("card_ids") or [])],
            "cron": str(item.get("cron") or "0 6 * * *").strip(),
            "time_limit_hours": task_time_limit(item.get("time_limit_hours", 0)),
            "schedule": str(item.get("schedule") or item.get("cron") or "0 6 * * *").strip(),
            "enabled": bool(item.get("enabled", True)),
            "last_run": str(item.get("last_run") or ""),
        }
        for item in (merged.get("METADATA_TASKS") or [])
    ]
    with STATE_LOCK:
        WEB_STATE.write_text(json.dumps(merged, ensure_ascii=False, indent=2), encoding="utf-8")
        _write_config(merged)
    return merged


def _load_komga(server_id=None):
    state = _read_state()
    if server_id:
        for server in state.get("KOMGA_SERVERS", []) or []:
            if server.get("id") == server_id:
                from api.komga_api import KomgaApi
                if not server.get("api_key") and (not server.get("email") or not server.get("password")):
                    raise ValueError("请填写 Komga 账号密码或 API 密钥")
                return KomgaApi(server["base_url"], server.get("email", ""), server.get("password", ""), server.get("api_key") or None)
    if not state.get("KOMGA_BASE_URL"):
        raise ValueError("请先保存 Komga 地址")
    if not state.get("KOMGA_API_KEY") and (not state.get("KOMGA_EMAIL") or not state.get("KOMGA_EMAIL_PASSWORD")):
        raise ValueError("请填写 Komga 账号密码或 API 密钥")
    from api.komga_api import KomgaApi
    return KomgaApi(state["KOMGA_BASE_URL"], state.get("KOMGA_EMAIL", ""), state.get("KOMGA_EMAIL_PASSWORD", ""), state.get("KOMGA_API_KEY") or None)


def _manual_refresh_targets(target_ids, full):
    context = _configured_library_context()
    grouped = {}
    for key in target_ids:
        target = context.get(str(key))
        if not target:
            raise ValueError("所选媒体卡片不存在")
        grouped.setdefault(target["server_id"], set()).add(target["library_id"])
    if not grouped:
        raise ValueError("请先添加媒体卡片")
    for server_id, libraries in grouped.items():
        _run_managed("services.media_refresh", {"server_id": server_id, "library_ids": sorted(libraries), "full": full})


def _start_refresh(full=False, library_ids=None, target_id=None):
    context = _configured_library_context()
    targets = [target_id] if target_id else [key for key in context if "::" in key]
    if library_ids and not target_id:
        targets = [key for key in targets if context[key]["library_id"] in library_ids]
    if not targets or any(key not in context for key in targets):
        raise ValueError("所选媒体卡片不存在")
    def worker():
        started = time.monotonic()
        details = f"方式：{'全量刮削' if full else '增量刮削'}\n应用媒体库：{target_names(targets, _read_state())}"
        try:
            _write_activity("手动刮削：开始", details)
            _manual_refresh_targets(targets, full)
            _write_activity("手动刮削：完成", details + f"\n耗时：{time.monotonic()-started:.1f} 秒")
            return "full" if full else "incremental"
        except TaskStopped:
            _write_activity("手动刮削：停止", details + "\n结果：已停止，已完成的修改保留")
            raise
        except Exception as exc:  # pragma: no cover - surfaced through API
            _write_activity("手动刮削：失败", details + f"\n错误：{exc}", level="error")
            raise
    return TASK_EXECUTOR.submit("manual:" + "|".join(sorted(targets)), targets, worker)


def _refresh_card_collages(library_ids):
    context = _configured_library_context()
    targets = []
    for target_id in library_ids or []:
        target_key = str(target_id)
        item = context.get(target_key)
        if item:
            targets.append((item.get("library_id") or target_key.split("::", 1)[-1], item["server_id"]))
    if not targets:
        raise ValueError("计划任务没有可刷新的媒体库")
    for library_id, server_id in targets:
        from tools.execution_outcomes import record_outcome
        os.environ["BANGUMI_EXECUTION_SERVER"] = server_id
        try:
            _preview_items(server_id, library_id, force=True)
            record_outcome("collage", library_id)
        except Exception:
            record_outcome("collage", library_id, failed=True)
            raise
        _write_activity("计划任务：拼贴刷新", f"刷新媒体库 {library_id} 的封面拼贴")


def _task_library_ids(target_ids):
    context = _configured_library_context()
    resolved = []
    for target_id in target_ids or []:
        item = context.get(str(target_id))
        library_id = item.get("library_id") if item else str(target_id).split("::", 1)[-1]
        if library_id and library_id not in resolved:
            resolved.append(library_id)
    return resolved


def _start_task(task):
    """Different libraries run concurrently; overlapping targets queue FIFO."""
    functions = {str(value) for value in (task.get("functions") or [task.get("type") or "metadata_completion"])}
    target_ids = [str(value) for value in (task.get("card_ids") or [])]

    def worker():
        started = time.monotonic()
        details = task_details(task, _read_state())
        try:
            _write_activity("计划任务：开始处理", details)
            result_labels = []
            if "metadata_completion" in functions:
                _complete_task_libraries(target_ids, task)
                result_labels.append("incremental")
            if "metadata_correction" in functions:
                _run_managed("services.task_worker", {"function": "metadata_correction", "task": task})
                result_labels.append("metadata_correction")
            if "summary_translation" in functions:
                _run_managed("services.task_worker", {"function": "summary_translation", "task": task})
                result_labels.append("summary_translation")
            if "card_collage_refresh" in functions:
                _run_managed("services.task_worker", {"function": "card_collage_refresh", "task": task})
                with PREVIEW_CACHE_LOCK:
                    global PREVIEW_CACHE_LOADED
                    PREVIEW_CACHE.clear()
                    PREVIEW_CACHE_LOADED = False
                result_labels.append("card_collage")
            _write_activity("计划任务：完成", details + f"\n结果：执行完成\n耗时：{time.monotonic()-started:.1f} 秒")
            return "+".join(result_labels) or "task"
        except TaskTimedOut:
            _write_activity("计划任务：超时停止", details + f"\n结果：达到时间限制，已停止；已完成的修改保留\n耗时：{time.monotonic()-started:.1f} 秒", level="error")
            raise
        except TaskStopped:
            _write_activity("计划任务：停止", details + f"\n结果：已停止，已完成的修改保留\n耗时：{time.monotonic()-started:.1f} 秒")
            raise
        except Exception as exc:  # pragma: no cover - surfaced through API
            _write_activity("计划任务：失败", details + f"\n错误：{exc}\n耗时：{time.monotonic()-started:.1f} 秒", level="error")
            raise
    context = _configured_library_context()
    targets = [f"{context[key]['server_id']}::{context[key]['library_id']}"
               if key in context else key for key in target_ids]
    return TASK_EXECUTOR.submit(str(task["id"]), targets, worker,
                                timeout_seconds=task_time_limit(task.get("time_limit_hours", 0)) * 3600)


def _complete_task_libraries(target_ids, task):
    context = _configured_library_context()
    grouped = {}
    if not task.get("fields"):
        raise ValueError("请选择补全元数据")
    for key in target_ids:
        target = context.get(str(key))
        if not target:
            raise ValueError(f"计划任务的媒体库不存在：{key}")
        grouped.setdefault(target["server_id"], []).append(target["library_id"])
    if not grouped:
        raise ValueError("请选择应用媒体库")
    for server_id, library_ids in grouped.items():
        request = {"server_id": server_id, "library_ids": library_ids,
                   "fields": task["fields"], "ai_completion": bool(task.get("ai_completion")),
                   **task_lock_options(task)}
        # Isolate imported scraper configuration between Komga services.
        _run_managed("services.metadata_task", request)


def _translate_task_libraries(target_ids, fields=None, correction=None, include_locked=False, lock_completed=None):
    from tools.translation_task import translate_library
    from tools.db import init_sqlite3, record_scrape_event
    action = "元数据修正" if correction is not None else "AI翻译"

    state = _read_state()
    context = _configured_library_context()
    targets = []
    for key in target_ids:
        target = context.get(str(key))
        if not target:
            raise ValueError(f"计划任务的媒体库不存在：{key}")
        targets.append(target)
    if not targets:
        raise ValueError("请选择应用媒体库")
    _, conn = init_sqlite3(ROOT / "recordsRefreshed.db")
    failures = 0
    try:
        for target in targets:
            library_id, server_id = target["library_id"], target["server_id"]
            if os.environ.get("BANGUMI_EXECUTION_ID"):
                os.environ["BANGUMI_EXECUTION_SERVER"] = server_id
            komga = _load_komga(server_id)
            libraries = komga.list_libraries()
            library_name = next((item.get("name") for item in libraries if str(item.get("id")) == library_id), library_id)
            card = next((item for item in state.get("KOMGA_LIBRARY_LIST", []) if str(item.get("LIBRARY")) == library_id and str(item.get("SERVER_ID") or "") == server_id), {})

            def record(item, kind, source_title, fields):
                record_scrape_event(
                    conn, "小说" if card.get("IS_NOVEL_ONLY") else "漫画",
                    item.get("name") or "", library_id, library_name, fields,
                    source_title=source_title, match_source=f"计划任务：{action}",
                    event_kind=kind, source_path=str(item.get("url") or ""),
                    komga_id=item["id"], server_id=server_id,
                )

            log = lambda detail, level: _write_activity(f"计划任务：{action}", detail, level=level)
            try:
                if correction is not None:
                    from tools.correction_task import correct_library
                    counts = correct_library(komga, library_id, state, record, log, fields, correction,
                                             only_novel=media_type(card), include_locked=include_locked,
                                             lock_completed=bool(lock_completed))
                else:
                    counts = translate_library(komga, library_id, state, record, log, fields=fields,
                                               include_locked=include_locked,
                                               lock_completed=True if lock_completed is None else lock_completed)
            finally:
                komga.r.close()
            failures += counts["failed"]
            _write_activity(f"计划任务：{action}", f"{target['server_name']} / {library_name}：更新 {counts['updated']} 项目，跳过 {counts['skipped']} 项目，失败 {counts['failed']} 字段")
    finally:
        conn.close()
    if failures:
        raise ValueError(f"{failures} 项元数据翻译或写入失败，已保留原文，详见运行日志")


def _cron_value(token, minimum, maximum):
    token = token.strip().upper()
    aliases = {"SUN": 0, "MON": 1, "TUE": 2, "WED": 3, "THU": 4, "FRI": 5, "SAT": 6}
    if token in aliases:
        return aliases[token]
    value = int(token)
    if not minimum <= value <= maximum:
        raise ValueError("Cron 值超出范围")
    return value


def _cron_field_matches(value, expression, minimum, maximum):
    expression = expression.strip()
    if not expression:
        return False
    allowed = set()
    for item in expression.split(","):
        item = item.strip()
        if not item:
            return False
        base, separator, step_text = item.partition("/")
        try:
            step = int(step_text) if separator else 1
            if step <= 0:
                return False
            if base in ("", "*", "?"):
                start, end = minimum, maximum
            elif "-" in base:
                start_text, end_text = base.split("-", 1)
                start = _cron_value(start_text, minimum, maximum)
                end = _cron_value(end_text, minimum, maximum)
            else:
                start = end = _cron_value(base, minimum, maximum)
            if start > end:
                return False
            allowed.update(range(start, end + 1, step))
        except (TypeError, ValueError):
            return False
    return value in allowed


def _cron_matches(expression, now=None):
    """Match a standard five-field local-time cron expression."""
    parts = str(expression or "").split()
    if len(parts) != 5:
        return False
    current = now or datetime.now()
    minute, hour, day, month, weekday = parts
    day_match = _cron_field_matches(current.day, day, 1, 31)
    month_match = _cron_field_matches(current.month, month, 1, 12)
    weekday_match = _cron_field_matches((current.weekday() + 1) % 7, weekday, 0, 7)
    # Standard cron treats 0 and 7 as Sunday. Normalize 7 in the matcher.
    if current.weekday() == 6 and _cron_field_matches(7, weekday, 0, 7):
        weekday_match = current.weekday() == 6
    day_of_month_wild = day.strip() in ("*", "?")
    day_of_week_wild = weekday.strip() in ("*", "?")
    if day_of_month_wild or day_of_week_wild:
        day_match = day_match and weekday_match
    else:
        day_match = day_match or weekday_match
    return (
        _cron_field_matches(current.minute, minute, 0, 59)
        and _cron_field_matches(current.hour, hour, 0, 23)
        and month_match
        and day_match
    )


def _task_scheduler_loop():
    while True:
        try:
            now = datetime.now()
            minute_key = now.strftime("%Y%m%d%H%M")
            for task in _read_state().get("METADATA_TASKS", []) or []:
                task_id = str(task.get("id") or "")
                cron = str(task.get("cron") or "0 6 * * *").strip()
                functions = {str(value) for value in (task.get("functions") or [task.get("type") or "metadata_completion"])}
                if not task_id or not task.get("enabled", True) or not cron or not _cron_matches(cron, now):
                    continue
                if TASK_LAST_RUN.get(task_id) == minute_key:
                    continue
                if _start_task(task):
                    TASK_LAST_RUN[task_id] = minute_key
                    _write_activity("计划任务：自动执行", "触发方式：Cron 定时触发\n" + task_details(task, _read_state()))
        except Exception as exc:  # pragma: no cover - scheduler is best effort
            try:
                _write_activity("计划任务：调度失败", str(exc), level="error")
            except Exception:
                pass
        time.sleep(20)


def _start_task_scheduler():
    global TASK_SCHEDULER_STARTED
    if TASK_SCHEDULER_STARTED:
        return
    TASK_SCHEDULER_STARTED = True
    threading.Thread(target=_task_scheduler_loop, name="TaskScheduler", daemon=True).start()


def _configured_library_context():
    state = _read_state()
    servers = {
        str(server.get("id")): server.get("name") or "Komga 服务"
        for server in (state.get("KOMGA_SERVERS") or [])
        if server.get("id")
    }
    result = {}
    legacy_ids = {}
    for item in (state.get("KOMGA_LIBRARY_LIST") or []):
        library_id = str(item.get("LIBRARY") or "")
        server_id = str(item.get("SERVER_ID") or "")
        if not library_id:
            continue
        value = {
            "library_id": library_id,
            "server_id": str(item.get("SERVER_ID") or ""),
            "server_name": servers.get(str(item.get("SERVER_ID") or ""), "默认 Komga 服务"),
        }
        result[f"{server_id}::{library_id}"] = value
        legacy_ids.setdefault(library_id, []).append(value)
    for library_id, values in legacy_ids.items():
        # Scrape records historically stored only a library ID. Preserve a
        # display context for those rows while new task targets use the exact
        # server::library key.
        result[library_id] = values[0]
    return result


def _read_scrape_rows(record_ids=None):
    """Read raw events and include the newer series/volume marker."""
    db_file = ROOT / "recordsRefreshed.db"
    if not db_file.exists():
        return []
    try:
        context = _configured_library_context()
        ids = sorted({item["library_id"] for item in context.values()})
        if not ids:
            return []
        _cleanup_expired_records()
        with closing(sqlite3.connect(db_file)) as conn:
            columns = {row[1] for row in conn.execute("PRAGMA table_info(scrape_records)").fetchall()}
            placeholders = ",".join("?" for _ in ids)
            source_sql = ",source_title,matched_title,match_source" if {"source_title", "matched_title", "match_source"}.issubset(columns) else ",'' AS source_title,item_title AS matched_title,'' AS match_source"
            kind_sql = ",event_kind" if "event_kind" in columns else ",'volume' AS event_kind"
            path_sql = ",source_path" if "source_path" in columns else ",'' AS source_path"
            identity_sql = (",komga_id" if "komga_id" in columns else ",''") + (",server_id" if "server_id" in columns else ",''")
            selection = ""
            if record_ids is not None:
                if not record_ids:
                    return []
                selection = " AND id IN (" + ",".join("?" for _ in record_ids) + ")"
                ids.extend(record_ids)
            rows = conn.execute("SELECT id,item_type,item_title,library_id,library_name,metadata_fields,status,recorded_at" + source_sql + kind_sql + path_sql + identity_sql + " FROM scrape_records WHERE library_id IN (" + placeholders + ")" + selection + " ORDER BY id DESC", ids).fetchall()
        return [{
            "id": row[0], "item_type": row[1], "item_title": row[2], "library_id": row[3], "library_name": row[4],
            "server_id": row[14] or context.get(str(row[3]), {}).get("server_id", ""),
            "server_name": context.get(f"{row[14]}::{row[3]}" if row[14] else str(row[3]), {}).get("server_name", "默认 Komga 服务"),
            "komga_id": row[13] or "", "record_server_id": row[14] or "",
            "metadata_fields": [field for field in (row[5] or "").split(",") if field], "status": row[6], "recorded_at": row[7],
            "source_title": row[8] or row[2], "matched_title": row[9] or row[2], "match_source": row[10] or "", "event_kind": row[11] or "volume", "source_path": row[12] or "",
        } for row in rows if not row[14] or f"{row[14]}::{row[3]}" in context]
    except (OSError, sqlite3.Error, IndexError):
        return []


def _is_series_scrape_row(row):
    if str(row.get("event_kind") or "").lower() == "series":
        return True
    # Fallback for records written before event_kind was added.
    return bool(set(row.get("metadata_fields") or ()) & {
        "publisher", "genres", "alternateTitles", "ageRating",
        "totalBookCount", "language", "titleSort", "status",
    })


def _group_scrape_records(rows):
    groups = {}
    for row in rows:
        title = str(row.get("source_title") or row.get("item_title") or "").strip()
        key = (str(row.get("server_id") or ""), str(row.get("library_id") or ""), str(row.get("item_type") or ""), title.casefold())
        groups.setdefault(key, []).append(row)
    result = []
    for rows_for_book in groups.values():
        primary_index = next((i for i, row in enumerate(rows_for_book) if _is_series_scrape_row(row)), 0)
        primary = dict(rows_for_book[primary_index])
        details = [dict(row) for i, row in enumerate(rows_for_book) if i != primary_index]
        fields = []
        for row in rows_for_book:
            for field in row.get("metadata_fields") or []:
                if field not in fields:
                    fields.append(field)
        primary["id"] = f"book:{primary.get('library_id', '')}:{primary.get('id', '')}"
        primary["recorded_at"] = max((str(row.get("recorded_at") or "") for row in rows_for_book), default=primary.get("recorded_at", ""))
        primary["metadata_fields"] = fields
        primary["volumes"] = [{
            "id": row.get("id"), "item_title": row.get("item_title") or row.get("source_title") or "",
            "matched_title": row.get("matched_title") or row.get("item_title") or "", "metadata_fields": row.get("metadata_fields") or [],
            "status": row.get("status") or "success", "recorded_at": row.get("recorded_at") or "", "match_source": row.get("match_source") or "",
            "source_path": row.get("source_path") or "",
            "komga_id": row.get("komga_id") or "", "record_server_id": row.get("record_server_id") or "",
            "source_title": row.get("source_title") or "",
        } for row in details]
        primary["source_path"] = primary.get("source_path") or next((row.get("source_path") for row in rows_for_book if row.get("source_path")), "")
        primary["volume_count"] = len(primary["volumes"])
        primary["record_count"] = len(rows_for_book)
        result.append(primary)
    return sorted(result, key=lambda row: str(row.get("recorded_at") or ""), reverse=True)


def _scrape_page_query(search=""):
    """Group and filter in SQLite, not in the web server's Python heap."""
    context = {key: value for key, value in _configured_library_context().items() if "::" in key}
    if not context:
        return None, []
    conn = sqlite3.connect(ROOT / "recordsRefreshed.db")
    try:
        columns = {row[1] for row in conn.execute("PRAGMA table_info(scrape_records)")}
    finally:
        conn.close()
    if not columns:
        return None, []
    params = []
    for item in context.values():
        params.extend([item["server_id"], item["library_id"], item["server_name"]])
    server = "COALESCE(r.server_id,'')" if "server_id" in columns else "''"
    title = "COALESCE(NULLIF(r.source_title,''),r.item_title)" if "source_title" in columns else "r.item_title"
    path = "COALESCE(r.source_path,'')" if "source_path" in columns else "''"
    kind = "r.event_kind" if "event_kind" in columns else "''"
    query = f"""WITH configured(sid,lid,sname) AS (VALUES {','.join('(?,?,?)' for _ in context)}),
        base AS (
            SELECT r.id,r.item_type,r.recorded_at,r.metadata_fields,r.library_name,
                c.sid,c.lid,c.sname,{title} AS title,{path} AS path,{kind} AS kind,
                ROW_NUMBER() OVER (PARTITION BY r.id ORDER BY c.sid) AS duplicate
            FROM scrape_records r JOIN configured c ON r.library_id=c.lid
                AND ({server}='' OR {server}=c.sid)
        ), unique_rows AS (SELECT * FROM base WHERE duplicate=1),
        grouped AS (
            SELECT sid,lid,item_type,LOWER(title) AS title_key,MAX(recorded_at) AS recorded_at,
                MAX(id) AS latest_id,COUNT(*) AS record_count
            FROM unique_rows GROUP BY sid,lid,item_type,LOWER(title)
            HAVING MAX(CASE WHEN title LIKE ? OR library_name LIKE ? OR sname LIKE ?
                OR path LIKE ? OR metadata_fields LIKE ? THEN 1 ELSE 0 END)=1
        ) """
    params.extend([f"%{search}%"] * 5)
    return query, params


def _read_scrape_records(limit=50, offset=0, search="", newest=True, with_total=False):
    limit = max(1, min(int(limit), 50))
    offset = max(0, int(offset))
    _cleanup_expired_records()
    query, params = _scrape_page_query(search)
    if not query:
        return {"items": [], "total": 0} if with_total else []
    direction = "DESC" if newest else "ASC"
    with closing(sqlite3.connect(ROOT / "recordsRefreshed.db")) as conn:
        total = conn.execute(query + "SELECT COUNT(*) FROM grouped", params).fetchone()[0]
        page_groups = conn.execute(query + f"""SELECT sid,lid,item_type,title_key,recorded_at,record_count
            FROM grouped ORDER BY recorded_at {direction},latest_id {direction} LIMIT ? OFFSET ?""",
                                   [*params, limit, offset]).fetchall()
        # Bound expanded details as well as top-level rows. Older details are
        # available through their own per-book paging endpoint.
        rows = conn.execute(query + f""", page AS (
            SELECT * FROM grouped ORDER BY recorded_at {direction},latest_id {direction} LIMIT ? OFFSET ?
        ), ranked AS (
            SELECT u.id,ROW_NUMBER() OVER (
                PARTITION BY u.sid,u.lid,u.item_type,LOWER(u.title)
                ORDER BY (u.kind='series') DESC,u.id DESC) AS position
            FROM unique_rows u JOIN page p ON u.sid=p.sid AND u.lid=p.lid
                AND u.item_type=p.item_type AND LOWER(u.title)=p.title_key
        ) SELECT id FROM ranked WHERE position<=51""", [*params, limit, offset]).fetchall()
    visible = _group_scrape_records(_read_scrape_rows([row[0] for row in rows]))
    for record in visible:
        key = (record["server_id"], record["library_id"], record["item_type"], record["source_title"].lower())
        group = next((item for item in page_groups if item[:4] == key), None)
        if group:
            record.update(recorded_at=group[4], record_count=group[5], volume_count=group[5]-1, volume_offset=0)
    visible.sort(key=lambda row: (row["recorded_at"], row["id"]), reverse=newest)
    _schedule_path_backfill(visible)
    return {"items": visible, "total": total} if with_total else visible


def _read_record_details(record_id, offset=0):
    query, params = _scrape_page_query()
    if not query:
        return {"items": [], "total": 0}
    primary_id = int(str(record_id).rsplit(":", 1)[-1])
    with closing(sqlite3.connect(ROOT / "recordsRefreshed.db")) as conn:
        clause = """ FROM unique_rows u JOIN unique_rows p ON p.id=?
            AND u.sid=p.sid AND u.lid=p.lid AND u.item_type=p.item_type
            AND LOWER(u.title)=LOWER(p.title) WHERE u.id<>p.id"""
        total = conn.execute(query + "SELECT COUNT(*)" + clause, [*params, primary_id]).fetchone()[0]
        rows = conn.execute(query + "SELECT u.id" + clause + " ORDER BY u.id DESC LIMIT 50 OFFSET ?",
                            [*params, primary_id, max(0, offset)]).fetchall()
    items = _read_scrape_rows([row[0] for row in rows])
    _schedule_path_backfill(items)
    return {"items": items, "total": total}


def _backfill_source_paths(records):
    """Recover old rows using recorded Komga IDs, never invent filesystem paths."""
    db_file = ROOT / "recordsRefreshed.db"
    configured = _configured_library_context()
    with closing(sqlite3.connect(db_file)) as conn:
        tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        columns = {row[1] for row in conn.execute("PRAGMA table_info(scrape_records)")}
        if "source_path" not in columns:
            conn.execute("ALTER TABLE scrape_records ADD COLUMN source_path TEXT")
        clients = {}
        for row in records:
            server_id = row.get("server_id", "")
            library_id = str(row.get("library_id") or "")
            servers = {value["server_id"] for value in configured.values() if value["library_id"] == library_id}
            if len(servers) > 1 and not row.get("record_server_id"):
                continue
            kind = "series" if _is_series_scrape_row(row) else "volume"
            table, id_column, name_column = ("refreshed_series", "series_id", "series_name") if kind == "series" else ("refreshed_books", "book_id", "book_name")
            name = (row.get("source_title") or row.get("item_title")) if kind == "series" else row.get("item_title")
            ids = [(row["komga_id"],)] if row.get("komga_id") else (
                conn.execute(f"SELECT {id_column} FROM {table} WHERE {name_column}=? LIMIT 2", (name,)).fetchall()
                if table in tables else [])
            try:
                if server_id not in clients:
                    clients[server_id] = _load_komga(server_id)
                komga = clients[server_id]
                if len(ids) != 1:
                    item = _find_legacy_record_item(komga, row, kind)
                    ids = [(item["id"],)] if item else []
                if len(ids) != 1:
                    continue
                item = (komga.get_specific_series if kind == "series" else komga.get_specific_book)(ids[0][0])
                if not isinstance(item, dict) or str(item.get("libraryId")) != library_id:
                    continue
                path = item_path(item)
                if not path:
                    continue
                event_id = str(row["id"]).rsplit(":", 1)[-1]
                conn.execute("UPDATE scrape_records SET source_path=? WHERE id=? AND COALESCE(source_path,'')=''", (path, event_id))
                conn.commit()
            except Exception as exc:
                _write_activity("记录：路径回填", f"{name}：{exc}", level="warning")


def _find_legacy_record_item(komga, row, kind):
    """Recover renamed legacy entries only when an exact match is unique."""
    title = str(row.get("source_title") or row.get("item_title") or "")
    series_matches = []
    for series in komga.iter_library_series(row["library_id"]):
        if title in (series.get("name"), (series.get("metadata") or {}).get("title")):
            series_matches.append(series)
            if len(series_matches) > 1:
                return None
    if len(series_matches) != 1:
        return None
    if kind == "series":
        return series_matches[0]
    names = {row.get("item_title"), row.get("matched_title")} - {None, ""}
    matches = []
    for book in komga.iter_series_books(series_matches[0]["id"]):
        if names.intersection((book.get("name"), (book.get("metadata") or {}).get("title"))):
            matches.append(book)
            if len(matches) > 1:
                return None
    return matches[0] if matches else None


def _schedule_path_backfill(records):
    if not PATH_BACKFILL_LOCK.acquire(blocking=False):
        return
    pending = []
    now = time.monotonic()
    for record in records:
        for row in [record, *[
            {**volume, "event_kind": "volume", "server_id": record.get("server_id"), "library_id": record.get("library_id")}
            for volume in record.get("volumes", [])
        ]]:
            if not row.get("source_path") and now - PATH_BACKFILL_ATTEMPTS.get(str(row["id"]), -1000) >= 300:
                pending.append(row)
                if len(pending) >= 20:
                    break
        if len(pending) >= 20:
            break
    if not pending:
        PATH_BACKFILL_LOCK.release()
        return
    if len(PATH_BACKFILL_ATTEMPTS) > 1000:
        PATH_BACKFILL_ATTEMPTS.clear()
    for row in pending:
        PATH_BACKFILL_ATTEMPTS[str(row["id"])] = now

    def worker():
        try:
            _backfill_source_paths(pending)
        except (OSError, sqlite3.Error) as exc:
            _write_activity("记录：路径回填", str(exc), level="warning")
        finally:
            PATH_BACKFILL_LOCK.release()

    threading.Thread(target=worker, name="RecordPathBackfill", daemon=True).start()


def _read_scrape_stats():
    query, params = _scrape_page_query()
    if not query:
        return dict(total=0, today=0, comic=0, novel=0)
    with closing(sqlite3.connect(ROOT / "recordsRefreshed.db")) as conn:
        row = conn.execute(query + """SELECT COUNT(*),
            SUM(recorded_at LIKE ?),SUM(item_type='漫画'),SUM(item_type='小说') FROM grouped""",
                           [*params, datetime.now().strftime("%Y-%m-%d") + "%"]).fetchone()
    return dict(zip(("total", "today", "comic", "novel"), [value or 0 for value in row]))


def _cleanup_expired_records():
    """Delete scrape history older than the configured retention window."""
    db_file = ROOT / "recordsRefreshed.db"
    if not db_file.exists():
        return
    try:
        days = max(1, min(int(_read_state().get("RECORD_RETENTION_DAYS", 30)), 365))
        with closing(sqlite3.connect(db_file)) as conn:
            conn.execute("DELETE FROM scrape_records WHERE datetime(recorded_at) < datetime('now', ?)", (f"-{days} days",))
            conn.commit()
    except (OSError, sqlite3.Error, TypeError, ValueError):
        return


def _read_runtime_logs(limit=100, offset=0, search="", with_total=False):
    db_file = ROOT / "recordsRefreshed.db"
    if not db_file.exists():
        return {"items": [], "total": 0} if with_total else []
    try:
        conn = sqlite3.connect(db_file)
        conn.execute("CREATE TABLE IF NOT EXISTS activity_logs (id INTEGER PRIMARY KEY AUTOINCREMENT, level TEXT NOT NULL, action TEXT NOT NULL, detail TEXT NOT NULL, source TEXT, recorded_at TEXT NOT NULL)")
        try:
            days = max(1, min(int(_read_state().get("LOG_RETENTION_DAYS", 30)), 365))
        except (TypeError, ValueError):
            days = 30
        conn.execute("DELETE FROM activity_logs WHERE datetime(recorded_at) < datetime('now', ?)", (f"-{days} days",))
        conn.commit()
        params = []
        where = ""
        if search:
            where = "WHERE action LIKE ? OR detail LIKE ? OR source LIKE ?"
            needle = f"%{search}%"
            params.extend([needle, needle, needle])
        total = conn.execute(f"SELECT COUNT(*) FROM activity_logs {where}", params).fetchone()[0]
        rows = conn.execute(f"SELECT id,level,action,detail,source,recorded_at FROM activity_logs {where} ORDER BY id DESC LIMIT ? OFFSET ?", (*params, max(1, min(limit, 100)), max(0, offset))).fetchall()
        conn.close()
        items = [{"id": r[0], "level": r[1], "action": r[2], "detail": r[3], "source": r[4], "recorded_at": r[5]} for r in rows]
        return {"items": items, "total": total} if with_total else items
    except sqlite3.Error:
        return {"items": [], "total": 0} if with_total else []


def _runtime_log_stats():
    db_file = ROOT / "recordsRefreshed.db"
    if not db_file.exists():
        return {"total": 0, "today": 0, "success": 0, "failed": 0}
    try:
        conn = sqlite3.connect(db_file)
        conn.execute("CREATE TABLE IF NOT EXISTS activity_logs (id INTEGER PRIMARY KEY AUTOINCREMENT, level TEXT NOT NULL, action TEXT NOT NULL, detail TEXT NOT NULL, source TEXT, recorded_at TEXT NOT NULL)")
        try:
            days = max(1, min(int(_read_state().get("LOG_RETENTION_DAYS", 30)), 365))
        except (TypeError, ValueError):
            days = 30
        conn.execute("DELETE FROM activity_logs WHERE datetime(recorded_at) < datetime('now', ?)", (f"-{days} days",))
        conn.commit()
        today = __import__("datetime").date.today().isoformat()
        row = conn.execute("SELECT COUNT(*), SUM(recorded_at LIKE ?) FROM activity_logs", (today + "%",)).fetchone()
        from tools.execution_outcomes import ensure_table
        ensure_table(conn)
        conn.execute("DELETE FROM execution_outcomes WHERE datetime(recorded_at)<datetime('now',?)", (f"-{days} days",))
        outcomes = conn.execute("SELECT SUM(failed=0),SUM(failed=1) FROM execution_outcomes").fetchone()
        failures = conn.execute("""SELECT COUNT(*) FROM activity_logs WHERE LOWER(level) IN ('error','critical')
            AND (action LIKE '计划任务%' OR action LIKE '手动刮削%' OR action='刮削匹配'
                 OR source IN ('scheduler','manual','task','scraper'))""").fetchone()[0]
        conn.commit()
        conn.close()
        return {"total": row[0] or 0, "today": row[1] or 0, "success": outcomes[0] or 0, "failed": failures}
    except sqlite3.Error:
        return {"total": 0, "today": 0, "success": 0, "failed": 0}


def _write_activity(action, detail, level="info", source="web"):
    try:
        from tools.db import record_activity_log
        conn = sqlite3.connect(ROOT / "recordsRefreshed.db")
        conn.execute("CREATE TABLE IF NOT EXISTS activity_logs (id INTEGER PRIMARY KEY AUTOINCREMENT, level TEXT NOT NULL, action TEXT NOT NULL, detail TEXT NOT NULL, source TEXT, recorded_at TEXT NOT NULL)")
        record_activity_log(conn, action, detail, level, source)
        conn.close()
    except Exception:
        pass


def _preview_items(server_id, library_id, force=False):
    key = (str(server_id or ""), str(library_id or ""))
    with PREVIEW_CACHE_LOCK:
        _load_preview_cache()
        cached = PREVIEW_CACHE.get(key)
        # Collages stay stable across page loads and container restarts. Only
        # an explicit refresh request (right-click or a scheduled task) may
        # replace the selected series.
        if cached and not force:
            return cached["items"]
    # Network I/O must not block login manifests or other libraries' covers.
    komga = _load_komga(server_id)
    payload = komga.get_latest_series(library_id=library_id, page=0)
    items = payload.get("content", []) if isinstance(payload, dict) else payload
    latest_batch = list(items or [])[:20]
    random.shuffle(latest_batch)
    selected_items = [latest_batch[index % len(latest_batch)] for index in range(8)] if latest_batch else []
    version = f"{int(time.time() * 1000)}-{secrets.token_hex(3)}"
    result = []
    for index, series in enumerate(selected_items):
        series_id = series.get("id")
        if series_id:
            result.append({
                "id": series_id,
                "preview_id": f"{series_id}-{index}",
                "title": series.get("name") or (series.get("metadata") or {}).get("title", ""),
                "url": f"/api/komga/cover?server_id={server_id}&series_id={series_id}&v={version}",
            })
    with PREVIEW_CACHE_LOCK:
        if key in PREVIEW_CACHE and not force:
            return PREVIEW_CACHE[key]["items"]
        PREVIEW_CACHE[key] = {"created": time.time(), "version": version, "items": result}
        _persist_preview_cache(key)
        return result


def _prepare_login_previews():
    """Warm missing opted-in collages off-thread without refreshing saved selections."""
    def prepare(key):
        try:
            with PREVIEW_CACHE_LOCK:
                empty_cache = key in PREVIEW_CACHE and not PREVIEW_CACHE[key].get("items")
            _preview_items(*key, **({"force": True} if empty_cache else {}))
        except Exception:
            # Public polling must not repeatedly hammer an unavailable server.
            pass
        finally:
            with PREVIEW_CACHE_LOCK:
                LOGIN_PREVIEW_PENDING.discard(key)

    state = _read_state()
    with PREVIEW_CACHE_LOCK:
        _load_preview_cache()
        for card in state.get("KOMGA_LIBRARY_LIST", []):
            if not card.get("LOGIN_BACKGROUND") or not card.get("LIBRARY"):
                continue
            key = (str(card.get("SERVER_ID") or ""), str(card["LIBRARY"]))
            if PREVIEW_CACHE.get(key, {}).get("items") or key in LOGIN_PREVIEW_PENDING:
                continue
            if time.monotonic() < LOGIN_PREVIEW_RETRY_AT.get(key, 0):
                continue
            LOGIN_PREVIEW_PENDING.add(key)
            LOGIN_PREVIEW_RETRY_AT[key] = time.monotonic() + 60
            threading.Thread(target=prepare, args=(key,), daemon=True).start()


def _login_background_entries():
    """Expose only opaque handles for explicitly opted-in, cached covers."""
    state = _read_state()
    result = {}
    with PREVIEW_CACHE_LOCK:
        _load_preview_cache()
        for card in state.get("KOMGA_LIBRARY_LIST", []):
            if not card.get("LOGIN_BACKGROUND"):
                continue
            server, library = str(card.get("SERVER_ID") or ""), str(card.get("LIBRARY") or "")
            for item in PREVIEW_CACHE.get((server, library), {}).get("items", []):
                series = str(item.get("id") or "")
                if not series:
                    continue
                identity = json.dumps([server, library, series], ensure_ascii=False).encode("utf-8")
                token = hmac.new(LOGIN_BACKGROUND_SECRET, identity, hashlib.sha256).hexdigest()
                result[token] = (server, library, series)
    return result


def _login_cover(token):
    entry = _login_background_entries().get(token)
    if entry is None:
        raise ValueError("Background cover unavailable")
    komga = _load_komga(entry[0])
    try:
        content, content_type, _ = read_series_cover(komga, entry[2])
        return content, content_type
    finally:
        komga.r.close()


class Handler(BaseHTTPRequestHandler):
    server_version = "BangumiKomgaWeb/1.0"

    def log_message(self, *_args):
        return

    def _json(self, status, payload):
        raw = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def _body(self):
        size = int(self.headers.get("Content-Length", "0"))
        return json.loads(self.rfile.read(size) or b"{}")

    def _session_token(self):
        cookies = self.headers.get("Cookie", "").split(";")
        for cookie in cookies:
            key, _, value = cookie.strip().partition("=")
            if key == "bk_session":
                return value
        return None

    def _authorized(self):
        return self._session_token() in SESSIONS

    def _require_auth(self):
        if self._authorized():
            return True
        self._json(401, {"error": "请先登录"})
        return False

    def do_GET(self):  # noqa: N802
        path = urlparse(self.path).path
        if path == "/api/auth/session":
            self._json(200, {"authenticated": self._authorized(), "username": _read_auth()["username"] if self._authorized() else ""})
        elif path == "/api/login-background":
            _prepare_login_previews()
            entries = list(_login_background_entries())
            self._json(200, {"items": [{"url": "/api/login-background/cover?token=" + token}
                                      for token in entries[:36]], "pending": bool(LOGIN_PREVIEW_PENDING)})
        elif path == "/api/login-background/cover":
            try:
                token = parse_qs(urlparse(self.path).query).get("token", [""])[0]
                content, content_type = _login_cover(token)
                self.send_response(200)
                self.send_header("Content-Type", content_type)
                self.send_header("Cache-Control", "no-store")
                self.send_header("Content-Length", str(len(content)))
                self.end_headers()
                self.wfile.write(content)
            except Exception:
                self._json(404, {"error": "封面不可用"})
        elif path.startswith("/api/") and not self._authorized():
            self._json(401, {"error": "请先登录"})
        elif path == "/api/config":
            self._json(200, _read_state())
        elif path == "/api/config/backup":
            _write_activity("配置：备份", "下载当前配置备份\n包含系统设置、媒体卡片、计划任务与认证配置")
            self._json(200, {"config": _read_state(), "format": "bangumikomga-config-v1"})
        elif path == "/api/status":
            self._json(200, TASK_EXECUTOR.snapshot())
        elif path == "/api/scrape-records":
            query = parse_qs(urlparse(self.path).query)
            try:
                limit = max(1, min(int(query.get("limit", [50])[0]), 50))
                offset = max(0, int(query.get("offset", [0])[0]))
            except ValueError:
                limit, offset = 50, 0
            self._json(200, _read_scrape_records(limit, offset, query.get("q", [""])[0],
                                               query.get("sort", ["newest"])[0] != "oldest", True))
        elif path == "/api/scrape-records/stats":
            self._json(200, _read_scrape_stats())
        elif path == "/api/scrape-records/details":
            query = parse_qs(urlparse(self.path).query)
            try:
                self._json(200, _read_record_details(query.get("id", [""])[0], int(query.get("offset", [0])[0])))
            except ValueError:
                self._json(400, {"error": "记录分页参数无效"})
        elif path == "/api/runtime-logs":
            query = parse_qs(urlparse(self.path).query)
            try:
                limit = max(1, min(int(query.get("limit", [100])[0]), 100))
                offset = max(0, int(query.get("offset", [0])[0]))
            except ValueError:
                limit, offset = 100, 0
            self._json(200, _read_runtime_logs(limit, offset, query.get("q", [""])[0].strip(), True))
        elif path == "/api/runtime-logs/stats":
            self._json(200, _runtime_log_stats())
        elif path == "/api/tasks":
            self._json(200, {"items": _read_state().get("METADATA_TASKS", []) or []})
        elif path == "/api/bangumi/search":
            query = parse_qs(urlparse(self.path).query).get("q", [""])[0].strip()
            if not query:
                self._json(400, {"error": "请输入搜索关键词"})
            else:
                try:
                    from api.bangumi_api import BangumiDataSourceFactory
                    state = _read_state()
                    source = BangumiDataSourceFactory.create({
                        "access_token": state.get("BANGUMI_ACCESS_TOKEN", ""),
                        "proxy_url": state.get("OUTBOUND_PROXY_URL", ""),
                        "use_local_archive": bool(state.get("USE_BANGUMI_ARCHIVE", False)),
                        "local_archive_folder": state.get("ARCHIVE_FILES_DIR", "./archivedata/"),
                    })
                    results = source.search_subjects(query, int(state.get("FUZZ_SCORE_THRESHOLD", 80)), False) or []
                    items = [{
                        "id": item.get("id"),
                        "name": item.get("name", ""),
                        "name_cn": item.get("name_cn", ""),
                        "type": item.get("type"),
                        "summary": item.get("summary", ""),
                        "images": item.get("images", {}),
                        "rating": item.get("rating", {}),
                    } for item in results[:8] if isinstance(item, dict)]
                    _write_activity("按钮：Bangumi 搜索", f"搜索“{query}”，返回 {len(items)} 个结果")
                    self._json(200, {"items": items})
                except Exception as exc:
                    self._json(400, {"error": f"Bangumi 搜索失败：{exc}"})
        elif path == "/api/bangumi/subject":
            subject_id = parse_qs(urlparse(self.path).query).get("id", [""])[0]
            if not subject_id:
                self._json(400, {"error": "缺少 Bangumi 条目 ID"})
            else:
                try:
                    from api.bangumi_api import BangumiDataSourceFactory
                    state = _read_state()
                    source = BangumiDataSourceFactory.create({
                        "access_token": state.get("BANGUMI_ACCESS_TOKEN", ""),
                        "proxy_url": state.get("OUTBOUND_PROXY_URL", ""),
                        "use_local_archive": bool(state.get("USE_BANGUMI_ARCHIVE", False)),
                        "local_archive_folder": state.get("ARCHIVE_FILES_DIR", "./archivedata/"),
                    })
                    item = source.get_subject_metadata(subject_id) or {}
                    self._json(200, {"item": {
                        "id": item.get("id"), "name": item.get("name", ""), "name_cn": item.get("name_cn", ""),
                        "summary": item.get("summary", ""), "type": item.get("type"), "images": item.get("images", {}),
                        "rating": item.get("rating", {}), "volumes": item.get("volumes", 0),
                        "date": item.get("date", ""), "tags": item.get("tags", []),
                    }})
                except Exception as exc:
                    self._json(400, {"error": f"Bangumi 预览失败：{exc}"})
        elif path == "/api/komga/previews":
            query = parse_qs(urlparse(self.path).query)
            server_id = query.get("server_id", [""])[0]
            library_id = query.get("library_id", [""])[0]
            force = query.get("refresh", ["0"])[0] == "1"
            if not library_id:
                self._json(400, {"error": "缺少媒体库 ID"})
            else:
                try:
                    self._json(200, {"items": _preview_items(server_id, library_id, force=force)})
                except Exception as exc:
                    self._json(400, {"error": str(exc)})
        elif path == "/api/komga/cover":
            query = parse_qs(urlparse(self.path).query)
            komga = None
            try:
                komga = _load_komga(query.get("server_id", [""])[0])
                series_id = query.get("series_id", [""])[0]
                content, content_type, cache_headers = read_series_cover(komga, series_id)
                self.send_response(200)
                self.send_header("Content-Type", content_type)
                # URLs include a new version after a manual refresh, so the
                # browser can safely keep the high-quality bytes for a year.
                self.send_header("Cache-Control", "public, max-age=31536000, immutable")
                for header, value in cache_headers.items():
                    self.send_header(header, value)
                self.send_header("Content-Length", str(len(content)))
                self.end_headers()
                self.wfile.write(content)
            except Exception as exc:
                self._json(404, {"error": f"封面读取失败：{exc}"})
            finally:
                if komga is not None:
                    komga.r.close()
        elif path == "/api/komga/libraries":
            try:
                query = dict(item.split("=", 1) for item in urlparse(self.path).query.split("&") if "=" in item)
                self._json(200, {"items": _load_komga(query.get("server_id")).list_libraries()})
            except Exception as exc:
                self._json(400, {"error": str(exc)})
        elif path == "/api/komga/collections" and self._require_auth():
            try:
                self._json(200, {"items": _load_komga().list_collections()})
            except Exception as exc:
                self._json(400, {"error": str(exc)})
        else:
            self._serve_static(path)

    def do_POST(self):  # noqa: N802
        path = urlparse(self.path).path
        try:
            if path == "/api/auth/login":
                body = self._body()
                auth = _read_auth()
                if body.get("username") != auth["username"] or _password_hash(body.get("password", "")) != auth["password_hash"]:
                    self._json(401, {"error": "账号或密码错误"})
                    return
                token = secrets.token_urlsafe(32)
                SESSIONS.add(token)
                _write_activity("按钮：登录", f"账号 {auth['username']} 登录后台")
                raw = json.dumps({"authenticated": True, "username": auth["username"]}, ensure_ascii=False).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Set-Cookie", f"bk_session={token}; Path=/; HttpOnly; SameSite=Strict")
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)
            elif path == "/api/auth/logout":
                token = self._session_token()
                if token:
                    SESSIONS.discard(token)
                _write_activity("按钮：退出登录", "用户退出后台")
                self._json(200, {"authenticated": False})
            elif path == "/api/auth/credentials" and self._require_auth():
                body = self._body()
                username = str(body.get("username", "")).strip()
                password = str(body.get("password", ""))
                if not username or not password:
                    self._json(400, {"error": "账号和密码不能为空"})
                    return
                result = _save_auth(username, password)
                _write_activity("配置：保存账号", f"后台账号修改为 {username}")
                self._json(200, result)
            elif path in ("/api/ai/test", "/api/ai") and not self._authorized():
                self._json(401, {"error": "请先登录"})
            elif path == "/api/ai/test":
                from tools.summary_translation import translate_summary_to_zh
                body = self._body()
                settings = _read_state()
                for key in ("OPENAI_BASE_URL", "OPENAI_API_KEY", "OPENAI_MODEL"):
                    settings[key] = str(body.get(key) or "").strip()
                sample = "A young reader discovers a secret library and begins a new adventure."
                try:
                    translated = translate_summary_to_zh(sample, True, settings, strict=True)
                    # Never echo credentials even if a provider includes them in its output.
                    for key in ("OPENAI_API_KEY", "OPENAI_BASE_URL", "OUTBOUND_PROXY_URL"):
                        if settings.get(key):
                            translated = translated.replace(settings[key], "[已隐藏]")
                    translated = translated[:2000]
                    _write_activity("AI：测试翻译成功", f"接口调用成功，返回中文译文\n原文：{sample}\n译文：{translated}")
                    self._json(200, {"message": "接口与中文翻译测试通过", "translation": translated})
                except ValueError as exc:
                    _write_activity("AI：测试翻译失败", str(exc), level="error")
                    self._json(400, {"error": str(exc)})
            elif path == "/api/ai":
                body = self._body()
                state = _read_state()
                for key in ("OPENAI_BASE_URL", "OPENAI_API_KEY", "OPENAI_MODEL"):
                    state[key] = str(body.get(key) or "").strip()
                save_state(state)
                _write_activity("配置：保存AI", "AI 接口配置已保存，凭据不写入日志")
                self._json(200, {"saved": True})
            elif path == "/api/proxy/test" and self._require_auth():
                from tools.proxy_settings import test_proxy
                result = test_proxy(self._body().get("url", ""))
                _write_activity("按钮：测试代理", "通过代理连接 Bangumi 成功")
                self._json(200, result)
            elif path == "/api/proxy" and self._require_auth():
                state = _read_state()
                state["OUTBOUND_PROXY_URL"] = self._body().get("url", "")
                result = save_state(state)
                _write_activity("配置：保存代理", "外部请求代理已修改" if result["OUTBOUND_PROXY_URL"] else "已清除外部请求代理")
                self._json(200, {"url": result["OUTBOUND_PROXY_URL"]})
            elif path == "/api/config" and self._require_auth():
                previous = _read_state()
                result = save_state(self._body())
                _write_activity("配置：保存设置", config_changes(previous, result))
                self._json(200, result)
            elif path == "/api/config/restore" and self._require_auth():
                body = self._body()
                payload = body.get("config", body) if isinstance(body, dict) else {}
                if not isinstance(payload, dict):
                    self._json(400, {"error": "备份文件格式无效"})
                    return
                previous = _read_state()
                result = save_state(payload)
                _write_activity("配置：还原", "从备份还原配置\n" + config_changes(previous, result))
                self._json(200, result)
            elif path == "/api/refresh" and self._require_auth():
                body = self._body()
                if _start_refresh(bool(body.get("full", False)), target_id=body.get("target_id")):
                    _write_activity("按钮：手动刮削", "触发方式：媒体卡片右键菜单\n方式：" + ("全量" if body.get("full", False) else "增量") + "\n目标：" + target_names([body.get("target_id") or "全部已配置媒体库"], _read_state()))
                    self._json(202, {"started": True})
                else:
                    self._json(409, {"started": False, "error": "已有刷新任务正在运行"})
            elif path == "/api/tasks" and self._require_auth():
                body = self._body()
                state = _read_state()
                task = dict(body or {})
                task["id"] = str(task.get("id") or f"task-{secrets.token_hex(6)}")
                task["functions"] = [str(value) for value in (task.get("functions") or [task.get("type", "metadata_completion")])][:1]
                task["type"] = task["functions"][0] if task["functions"] else "metadata_completion"
                labels = {"metadata_completion": "元数据补全", "summary_translation": "AI翻译", "metadata_correction": "元数据修正", "card_collage_refresh": "卡片拼贴刷新"}
                if task["type"] not in labels:
                    self._json(400, {"error": "无效的任务功能"})
                    return
                original_tasks = state.get("METADATA_TASKS") or []
                task_index = next((index for index, item in enumerate(original_tasks)
                                   if item.get("id") == task["id"]), len(original_tasks))
                previous_task = original_tasks[task_index] if task_index < len(original_tasks) else None
                task["time_limit_hours"] = task.get("time_limit_hours",
                    previous_task.get("time_limit_hours", 0) if previous_task is not None else 2)
                tasks = [item for item in original_tasks if item.get("id") != task["id"]]
                task["name"] = str(task.get("name") or "").strip()
                if not task["name"]:
                    base_name = labels.get(task["type"], "计划任务")
                    existing = {str(item.get("name") or "") for item in tasks}
                    task["name"] = base_name
                    if task["name"] in existing:
                        task["name"] = f"{base_name} 副本"
                        copy_index = 2
                        while task["name"] in existing:
                            task["name"] = f"{base_name} 副本 {copy_index}"
                            copy_index += 1
                task["fields"] = list(task.get("fields") or [])
                if task["type"] != "card_collage_refresh" and not task["fields"]:
                    self._json(400, {"error": "请至少选择一个元数据项"})
                    return
                task["operations"] = list(task.get("operations") or [])
                task["ai_completion"] = bool(task.get("ai_completion", False))
                task.update(task_lock_options(task))
                task["operations"] = [value for value in task["operations"] if value != "include_locked"]
                if task["type"] in ("summary_translation", "metadata_correction"):
                    if not task["fields"] or any(field not in ("title", "summary", "publisher", "authors") for field in task["fields"]):
                        self._json(400, {"error": "请选择元数据：标题、简介、出版商或作者"})
                        return
                if task["type"] == "metadata_correction":
                    ops = set(task["operations"])
                    if not ops <= {"simplify", "extract_title", "include_locked"} or not ops & {"simplify", "extract_title"}:
                        self._json(400, {"error": "请选择繁转简或标题提取"})
                        return
                    if "simplify" not in ops and "title" not in task["fields"]:
                        self._json(400, {"error": "标题提取需要选择标题元数据"})
                        return
                task["card_ids"] = list(task.get("card_ids") or [])
                task["cron"] = str(task.get("cron") or "0 6 * * *").strip()
                if len(task["cron"].split()) != 5:
                    self._json(400, {"error": "计划任务必须填写五段 Cron 表达式"})
                    return
                task["schedule"] = task["cron"]
                task["enabled"] = bool(task.get("enabled", True))
                tasks.insert(task_index, task)
                state["METADATA_TASKS"] = tasks
                result = save_state(state)
                _write_activity("计划任务：保存", task_details(task, result))
                self._json(200, {"items": result.get("METADATA_TASKS", [])})
            elif path == "/api/tasks/delete" and self._require_auth():
                task_id = str(self._body().get("id", ""))
                if task_id in TASK_EXECUTOR.snapshot()["tasks"]:
                    self._json(409, {"error": "请先停止正在执行或排队的任务，再删除"})
                    return
                state = _read_state()
                deleted = next((item for item in state.get("METADATA_TASKS", []) if item.get("id")==task_id), {"id":task_id,"name":task_id})
                state["METADATA_TASKS"] = [item for item in (state.get("METADATA_TASKS") or []) if item.get("id") != task_id]
                result = save_state(state)
                _write_activity("计划任务：删除", task_details(deleted, state))
                self._json(200, {"items": result.get("METADATA_TASKS", [])})
            elif path == "/api/tasks/stop" and self._require_auth():
                task_id = str(self._body().get("id", ""))
                stopped = _stop_task(task_id)
                if stopped:
                    _write_activity("计划任务：停止请求", f"停止执行或取消排队：{task_id}")
                self._json(202 if stopped else 409, {"stopping": stopped, "error": "" if stopped else "任务已结束或不是当前运行任务"})
            elif path == "/api/tasks/run" and self._require_auth():
                body = self._body()
                task_id = str(body.get("id", ""))
                task = next((item for item in (_read_state().get("METADATA_TASKS") or []) if item.get("id") == task_id), None)
                if not task:
                    self._json(404, {"error": "计划任务不存在"})
                elif _start_task(task):
                    _write_activity("计划任务：执行", "触发方式：点击立即执行\n" + task_details(task, _read_state()))
                    self._json(202, {"started": True})
                else:
                    self._json(409, {"started": False, "error": "此任务已在执行或排队"})
            else:
                self._json(404, {"error": "not found"})
        except Exception as exc:
            self._json(400, {"error": str(exc)})

    def _serve_static(self, path):
        relative = "index.html" if path in ("", "/") else path.lstrip("/")
        target = (WEB_DIR / relative).resolve()
        if WEB_DIR not in target.parents and target != WEB_DIR:
            self._json(403, {"error": "forbidden"})
            return
        if not target.exists() or not target.is_file():
            self._json(404, {"error": "not found"})
            return
        content_type = "text/html; charset=utf-8" if target.suffix == ".html" else "text/plain; charset=utf-8"
        if target.suffix == ".js":
            content_type = "application/javascript; charset=utf-8"
        elif target.suffix == ".css":
            content_type = "text/css; charset=utf-8"
        elif target.suffix == ".ico":
            content_type = "image/x-icon"
        elif target.suffix == ".png":
            content_type = "image/png"
        elif target.suffix == ".svg":
            content_type = "image/svg+xml"
        raw = target.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)


def start_web_server(port=PORT):
    server = ThreadingHTTPServer(("0.0.0.0", port), Handler)
    threading.Thread(target=server.serve_forever, name="WebServer", daemon=True).start()
    _start_task_scheduler()
    return server


if __name__ == "__main__":
    start_web_server().serve_forever()
