"""Sparse Bangumi field mapping based on komf-rs BangumiMetadataMapper."""
import re
import textwrap
from datetime import date
from tools.provider_filters import bangumi_tags, STATUS_TAGS


def infobox(subject):
    return {item.get("key"): item.get("value") for item in subject.get("infobox") or []
            if isinstance(item, dict)}


def names(value):
    if isinstance(value, str):
        return [part.strip() for part in re.split("[，、,]", value) if part.strip()]
    if isinstance(value, list):
        return [item["v"] for item in value if isinstance(item, dict) and isinstance(item.get("v"), str) and item["v"].strip()]
    return []


def status(value):
    if not isinstance(value, str):
        return None
    if any(term in value for term in ("休刊", "停刊", "停止连载", "长期休载")):
        return "HIATUS"
    if "连载" in value:
        return "ONGOING"
    if "腰斩" in value or "完结" in value:
        return "ENDED"
    return None


def release_date(value):
    if not isinstance(value, str):
        return None
    match = re.fullmatch(r"(\d{4})[-年](\d{1,2})(?:[-月](\d{1,2})日?|月)?", value.strip())
    if not match:
        return None
    try:
        return date(int(match[1]), int(match[2]), int(match[3] or 1)).isoformat()
    except ValueError:
        return None


def authors(box):
    result = []
    for key, roles in (
        ("作者", ("writer",)), ("原作", ("writer",)),
        ("作画", ("penciller", "inker", "colorist", "letterer", "cover")),
        ("插图", ("penciller", "inker", "colorist", "letterer", "cover")),
        ("译者", ("translator",)),
    ):
        for name in names(box.get(key)):
            for role in roles:
                item = {"name": name, "role": role}
                if item not in result:
                    result.append(item)
    return result


def common(subject):
    fields = {
        "title": subject.get("name_cn") or subject.get("name"),
        "summary": textwrap.dedent(subject.get("summary") or "").strip(),
        "links": [{"label": "Bangumi", "url": f"https://bgm.tv/subject/{subject['id']}"}],
    }
    return fields


def series_fields(subject):
    box, fields = infobox(subject), common(subject)
    tags = bangumi_tags(subject.get("tags") or [])
    fields["tags"] = tags
    platform = subject.get("platform")
    fields["genres"] = [platform] if isinstance(platform, str) and platform else []
    publishers = names(box.get("出版社"))
    if publishers:
        fields["publisher"] = publishers[0]
    count = next((subject.get(key) for key in ("volumes", "eps", "total_episodes")
                  if isinstance(subject.get(key), int)), None)
    if count is None:
        for key in ("册数", "冊数", "卷数", "巻数", "册數", "冊數", "卷數", "巻數", "话数", "話數", "话數", "話数"):
            match = re.search(r"\d+", str(box.get(key) or ""))
            if match:
                count = int(match[0])
                break
    if count is not None and count > 0:
        fields["totalBookCount"] = count
    state = next((status(box[key]) for key in ("状态", "连载状态", "刊行状态")
                  if status(box.get(key))), None)
    if state is None:
        state = next((status(tag["name"]) for tag in subject.get("tags") or []
                      if isinstance(tag, dict) and tag.get("name") in STATUS_TAGS), None)
    if "结束" in box or "完结" in box or box.get("连载结束") or count and count > 0:
        state = "ENDED"
    if state:
        fields["status"] = state
    if subject.get("age_rating") in (0, 1, 2):
        fields["ageRating"] = {0: 0, 1: 15, 2: 18}[subject["age_rating"]]
    elif subject.get("nsfw") is True:
        fields["ageRating"] = 18
    elif subject.get("nsfw") is None and any(tag in {
        "エロ", "官能", "乱交", "SM", "触手", "鬼畜", "催眠", "扶她", "母系", "熟女",
        "调教", "恶堕", "幼女", "R18", "成年コミック", "成人漫画", "アダルトコミック",
        "18X", "無修正", "無修", "无修", "H本", "A书", "黄漫",
    } for tag in tags):
        fields["ageRating"] = 18
    alternate = [subject.get("name"), subject.get("name_cn")]
    for key, value in box.items():
        if key in ("别名", "別名"):
            alternate.extend(names(value))
        if isinstance(value, list):
            alternate.extend(item.get("v") for item in value if isinstance(item, dict)
                             and item.get("k") in ("别名", "別名"))
    fields["alternateTitles"] = [{"label": "Bangumi", "title": title}
                                 for title in dict.fromkeys(alternate)
                                 if isinstance(title, str) and title and title != fields["title"]]
    return {key: value for key, value in fields.items() if value not in (None, "", [])}


def book_fields(subject):
    box, fields = infobox(subject), common(subject)
    fields["title"] = subject.get("name")
    ranked = sorted((tag for tag in subject.get("tags") or [] if isinstance(tag, dict)),
                    key=lambda tag: int(tag.get("count") or 0), reverse=True)[:15]
    fields["tags"] = list(dict.fromkeys(tag["name"] for tag in ranked
                                      if tag.get("name") and int(tag.get("count") or 0) > 1))
    fields["authors"] = authors(box)
    fields["releaseDate"] = release_date(subject.get("date"))
    isbn = box.get("ISBN-13") or box.get("ISBN")
    if isinstance(isbn, str):
        isbn = isbn.replace("-", "")
        if len(isbn) == 10 and isbn[:9].isdigit():
            prefix = "978" + isbn[:9]
            checksum = (10 - sum(int(char) * (1 if i % 2 == 0 else 3) for i, char in enumerate(prefix)) % 10) % 10
            isbn = prefix + str(checksum)
        if len(isbn) == 13 and isbn.isdigit():
            fields["isbn"] = isbn
    match = re.search(r"\(([^)]*)\)[^(]*$", subject.get("name") or "")
    if match:
        try:
            number = float(match[1].strip())
            fields["number"], fields["numberSort"] = format(number, "g"), number
        except ValueError:
            pass
    return {key: value for key, value in fields.items() if value not in (None, "", [])}


def mapped_subject(subject):
    if not isinstance(subject, dict) or not subject.get("id"):
        return subject
    return {**subject, "_provider_fields": series_fields(subject), "_komf_book_fields": book_fields(subject)}
