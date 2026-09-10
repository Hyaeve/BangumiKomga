"""Read original Komga posters consistently for public and authenticated views."""
from urllib.parse import quote

IMAGE_TYPES = {"image/jpeg", "image/png", "image/webp", "image/avif", "image/gif"}
MAX_COVER_BYTES = 16 * 1024 * 1024


def read_series_cover(komga, series_id):
    base = f"{komga.base_url}/series/{quote(str(series_id), safe='')}"
    headers = {"Accept": "image/avif,image/webp,image/jpeg,image/png,image/*"}

    def read_image(url):
        with komga.r.get(url, headers=headers, stream=True, timeout=(5, 20)) as response:
            if not response.ok:
                return None
            content_type = response.headers.get("Content-Type", "").split(";")[0].strip().lower()
            if content_type not in IMAGE_TYPES:
                return None
            data = bytearray()
            for chunk in response.iter_content(65536):
                data.extend(chunk)
                if len(data) > MAX_COVER_BYTES:
                    raise ValueError("Komga 封面超过大小限制")
            if not data:
                return None
            cache_headers = {key: response.headers[key] for key in ("ETag", "Last-Modified") if key in response.headers}
            return bytes(data), content_type, cache_headers

    result = read_image(base + "/thumbnail")
    if result is not None:
        return result
    with komga.r.get(base + "/thumbnails", timeout=(5, 20)) as response:
        response.raise_for_status()
        items = response.json()
    if isinstance(items, list):
        items = [item for item in items if isinstance(item, dict) and item.get("id")]
        selected = next((item for item in items if item.get("selected")), None) or next(iter(items), None)
        if selected:
            result = read_image(base + "/thumbnails/" + quote(str(selected["id"]), safe=""))
            if result is not None:
                return result
    raise ValueError("Komga 未返回有效封面")
