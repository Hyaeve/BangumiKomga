"""Explicit title extraction shared by correction and matching tasks."""
import re


def normalize_filter_terms(value):
    lines = value.splitlines() if isinstance(value, str) else value if isinstance(value, list) else []
    return list(dict.fromkeys(line.strip() for line in lines if isinstance(line, str) and line.strip()))


def bracket_title(name):
    raw = str(name or "").strip()
    groups = re.findall(r"\[([^\[\]]+)\]", raw)
    if groups and (len(groups) > 1 or re.fullmatch(r"\[[^\[\]]+\]", raw)):
        return groups[0].strip()
    return ""


def explicit_title(name):
    raw = str(name or "").strip()
    title = re.search(r"《([^《》]+)》", raw)
    if title and title.group(1).strip():
        return title.group(1).strip()
    return bracket_title(raw)
