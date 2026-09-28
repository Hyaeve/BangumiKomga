# 元数据提供商原生移植

参考本机 `komf-rs-master` 的 `crates/komf-core/src/providers`、
`config.rs` 和 `util/name_similarity.rs`，在本项目内以 Go 实现。
不运行 komf-rs 服务，不要求用户额外部署容器。已从系列级通用匹配拆分为
来源专用匹配，并接入卷册关联；仍不是 komf-rs 所有功能的完整等价实现。

## 搜索顺序

1. 首先按本项目既有标题提取顺序尝试 Bangumi。开启离线库时先查
   SQLite；离线搜索没有匹配结果才回退在线搜索，详情仍从离线库读取。
2. 所有 Bangumi 标题候选失败后，按 `priority` 从小到大遍历启用的其他
   提供商。每个提供商依次搜索全部候选，取得有效匹配后立即停止。
3. 同优先级保持下表的注册顺序，不混合多个站点的结果重新评分。
4. 所有提供商无结果后，才允许任务已启用的 AI 补全。

Bangumi 永远优先是本项目的明确要求，区别于 komf-rs 的默认优先级 100。
已有匹配仍先复用记录，不会每次重新搜索全部站点。

| 提供商配置名 | 默认优先级 | 当前接入 | 条件 |
| --- | --- | --- | --- |
| MANGA_UPDATES | 10 | API 搜索、系列详情 | 默认启用 |
| MAL | 20 | API 搜索、系列详情 | client ID 或 access token |
| ANILIST | 40 | GraphQL 搜索、系列详情 | token 可选 |
| MANGADEX | 10 | API 搜索、系列详情 | 漫画 |
| COMIC_VINE | 110 | API 搜索、系列详情、卷册 | API key、年份及封面消歧 |
| MANGA_BAKA | 10 | API 或 SQLite 搜索、系列详情 | database 可选 |
| BOOK_WALKER | 10 | SQLite 搜索、系列详情 | 兼容的本地数据库 |
| YEN_PRESS | 50 | 搜索接口、网页系列解析 | 网页结构可能变化 |
| VIZ | 70 | 网页搜索、系列解析 | 网页结构可能变化 |
| WEBTOONS | 130 | 网页搜索、系列解析 | 网页结构可能变化 |
| EHENTAI | 10 | 搜索、gdata 详情 | 站点可达性限制 |

除 MangaUpdates 外的新增来源默认关闭。参考项目仅声明但未实现的
Kodansha、Nautiljon、Hentag 不提供虚假的启用项。

## 配置与过滤

配置持久化在 `/config/config.py` 的 `METADATA_PROVIDERS` 中，
配置备份/还原包含它。受认证的 `GET /api/providers` 返回目录及当前配置，
保存复用 `POST /api/config`。目前没有专门的提供商 Web 编辑面板。

```python
METADATA_PROVIDERS = [
    {"name": "MANGA_UPDATES", "enabled": True, "priority": 10},
    {"name": "ANILIST", "enabled": True, "priority": 40,
     "matching_mode": "CLOSEST_MATCH", "title_language": "ja",
     "tags_score_threshold": 60, "tags_size_limit": 15,
     "fields": {"alternateTitles": False}},
]
```

- 名称匹配支持 EXACT / CLOSEST_MATCH。短标题要求精确匹配，其余按参考
  实现的长度分档使用编辑距离 1、2、3。Bangumi 同样不再用旧百分比分数
  重排候选；`FUZZ_SCORE_THRESHOLD` 参数仅保留调用兼容。
- 提供商站点链接可直接解析 ID，跳过关键词搜索。
- 主标题/别名去空和去重、摘要 HTML 清理、字段开关、链接去重。
  禁用写入标题不会影响匹配时使用标题。
- AniList 默认标签 rank 至少 60、最多 15；MangaUpdates 分类按 votes
  排序取前 15；MangaDex 只使用 genre/theme 标签分组。
- Bangumi 使用参考白名单、动态计数阈值、状态标签排除，并过滤
  “漫画单行本”系列结果。
- eHentai 已接入基础 namespace、黑名单及 male-only 过滤，
  尚未迁移完整 EhTagTranslation 翻译库和标题模板。
- 系列写入仍经过当前媒体卡片/任务的选中字段与锁定策略，不由提供商
  绕过这些策略。未知字段及锁状态配置会被拒绝。
- 提供商 ID 使用 `provider:名称:原始ID`，不会把外站 ID 发给 Bangumi。
- 返回封面按原始图片读取，限制大小和超时，不二次压缩；
  未返回图片、禁用封面或下载失败不会上传空内容。

## 来源专用匹配

