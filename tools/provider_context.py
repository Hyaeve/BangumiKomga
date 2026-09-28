"""Komga book context consumed only by a provider requiring cover disambiguation."""
from urllib.parse import quote


def read_qualifier_cover(komga, book_id):
    address = f"{komga.base_url}/books/{quote(str(book_id), safe='')}/thumbnail"
    with komga.r.get(address, stream=True, timeout=(5, 20)) as response:
        response.raise_for_status()
        if not response.headers.get("Content-Type", "").startswith("image/"):
            return b""
        result, size = [], 0
        for chunk in response.iter_content(65536):
            size += len(chunk)
            if size > 8 * 1024 * 1024:
                return b""
            result.append(chunk)
        return b"".join(result)
