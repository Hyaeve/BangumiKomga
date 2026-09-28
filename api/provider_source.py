"""Native provider fallback after every Bangumi title candidate has failed."""
from tools.native_core import core_request
from tools.provider_settings import validate_providers, DEFAULT_PROVIDERS
from tools.log import logger
import requests
import tempfile
from pathlib import Path
from urllib.parse import urlsplit
from tools.proxy_settings import proxy_kwargs

PREFIX = "provider:"
COVER_HOSTS = {
    "MANGA_UPDATES": ("mangaupdates.com",),
    "MAL": ("myanimelist.net",),
    "ANILIST": ("anilist.co",),
    "MANGADEX": ("mangadex.org",),
    "COMIC_VINE": ("gamespot.com",),
    "MANGA_BAKA": ("mangabaka.org",),
    "YEN_PRESS": ("yenpress.com",),
    "VIZ": ("viz.com",),
    "WEBTOONS": ("pstatic.net", "webtoons.com"),
    "EHENTAI": ("ehgt.org", "e-hentai.org"),
}


def encode_id(provider, item_id):
    return PREFIX + provider + ":" + str(item_id)


def decode_id(value):
    if not isinstance(value, str) or not value.startswith(PREFIX):
        return None
    parts = value.split(":", 2)
    return (parts[1], parts[2]) if len(parts) == 3 else None


def native_metadata(item):
    if not isinstance(item, dict) or not item.get("id") or not item.get("provider"):
        return {}
    all_fields = item.get("fields") or {}
    fields = {key: value for key, value in all_fields.items() if key in {
        "title", "summary", "publisher", "status", "genres", "tags", "alternateTitles",
        "ageRating", "totalBookCount", "language", "links", "titleSort", "readingDirection",
    }}
    titles = item.get("titles") or []
    name = fields.get("title") or next((t.get("name") for t in titles if t.get("name")), "")
    if not name:
        return {}
    return {
        "id": encode_id(item["provider"], item["id"]),
        "provider": item["provider"], "provider_id": item["id"],
        "name": name, "name_cn": "", "platform": "小说" if item.get("media_type") == "book" else "漫画",
        "series": True, "type": 1, "_provider_fields": fields,
        "summary": fields.get("summary", ""), "images": {},
        "_provider_cover": item.get("cover", ""),
        "_provider_shared": {key: all_fields[key] for key in ("authors", "releaseDate") if key in all_fields},
    }


class ProviderDataSource:
    def __init__(self, bangumi, options=None, proxy=""):
        self.bangumi = bangumi
        self.config = {"providers": validate_providers(DEFAULT_PROVIDERS if options is None else options),
                       "proxy": proxy}
        self.match_context = {}
        self.cover_loader = None
        self.metadata_cache = {}

    def __getattr__(self, name):
        return getattr(self.bangumi, name)

    def search_subjects(self, *args, **kwargs):
        from tools.komf_bangumi_metadata import mapped_subject
        results = self.bangumi.search_subjects(*args, **kwargs)
        return [mapped_subject(item) for item in results] if isinstance(results, list) else results

    def search_other_providers(self, queries, media):
        if not any(item.get("enabled") for item in self.config["providers"]):
            return None
        with tempfile.TemporaryDirectory(prefix="bangumikomga-match-") as folder:
            context = dict(self.match_context)
            if self.cover_loader and any(item.get("enabled") and item["name"] == "COMIC_VINE" for item in self.config["providers"]):
                try:
                    content = self.cover_loader()
                    if content and len(content) <= 8 * 1024 * 1024:
                        path = Path(folder) / "cover"
                        path.write_bytes(content)
                        context["cover_path"] = str(path)
                except Exception:
                    logger.warning("无法取得卷册封面，ComicVine 多候选不会猜测匹配")
            response = core_request("providers.match", {"provider_config": self.config,
                                    "queries": list(dict.fromkeys(queries))[:20], "media_type": media,
                                    "match_context": context})
        if response is None:
            logger.warning("未构建 Go 核心，跳过其他元数据提供商")
            return None
        for error in response.get("errors", []):
            logger.warning("元数据提供商：%s", error)
        item = native_metadata(response.get("match"))
        if item:
            item["_match_query"] = response.get("query", "")
            self.metadata_cache[item["id"]] = item
            return item
        return None

    def get_subject_metadata(self, subject_id):
        identity = decode_id(subject_id)
        if not identity:
            from tools.komf_bangumi_metadata import mapped_subject
            return mapped_subject(self.bangumi.get_subject_metadata(subject_id))
        response = core_request("providers.get", {"provider_config": self.config,
                                "provider": identity[0], "provider_id": identity[1]})
        if response is None:
            raise RuntimeError("读取已匹配提供商条目需要 Go 核心")
        item = native_metadata(response)
        if item:
            self.metadata_cache[item["id"]] = item
        return item

    def shared_book_fields(self, subject_id):
        metadata = self.metadata_cache.get(subject_id) or {}
        shared = metadata.get("_provider_shared") or {}
        # Komf inherits series authors when a volume has no own author list.
        # It does not copy the series summary or date to every volume.
        return {"authors": shared["authors"]} if shared.get("authors") else {}

    def get_related_subjects(self, subject_id):
        if decode_id(subject_id):
            # Never guess volume associations or send external IDs to Bangumi.
            return []
        return self.bangumi.get_related_subjects(subject_id)

    def associate_books(self, subject_id, books, media):
        identity = decode_id(subject_id)
        if not identity:
            return {}
        response = core_request("providers.associate", {
            "provider_config": self.config, "provider": identity[0], "provider_id": identity[1],
            "local_books": [{"id": str(book["id"]), "name": book.get("name", "")} for book in books],
            "media_type": media,
        })
        if response is None:
            raise RuntimeError("提供商卷册匹配需要 Go 核心")
        return response

    def get_book_metadata(self, subject_id, book_id):
        identity = decode_id(subject_id)
        if not identity:
            raise ValueError("提供商系列 ID 无效")
        response = core_request("providers.book", {
            "provider_config": self.config, "provider": identity[0], "provider_id": identity[1],
            "book_id": str(book_id),
        })
        if response is None:
            raise RuntimeError("提供商卷册详情需要 Go 核心")
        return response

    def get_subject_thumbnail(self, metadata, image_size):
        if metadata.get("provider"):
            address = metadata.get("_provider_cover", "")
            if not address:
                return {}
            try:
                parsed = urlsplit(address)
                host = parsed.hostname or ""
                allowed = COVER_HOSTS.get(metadata["provider"], ())
                if (parsed.scheme != "https" or parsed.username or parsed.port not in (None, 443)
                        or not any(host == domain or host.endswith("." + domain) for domain in allowed)):
                    return {}
                with requests.get(address, timeout=(5, 20), stream=True, allow_redirects=False,
                                  **proxy_kwargs(address, {"OUTBOUND_PROXY_URL": self.config["proxy"]})) as response:
                    if response.status_code != 200 or not response.headers.get("Content-Type", "").startswith("image/"):
                        return {}
                    chunks, size = [], 0
                    for chunk in response.iter_content(65536):
                        size += len(chunk)
                        if size > 8 * 1024 * 1024:
                            return {}
                        chunks.append(chunk)
                    return {"file": (metadata.get("name") or "cover", b"".join(chunks))} if size else {}
            except (requests.RequestException, ValueError):
                logger.warning("提供商封面获取失败")
                return {}
        return self.bangumi.get_subject_thumbnail(metadata, image_size)
