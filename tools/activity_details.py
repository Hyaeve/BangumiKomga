"""Human-readable audit descriptions with an explicit non-secret field list."""

FIELDS = {
    "title": "标题", "summary": "简介", "publisher": "出版商", "authors": "作者",
    "tags": "标签", "genres": "流派", "thumbnail": "封面", "links": "链接",
    "alternateTitles": "别名", "ageRating": "年龄分级", "language": "语言",
    "totalBookCount": "册数", "titleSort": "标题排序", "status": "状态",
    "number": "卷号", "numberSort": "卷号排序", "releaseDate": "发行日期", "isbn": "ISBN",
}
FUNCTIONS = {"metadata_completion": "元数据补全", "metadata_correction": "元数据修正",
             "summary_translation": "AI翻译", "card_collage_refresh": "卡片拼贴刷新"}


def field_names(values):
    return "、".join(FIELDS.get(value, str(value)) for value in values or []) or "未选择"


def target_names(targets, state):
    servers = {str(item.get("id")): item.get("name") or "Komga 服务"
               for item in state.get("KOMGA_SERVERS", [])}
    return "；".join(
        f"{servers.get(str(key).partition('::')[0], '默认 Komga 服务')} / 媒体库 ID：{str(key).partition('::')[2] or key}"
        for key in targets) or "未选择"


def task_details(task, state):
    from tools.task_lock_policy import task_lock_options
    options = task_lock_options(task)
    functions = task.get("functions") or [task.get("type", "metadata_completion")]
    rows = [f"任务：{task.get('name') or '未命名任务'}",
            "功能：" + "、".join(FUNCTIONS.get(value, value) for value in functions),
            f"应用媒体库：{target_names(task.get('card_ids', []), state)}",
            f"Cron：{task.get('cron') or '0 6 * * *'}"]
    hours = task.get("time_limit_hours") or 0
    rows.append(f"时间限制：{hours} h" if hours else "时间限制：不限时")
    if functions != ["card_collage_refresh"]:
        rows.extend([f"元数据：{field_names(task.get('fields'))}",
                     f"包含锁定：{'开启' if options['include_locked'] else '关闭'}；完成锁定：{'开启' if options['lock_completed'] else '关闭'}"])
    if "metadata_correction" in functions:
        rows.append("修正选项：" + "、".join({"simplify":"繁转简","extract_title":"标题提取"}.get(value,value)
                    for value in task.get("operations", []) if value != "include_locked"))
    if "metadata_completion" in functions:
        rows.append(f"AI补全：{'开启' if task.get('ai_completion') else '关闭'}")
    return "\n".join(rows)


def config_changes(before, after):
    rows = []
    scalar_labels = {
        "BANGUMI_KOMGA_SERVICE_TYPE": "运行模式",
        "BANGUMI_KOMGA_SERVICE_POLL_INTERVAL": "轮询间隔",
        "BANGUMI_KOMGA_SERVICE_POLL_REFRESH_ALL_METADATA_INTERVAL": "全量刷新周期",
        "RECORD_RETENTION_DAYS": "记录保留天数", "LOG_RETENTION_DAYS": "日志保留天数",
    }
    for key, label in scalar_labels.items():
        if before.get(key) != after.get(key):
            rows.append(f"{label}：{before.get(key, '未设置')} → {after.get(key, '未设置')}")
    for key, label in {"OUTBOUND_PROXY_URL":"代理地址", "BANGUMI_ACCESS_TOKEN":"Bangumi 令牌", "OPENAI_API_KEY":"AI 密钥",
                       "OPENAI_BASE_URL":"AI 接口地址", "OPENAI_MODEL":"AI 模型",
                       "KOMGA_BASE_URL":"默认 Komga 地址", "KOMGA_EMAIL":"默认 Komga 账号",
                       "KOMGA_EMAIL_PASSWORD":"默认 Komga 密码", "KOMGA_API_KEY":"默认 Komga 密钥"}.items():
        if before.get(key) != after.get(key):
            rows.append(f"{label}：已修改")
    for setting, label, identify in (
        ("KOMGA_SERVERS", "Komga 服务", lambda item: str(item.get("id"))),
        ("KOMGA_LIBRARY_LIST", "媒体卡片", lambda item: f"{item.get('SERVER_ID','')}::{item.get('LIBRARY','')}"),
        ("METADATA_TASKS", "计划任务", lambda item: str(item.get("id"))),
    ):
        previous = {identify(item): item for item in before.get(setting, [])}
        current = {identify(item): item for item in after.get(setting, [])}
        for key in dict.fromkeys([*previous, *current]):
            old, new = previous.get(key), current.get(key)
            if old == new:
                continue
            item = new or old
            action = "添加" if old is None else "删除" if new is None else "修改"
            name = target_names([key], after if new else before) if setting == "KOMGA_LIBRARY_LIST" else item.get("name") or key
            rows.append(f"{action}{label}：{name}")
            if setting == "KOMGA_LIBRARY_LIST" and new:
                rows.extend([f"  缺失元数据：{field_names(new.get('REQUIRED_FIELDS'))}",
                             f"  覆盖元数据：{field_names(new.get('OVERWRITE_FIELDS'))}",
                             f"  媒体类型：{ {'comic':'漫画','book':'书籍','mixed':'混合'}.get(new.get('MEDIA_TYPE'),'漫画') }",
                             "  功能：" + "；".join(f"{text}：{'开启' if new.get(field, default) else '关闭'}"
                                for field,text,default in (("SCRAPE_ENABLED","刮削匹配",True),("AI_RECOGNITION","AI识别",False),("SORT_VOLUMES","卷号排序",False),("LOGIN_BACKGROUND","登录背景",False)))])
            if setting == "METADATA_TASKS" and new:
                rows.append(f"  定时状态：{'启用' if new.get('enabled',True) else '停用'}")
                rows.append(task_details(new, after))
        if list(previous) != list(current) and previous.keys() == current.keys():
            rows.append(f"{label}：调整排列顺序")
    return "\n".join(rows) or "保存配置，所记录的设置项无变化"
