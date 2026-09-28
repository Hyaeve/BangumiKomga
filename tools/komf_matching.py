"""Reference NameSimilarityMatcher and Bangumi candidate rules from komf-rs."""
from zhconv import convert
from api.bangumi_model import SubjectPlatform


def name_matches(query, candidate, mode="CLOSEST_MATCH"):
    if not isinstance(candidate, str) or not query:
        return False
    if mode == "EXACT" or len(query) <= 3:
        return query == candidate
    limit = 1 if len(query) <= 6 else 2 if len(query) <= 9 else 3
    left, right = query.upper(), candidate.upper()
    if abs(len(left) - len(right)) > limit:
        return False
    costs = list(range(len(left) + 1))
    for i, char in enumerate(right, 1):
        row = [i]
        for j, other in enumerate(left, 1):
            row.append(min(row[-1] + 1, costs[j] + 1, costs[j - 1] + (char != other)))
        costs = row
    return costs[-1] <= limit


def titles(subject, aliases=True):
    result = [subject.get("name"), subject.get("name_cn")]
    if aliases:
        for item in subject.get("infobox") or []:
            value = item.get("value")
            if item.get("key") in ("别名", "別名"):
                if isinstance(value, str):
                    result.append(value)
                elif isinstance(value, list):
                    result.extend(entry.get("v") for entry in value if isinstance(entry, dict))
            if isinstance(value, list):
                result.extend(entry.get("v") for entry in value if isinstance(entry, dict)
                              and entry.get("k") in ("别名", "別名", "版本名"))
    variants = []
    for title in result:
        if isinstance(title, str) and title:
            for value in (title, convert(title, "zh-cn"), convert(title, "zh-tw")):
                if value not in variants:
                    variants.append(value)
    return variants


def eligible(subject, media=False, offline=True):
    if not isinstance(subject, dict) or not subject.get("id"):
        return False
    if offline and subject.get("series") is False:
        return False
    if any(tag.get("name") == "漫画单行本" for tag in subject.get("tags", []) if isinstance(tag, dict)):
        return False
    platform = SubjectPlatform.parse(subject.get("platform"))
    mode = media if isinstance(media, str) else "book" if media else "comic"
    return (mode == "mixed" and platform in (SubjectPlatform.Comic, SubjectPlatform.Novel)
            or mode == "comic" and platform == SubjectPlatform.Comic
            or mode == "book" and platform == SubjectPlatform.Novel)


def match_bangumi(query, candidates, media=False, *, offline=True, detail_loader=None):
    candidates = [item for item in candidates if eligible(item, media, offline)]
    matched = [item for item in candidates if any(name_matches(query, title)
               for title in titles(item, aliases=offline))]
    # Online sparse DTOs use aliases only if none of the primary titles matched.
    if not matched and not offline and detail_loader:
        for item in candidates:
            detail = detail_loader(item["id"])
            if eligible(detail, media, False) and any(name_matches(query, title) for title in titles(detail)):
                matched.append(detail)
    if not matched:
        return []
    chosen = matched[0]
    if not offline and detail_loader:
        chosen = detail_loader(chosen["id"])
        if not eligible(chosen, media, False):
            return []
    return [chosen]
