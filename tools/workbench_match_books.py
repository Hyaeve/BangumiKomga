"""Scoped volume writes for an explicitly confirmed workbench match."""
from contextlib import closing

from api.bangumi_api import BangumiArchiveDataSource
from api.bangumi_model import SubjectRelation
from api.provider_source import ProviderDataSource, encode_id
from tools.db import init_sqlite3, record_scrape_event, upsert_book_record
from tools.get_number import get_number, NumberType
from tools.komf_bangumi_metadata import book_fields
from tools.komga_path import item_path
from tools.record_edit import editable_fields, validate_changes
from tools.task_lock_policy import locked


def apply_books(backend, entry, include_cover):
    from tools.workbench_match import context, provider_config
    state, scope, card, series = context(backend, entry)
    client = backend._load_komga(scope["server_id"], require_server=True)
    warnings, completed = [], 0
    try:
        books = [book for book in client.iter_series_books(series["id"])
                 if str(book.get("seriesId")) == series["id"]
                 and str(book.get("libraryId")) == scope["library_id"] and not book.get("deleted")]
        if not books:
            return completed, warnings
        offline = entry["provider"] == "BANGUMI_OFFLINE"
        if offline:
            source = BangumiArchiveDataSource(state.get("ARCHIVE_FILES_DIR", "./archivedata/"))
            numbered = {}
            for related in source.get_related_subjects(entry["subject_id"]):
                if SubjectRelation.parse(related.get("relation")) != SubjectRelation.OFFPRINT:
                    continue
                number, kind = get_number((related.get("name") or "") + (related.get("name_cn") or ""))
                if kind not in (NumberType.NONE, NumberType.CHAPTER):
                    numbered.setdefault(number, []).append(related["id"])
            associations = {}
            for book in books:
                number, kind = get_number(book.get("name", ""))
                if kind not in (NumberType.NONE, NumberType.CHAPTER) and len(numbered.get(number, [])) == 1:
                    associations[str(book["id"])] = numbered[number][0]
        else:
            config = provider_config(state, entry["provider"])
            source = ProviderDataSource(None, config["providers"], config["proxy"])
            media_type = "webtoon" if entry["provider"] == "WEBTOONS" else entry.get("media_type", backend.media_type(card))
            associations = source.associate_books(entry["subject_id"], books, media_type)
        overwrite = set(card.get("OVERWRITE_FIELDS") or [])
        for book in books:
            identity = associations.get(str(book["id"]))
            if not identity:
                continue
            try:
                current = client.get_specific_book(book["id"])
                if (str(current.get("seriesId")) != series["id"]
                        or str(current.get("libraryId")) != scope["library_id"] or current.get("deleted")):
                    raise ValueError("卷册已移出当前媒体库或系列")
                before = current["metadata"]
                detail = ({"fields": book_fields(source.get_subject_metadata(identity))} if offline
                          else source.get_book_metadata(entry["subject_id"], identity))
                changes = {}
                for field, value in (detail.get("fields") or {}).items():
                    if (field not in editable_fields("volume") or value in (None, "", [], {})
                            or locked(before, field) or (field not in overwrite and before.get(field) not in (None, "", [], {}))):
                        continue
                    validate_changes({field: value}, "volume")
                    if before.get(field) != value:
                        changes[field] = value
                if changes and not client.update_book_metadata(book["id"], changes):
                    raise ValueError("卷册元数据写入失败")
                saved = client.get_specific_book(book["id"])["metadata"]
                if any(saved.get(key) != value for key, value in changes.items()):
                    raise ValueError("卷册写入后回读不一致")
                if any(saved.get(key + suffix) != before.get(key + suffix)
                       for key in changes for suffix in ("Lock", "Locked")):
                    raise ValueError("卷册锁定状态已变化")
                before, saved = dict(before), dict(saved)
                if include_cover and not offline and detail.get("cover"):
                    from tools import posters
                    try:
                        if not posters.protected(client, current, "volume"):
                            image = source.get_subject_thumbnail(
                                {"provider": entry["provider"], "_provider_cover": detail["cover"]}, "large")
                            if image:
                                old_poster = posters.try_capture(client, book["id"], "volume")
                                new_poster = posters.upload(client, book["id"], "volume", image["file"][1])
                                before["thumbnail"], saved["thumbnail"] = old_poster, new_poster
                                changes["thumbnail"] = new_poster
                    except Exception as exc:
                        warnings.append(f"{book.get('name', book['id'])} 海报未更新：{exc}")
                        backend._write_activity("工作平台：分卷海报失败", warnings[-1], level="error")
                _, conn = init_sqlite3(backend.ROOT / "recordsRefreshed.db")
                with closing(conn):
                    record_scrape_event(
                        conn, "小说" if backend.media_type(card) == "book" else "漫画",
                        book.get("name", ""), scope["library_id"], card.get("NAME") or scope["library_id"],
                        list(changes), source_title=series.get("name", ""), matched_title=saved.get("title", ""),
                        match_source="工作平台：手动刮削匹配", event_kind="volume", source_path=item_path(current),
                        komga_id=book["id"], server_id=scope["server_id"],
                        metadata_before=before, metadata_after=saved, metadata_provider=entry["provider"])
                    upsert_book_record(conn, book["id"], str(identity) if offline else encode_id(entry["provider"], identity), 1, book.get("name", ""))
                completed += 1
            except Exception as exc:
                warnings.append(f"{book.get('name', book['id'])}：{exc}")
                backend._write_activity("工作平台：分卷匹配失败", warnings[-1], level="error")
        return completed, warnings
    finally:
        client.r.close()
