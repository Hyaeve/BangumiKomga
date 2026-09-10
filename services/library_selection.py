"""Small helpers shared by runtime workers and SSE filtering."""


def is_configured_library(library_items, library_id):
    if not library_items or not library_id:
        return False
    return any(str(item.get("LIBRARY")) == str(library_id) for item in library_items)