- MangaUpdates 只用搜索结果主标题（去 Novel 后缀）选择首个结果，然后取详情。
- MAL 搜索限制 3～64 字符，搜索 DTO 的原名与别名参与匹配，再取首个命中详情。
- AniList、MangaBaka 使用命中的搜索载荷；MangaDex 使用命中载荷，卷册
  查询另行读取封面列表。不会重复使用详情标题把搜索阶段的命中否决。
- BookWalker 保留参考的主标题加别名列表字符串比较，不自行改为独立别名匹配。
- YenPress 搜索截断 128 字符、排除 audio、清理 manga/light novel 和卷号
  后缀；遍历书目分页，选择首个有编号书目，单本无编号时允许回退。
- Viz 排除数字双连字符标题，截断 100 字符并去括号查询；
  优先 digital，404 才回退 product。
- Webtoons 只在前五个搜索结果匹配。
- ComicVine 按文件夹/标题 ID 格式、年份和清理后的标题筛选；
  多候选用首卷封面 32×32 box 平均哈希、归一 Hamming 距离不超过 0.1
  消歧。无法取图、解码或比较时不猜测。
- eHentai 加入系列/目录及单本文件名 GID 识别、书名搜索变体、
  语言分组/评分排序和翻译语言标识优先；完整离线候选链仍待补齐。
- 单个候选查询出错后记录错误，继续该来源下一标题；直链详情失败允许搜索回退。

## 卷册写入

原生协议增加 `providers.books`、`providers.book` 和 `providers.associate`。
MangaDex 从封面语言优先级按卷去重；ComicVine 从 issues 取书目；
BookWalker 从 products 读取；YenPress/Viz 从书目页读取；
Webtoons 从 episodeList 读取。

关联按参考的卷号范围及版本标识执行；单本对单本可直配，但章节文件排除。
书籍、漫画及 Webtoon 使用各自编号解析。不关联的分卷不会虚构详细信息；
可按参考规则继承系列作者，但不复制系列简介/日期到所有卷册。
一卷获取失败不会阻止其他卷册；任务关闭“包含分卷”时不查询分卷。
卷册写入复用原有选中字段、覆盖、完成锁定和前后快照。

Bangumi 系列映射去掉旧默认语言、默认分级、默认总卷数和评分流派，
只输出有来源依据的值；系列标签与分卷标签分开过滤。分卷保留来源标题，
增加 ISBN-10 转 13 和日期规范化。

## 数据与兼容边界

离线数据库是外部数据文件，不是编译进 Go 的固定内容。Bangumi 的下载/
更新沿用本项目归档更新流程；BookWalker、MangaBaka 的读取器只读打开
指定文件，其数据库下载器和自动更新尚未移植。不要把任意 SQLite 文件
当作兼容数据库使用。

仍未完整对齐的部分：Bangumi 分卷关联仍用旧编号流程，person 实体补强、
eHentai 完整离线库/EhTagTranslation/标题模板、跨来源聚合、
OAuth 自动续期、每库来源配置、完整元数据后处理选项，以及部分来源
卷册作者/故事弧/出版社与发行日的详细映射。上述不是已完成功能。
MangaUpdates、MAL、AniList、MangaBaka 和 eHentai 在参考中本就无
独立卷册书目，不为它们伪造书目。
请求节流目前为单次调用内节流，尚非跨进程共享限流。

验证使用固定 API/HTML/SQLite fixture 和模拟 HTTP；未声称所有在线
站点、付费凭据或真实离线数据库已经联调。网页提供商尤其需要实际数据
继续校验。Go 原生核心未构建时会记录警告并跳过新增来源。

## 封面质量

写入 Komga 的封面优先使用匹配来源提供的原图或最大规格图片，不做二次压缩。
MangaDex 系列及分卷均使用无缩略尺寸后缀的原图；
ComicVine 系列及分卷统一按 original、super、medium、small 等规格降序选取非空地址。
其他来源保留已有的 original/raw/extraLarge/large 优先规则。
只提供单一缩略图地址的来源不能保证获得站点原图，不通过放大伪造清晰度。
严格离线 Bangumi 没有封面资源时仍保留 Komga 原封面；封面字段选择和覆盖规则不变。

## 文件边界

- `internal/providers`：独立检索、详情解析及过滤，可单独测试。
- `internal/coreprotocol`：本地 JSON 命令协议，不监听网络端口。
- `api/provider_source.py`：Python/Go 过渡层。
- `core/refresh_metadata.py`：Bangumi 优先及现有写入规则。
- `tools/provider_settings.py`：持久化配置校验。
- `tools/provider_filters.py`、`corpus/bangumi_tag_whitelist.json`：
  Bangumi 标签过滤。后者必须随镜像发布。
- `THIRD_PARTY_NOTICES.md`：参考代码及数据归属。
