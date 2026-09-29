"""Content-addressed poster snapshots; no historical images are invented."""
import base64
import hashlib
import io
import os
import re
import sqlite3
import tempfile
import warnings
from pathlib import Path
from contextlib import closing

from PIL import Image
from tools.komga_cover import read_item_cover, MAX_COVER_BYTES


def folder():
    return Path(os.getenv("BANGUMI_KOMGA_DATA_DIR", str(Path(__file__).resolve().parents[1] / "config"))) / "posters"


def image_info(data):
    if not data or len(data) > MAX_COVER_BYTES:
        raise ValueError("海报为空或超过 16 MiB")
    with warnings.catch_warnings():
        warnings.simplefilter("error", Image.DecompressionBombWarning)
        try:
            with Image.open(io.BytesIO(data), formats=["JPEG", "PNG", "WEBP"]) as image:
                width, height = image.size
                mime = Image.MIME[image.format]
                if width * height > 40_000_000:
                    raise ValueError("海报超过 4000 万像素")
                image.verify()
        except Exception as exc:
            raise ValueError("请选择有效的 JPEG、PNG 或 WebP 海报") from exc
    return {"width": width, "height": height, "mime": mime}


def store(data):
    info = image_info(data)
    digest = hashlib.sha256(data).hexdigest()
    root = folder()
    root.mkdir(parents=True, exist_ok=True)
    path = root / digest
    if not path.exists():
        fd, temporary = tempfile.mkstemp(dir=root)
        try:
            with os.fdopen(fd, "wb") as output:
                output.write(data)
            os.replace(temporary, path)
        finally:
            if os.path.exists(temporary):
                os.remove(temporary)
    return {**info, "id": digest}


def read(digest):
    if not re.fullmatch(r"[a-f0-9]{64}", str(digest)):
        raise ValueError("海报标识无效")
    data = (folder() / digest).read_bytes()
    return data, image_info(data)["mime"]


def capture(client, item_id, kind):
    data, _, _ = read_item_cover(client, item_id, kind)
    return store(data)


def try_capture(client, item_id, kind):
    try:
        return capture(client, item_id, kind)
    except Exception:
        return None


def local_lock(client, item_id, kind, value=None):
    # Komga has no thumbnailLock field. Keep our protection policy locally.
    root = folder()
    root.mkdir(parents=True, exist_ok=True)
    key = hashlib.sha256(f"{client.base_url}|{kind}|{item_id}".encode()).hexdigest()
    with closing(sqlite3.connect(root / "locks.sqlite3")) as conn:
        conn.execute("CREATE TABLE IF NOT EXISTS locks (id TEXT PRIMARY KEY, locked INTEGER NOT NULL)")
        if value is not None:
            conn.execute("INSERT OR REPLACE INTO locks VALUES (?, ?)", (key, int(value)))
            conn.commit()
        row = conn.execute("SELECT locked FROM locks WHERE id=?", (key,)).fetchone()
        return bool(row and row[0])


def protected(client, item, kind):
    metadata = item.get("metadata") or {}
    if metadata.get("thumbnailLock") or metadata.get("thumbnailLocked") or local_lock(client, item["id"], kind):
        return True
    thumbnails = (client.get_series_thumbnails if kind == "series" else client.get_book_thumbnails)(item["id"])
    # Respect an existing manually selected/uploaded image unless explicitly included.
    return any(t.get("selected") and t.get("type") == "USER_UPLOADED" for t in thumbnails)


def upload(client, item_id, kind, data):
    info = store(data)
    uploader = client.update_series_thumbnail if kind == "series" else client.update_book_thumbnail
    if not uploader(item_id, {"file": ("poster", data, info["mime"])}):
        raise ValueError("Komga 海报上传失败，未修改本地记录")
    current = capture(client, item_id, kind)
    if current["id"] != info["id"]:
        raise ValueError("Komga 已接受上传，但回读图片与上传不一致，请检查实际封面")
    return current


def decode_upload(value):
    if not isinstance(value, str) or len(value) > 23 * 1024 * 1024:
        raise ValueError("海报文件过大或格式无效")
    try:
        data = base64.b64decode(value, validate=True)
    except ValueError as exc:
        raise ValueError("海报编码无效") from exc
    image_info(data)
    return data


def offline_candidate(item, settings):
    """Only previously matched Bangumi IDs and explicitly local poster files."""
    from bangumi_archive.sqlite_store import ArchiveStore
    links = (item.get("metadata") or {}).get("links") or []
    ids = []
    for link in links:
        match = re.fullmatch(r"https?://(?:bgm\.tv|bangumi\.tv|chii\.in)/subject/(\d+)/?", link.get("url", ""))
        if match:
            ids.append(match[1])
    if not ids:
        return None, "未记录已匹配的 Bangumi 条目，保留封面"
    root = Path(settings.get("ARCHIVE_FILES_DIR") or "./archivedata")
    archive = ArchiveStore(root)
    candidates = []
    for subject_id in ids:
        if not archive.get(subject_id):
            continue
        # Optional offline originals are independent of the official archive update.
        for suffix in ("jpg", "jpeg", "png", "webp"):
            path = root / "posters" / f"{subject_id}.{suffix}"
            if path.is_file() and path.stat().st_size <= MAX_COVER_BYTES:
                data = path.read_bytes()
                info = image_info(data)
                candidates.append((info["width"] * info["height"], data))
    if not candidates:
        return None, "离线库未提供海报原图（官方归档不含图片），保留封面"
    return max(candidates, key=lambda candidate: candidate[0])[1], ""


def replace_offline(client, item, kind, settings, include_locked, lock_completed):
    if not include_locked and protected(client, item, kind):
        return None, "海报已受保护，未勾选包含锁定，跳过"
    data, reason = offline_candidate(item, settings)
    if data is None:
        return None, reason
    before = capture(client, item["id"], kind)
    info = image_info(data)
    if (info["width"] < before["width"] or info["height"] < before["height"]
            or info["width"] * info["height"] <= before["width"] * before["height"]):
        return None, "没有更高分辨率海报，保留当前封面"
    old_lock = protected(client, item, kind)
    after = upload(client, item["id"], kind, data)
    if lock_completed:
        local_lock(client, item["id"], kind, True)
    return ({"thumbnail": before, "thumbnailLock": old_lock},
            {"thumbnail": after, "thumbnailLock": protected(client, item, kind)}), ""
