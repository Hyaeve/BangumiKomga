"""Shared task lock policy; never unlock fields as a side effect."""


def task_lock_options(task):
    kind = (task.get("functions") or [task.get("type")])[0]
    return {
        "include_locked": bool(task.get("include_locked", "include_locked" in (task.get("operations") or []))),
        # Preserve the historical translation behavior only for old configs.
        "lock_completed": bool(task.get("lock_completed", kind == "summary_translation")),
    }


def locked(metadata, field):
    return bool(metadata.get(field + "Lock") or metadata.get(field + "Locked"))


def completion_payload(metadata, candidates, fields, include_locked=False, lock_completed=False):
    result = {}
    for field in fields:
        if field not in candidates or field.endswith(("Lock", "Locked")):
            continue
        if locked(metadata, field) and not include_locked:
            continue
        value = metadata.get(field)
        if value in (None, "", [], {}):
            value = candidates[field]
            if value in (None, "", [], {}):
                continue
            result[field] = value
        if lock_completed and not locked(metadata, field):
            result[field + "Lock"] = True
    return result


def lock_existing_completion(komga, item, kind, fields, on_update, on_log):
    """Already populated selected fields satisfy completion without a search."""
    original = item.get("metadata") or {}
    eligible = [field for field in fields if field in original
                and original[field] not in (None, "", [], {}) and not locked(original, field)]
    if not eligible:
        return
    latest = (komga.get_specific_series if kind == "series" else komga.get_specific_book)(item["id"])
    current = latest.get("metadata") or {}
    payload = {field + "Lock": True for field in eligible
               if current.get(field) == original[field] and not locked(current, field)}
    if not payload:
        return
    if (komga.update_series_metadata if kind == "series" else komga.update_book_metadata)(item["id"], payload):
        from tools.komga_path import item_path
        on_update({**item, "url": item_path(latest) or item_path(item)}, kind, list(payload))
    else:
        on_log(f"{item.get('name', item['id'])}：已完成元数据锁定失败", "error")
