"""Explicit title extraction shared by correction and matching tasks."""
import re


def normalize_filter_terms(value):
    lines = value.splitlines() if isinstance(value, str) else value if isinstance(value, list) else []
    return list(dict.fromkeys(line.strip() for line in lines if isinstance(line, str) and line.strip()))


def compile_title_filters(value, use_regex=False):
    return [pattern for pattern, _ in title_filter_rules(value, use_regex)]


def title_filter_rules(value, use_regex=False):
    terms = normalize_filter_terms(value)
    patterns = []
    for index, term in enumerate(terms, 1):
        flags = 0
        expression = term
        is_regex = use_regex
        if not use_regex and term.startswith("/") and term.rfind("/") > 0:
            end = term.rfind("/")
            expression, suffix = term[1:end], term[end+1:]
            if any(flag not in "ims" for flag in suffix):
                raise ValueError(f"过滤词条第 {index} 条正则标志无效，仅支持 i、m、s")
            for flag in suffix:
                flags |= {"i": re.I, "m": re.M, "s": re.S}[flag]
            is_regex = True
        try:
            patterns.append((re.compile(expression if is_regex else re.escape(term), flags), is_regex))
        except re.error as exc:
            raise ValueError(f"过滤词条第 {index} 条正则无效：{exc.msg}") from None
    return patterns


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
