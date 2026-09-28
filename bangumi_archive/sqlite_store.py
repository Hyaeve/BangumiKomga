"""Bounded SQLite archive queries; atomic database replacement keeps readers safe."""
import json
import os
import sqlite3
import tempfile
import threading
from contextlib import closing
from pathlib import Path

from zhconv import convert
from tools.file_lock import exclusive_file_lock

SCHEMA_VERSION = 1
_build_lock = threading.Lock()
_building = set()


def ensure_index_background(folder):
    store = ArchiveStore(folder)
    if store.ready() or not (store.folder / "subject.jsonlines").exists():
        return
    key = str(store.folder.resolve())
    with _build_lock:
        if key in _building:
            return
        _building.add(key)
    def build():
        from tools.log import logger
        try:
            store.build()
            logger.info("Bangumi SQLite 离线索引已就绪")
        except Exception as exc:
            logger.error("Bangumi SQLite 索引构建失败：%s", exc)
        finally:
            with _build_lock:
                _building.discard(key)
    threading.Thread(target=build, daemon=True, name="BangumiSQLiteIndex").start()


def normalize(text):
    return convert(str(text or ""), "zh-cn").casefold().strip()


def subject_metadata(data):
    from bangumi_archive.local_archive_searcher import parse_infobox
    result = dict(data)
    result["infobox"] = parse_infobox(data.get("infobox", "")) if isinstance(data.get("infobox", ""), str) else data["infobox"]
    if not isinstance(result["infobox"], list):
        result["infobox"] = []
    for entry in result["infobox"]:
        if entry.get("key") == "别名" and isinstance(entry.get("value"), list):
            entry["value"] = [{"v": str(alias.get("v", "")).split("|")[-1].strip()}
                              for alias in entry["value"] if isinstance(alias, dict)]
    result.setdefault("name", "")
    result.setdefault("name_cn", "")
    result.setdefault("tags", [])
    result["images"] = {}
    result["rating"] = data.get("rating") or {"rank": data.get("rank", 0), "total": data.get("total", 0),
                                            "count": data.get("score_details", {}), "score": data.get("score", 0)}
    favorite = data.get("favorite") or {}
    result["collection"] = {key: favorite.get(source, 0) for key, source in
                            (("on_hold", "on_hold"), ("dropped", "dropped"), ("wish", "wish"), ("collect", "done"), ("doing", "doing"))}
    result["total_episodes"] = data.get("eps", 0)
    result["meta_tags"] = [tag["name"] for tag in result["tags"] if isinstance(tag, dict) and "name" in tag]
    result.setdefault("series", False)
    return result


