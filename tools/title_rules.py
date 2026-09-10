"""Explicit title extraction shared by correction and matching tasks."""
import re


def explicit_title(name):
    raw = str(name or "").strip()
    title = re.search(r"《([^《》]+)》", raw)
    if title and title.group(1).strip():
        return title.group(1).strip()
    groups = re.findall(r"\[([^\[\]]+)\]", raw)
    if groups and (len(groups) > 1 or re.fullmatch(r"\[[^\[\]]+\]", raw)):
        return groups[0].strip()
    return ""
