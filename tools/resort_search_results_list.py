from thefuzz import fuzz
from api.bangumi_model import SubjectPlatform


def compute_name_score_by_fuzzy(name: str, name_cn: str, infobox, target: str) -> int:
    """
    Use fuzzy to computes the Levenshtein distance between name, name_cn, and infobox "别名" (if exists) and the target string.
    """
    target = target.lower()
    score = fuzz.ratio(name.lower(), target)
    if name_cn:
        score = max(score, fuzz.ratio(name_cn.lower(), target))
    for item in infobox:
        if item["key"] == "别名":
            if isinstance(item["value"], (list,)):  # 判断传入值是否为列表
                for alias in item["value"]:
                    score = max(score, fuzz.ratio(alias["v"].lower(), target))
            else:
                score = max(score, fuzz.ratio(item["value"].lower(), target))
    return score


def resort_search_list(query, results, threshold, is_novel=False):
    # Keep the old call signature for workers; percentage thresholds no longer
    # replace komf's length-dependent edit-distance matcher.
    from tools.komf_matching import match_bangumi
    return match_bangumi(query, results, is_novel)