class ArchiveStore:
    def __init__(self, folder):
        self.folder = Path(folder)
        self.path = self.folder / "bangumi.sqlite3"

    def signature(self):
        return json.dumps([(name, (self.folder / name).stat().st_size, (self.folder / name).stat().st_mtime_ns)
                           for name in ("subject.jsonlines", "subject-relations.jsonlines") if (self.folder / name).exists()])

    def ready(self):
        if not self.path.exists():
            return False
        try:
            with closing(sqlite3.connect(f"{self.path.resolve().as_uri()}?mode=ro", uri=True)) as conn:
                return conn.execute("SELECT value FROM state WHERE key='version'").fetchone() == (str(SCHEMA_VERSION),)
        except sqlite3.Error:
            return False

    def build(self):
        self.folder.mkdir(parents=True, exist_ok=True)
        with exclusive_file_lock(self.folder / "bangumi-index.lock"):
            signature = self.signature()
            if self.ready():
                with closing(sqlite3.connect(self.path)) as conn:
                    if conn.execute("SELECT value FROM state WHERE key='source'").fetchone() == (signature,):
                        return False
            source = self.folder / "subject.jsonlines"
            if not source.exists():
                raise FileNotFoundError("缺少 subject.jsonlines，无法构建离线索引")
            fd, temporary = tempfile.mkstemp(prefix="bangumi-build-", suffix=".sqlite3", dir=self.folder)
            os.close(fd)
            try:
                with closing(sqlite3.connect(temporary)) as conn:
                    conn.executescript("""
                        CREATE TABLE state(key TEXT PRIMARY KEY,value TEXT NOT NULL);
                        CREATE TABLE subjects(id INTEGER PRIMARY KEY,payload TEXT NOT NULL);
                        CREATE TABLE names(name TEXT NOT NULL,subject_id INTEGER NOT NULL);
                        CREATE INDEX names_exact ON names(name);
                        CREATE VIRTUAL TABLE names_fts USING fts5(name,subject_id UNINDEXED, tokenize='trigram');
                        CREATE TABLE relations(subject_id INTEGER,related_subject_id INTEGER,relation_type INTEGER);
                        CREATE INDEX relations_subject ON relations(subject_id);
                    """)
                    count = 0
                    with source.open(encoding="utf-8") as stream:
                        for line in stream:
                            if not line.strip():
                                continue
                            data = json.loads(line)
                            if data.get("type") != 1:
                                continue
                            metadata = subject_metadata(data)
                            subject_id = int(data["id"])
                            conn.execute("INSERT INTO subjects VALUES (?,?)", (subject_id, json.dumps(metadata, ensure_ascii=False)))
                            names = {normalize(metadata.get("name")), normalize(metadata.get("name_cn"))}
                            for entry in metadata["infobox"]:
                                if entry.get("key") in ("别名", "简体中文名"):
                                    value = entry.get("value")
                                    if isinstance(value, list):
                                        names.update(normalize(alias.get("v")) for alias in value if isinstance(alias, dict))
                                    elif isinstance(value, str):
                                        names.add(normalize(value))
                            for name in names - {""}:
                                conn.execute("INSERT INTO names VALUES (?,?)", (name, subject_id))
                                conn.execute("INSERT INTO names_fts VALUES (?,?)", (name, subject_id))
                            count += 1
                    if not count:
                        raise ValueError("离线归档没有书籍条目，保留旧索引")
                    relation_file = self.folder / "subject-relations.jsonlines"
                    if relation_file.exists():
                        with relation_file.open(encoding="utf-8") as stream:
                            for line in stream:
                                if not line.strip():
                                    continue
                                row = json.loads(line)
                                conn.execute("INSERT INTO relations VALUES (?,?,?)",
                                             (row["subject_id"], row["related_subject_id"], row["relation_type"]))
                    conn.executemany("INSERT INTO state VALUES (?,?)", [("version", str(SCHEMA_VERSION)), ("source", signature)])
                    conn.commit()
                os.replace(temporary, self.path)
            finally:
                if os.path.exists(temporary):
                    os.unlink(temporary)
            return True

    def get(self, subject_id):
        if not self.ready():
            return {}
        with closing(sqlite3.connect(f"{self.path.resolve().as_uri()}?mode=ro", uri=True)) as conn:
            row = conn.execute("SELECT payload FROM subjects WHERE id=?", (int(subject_id),)).fetchone()
        return json.loads(row[0]) if row else {}

    def search(self, query):
        if not self.ready():
            return []
        query = normalize(query)
        if not query:
            return []
        with closing(sqlite3.connect(f"{self.path.resolve().as_uri()}?mode=ro", uri=True)) as conn:
            ids = [row[0] for row in conn.execute("SELECT DISTINCT subject_id FROM names WHERE name=? LIMIT 200", (query,))]
            if len(query) >= 3:
                expression = '"' + query.replace('"', '""') + '"'
                ids.extend(row[0] for row in conn.execute("SELECT DISTINCT subject_id FROM names_fts WHERE names_fts MATCH ? LIMIT 200", (expression,)))
            else:
                # FTS trigram cannot match 1-2 character queries.
                escaped = query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
                ids.extend(row[0] for row in conn.execute("SELECT DISTINCT subject_id FROM names WHERE name LIKE ? ESCAPE '\\' LIMIT 200", ("%"+escaped+"%",)))
            ids = list(dict.fromkeys(ids))[:200]
            if not ids:
                return []
            return [json.loads(row[0]) for row in conn.execute(
                f"SELECT payload FROM subjects WHERE id IN ({','.join('?' for _ in ids)})", ids)]

    def relations(self, subject_id):
        if not self.ready():
            return []
        with closing(sqlite3.connect(f"{self.path.resolve().as_uri()}?mode=ro", uri=True)) as conn:
            rows = conn.execute("""SELECT s.payload,r.relation_type FROM relations r
                JOIN subjects s ON s.id=r.related_subject_id WHERE r.subject_id=?""", (int(subject_id),)).fetchall()
        return [{**json.loads(payload), "relation": relation} for payload, relation in rows]
