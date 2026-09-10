# Web 后台与增量刮削改造说明

## 新增文件

- `web_backend.py`：标准库 HTTP 服务，监听 `15600`，提供配置、Komga 媒体库读取、刷新任务和状态 API。
- `config/config.py`：Web 保存的权威配置文件，包含 `KOMGA_SERVERS`、`KOMGA_LIBRARY_LIST` 和后台账号哈希，原版核心可直接导入。
- `config/web_config.json`：旧版本兼容状态文件，保存时与 `config/config.py` 同步。
- `web/index.html`、`web/config.js`、`web/style.css`：后台控制台页面和刮削记录列表。

## 修改文件

- `main.py`：先启动 Web 服务；首次安装没有 `config.py` 时等待页面保存配置；配置变化后自动重启独立刮削子进程，使运行模式与媒体库监听范围即时生效。
- `services/runtime_service.py`：独立运行原版刮削服务，避免重载配置时影响 Web 页面。
- `services/library_selection.py`：无副作用的媒体库卡片过滤函数，供多 Komga 实时监听和单元测试复用。
- `services/service_runner.py`：移除启动时无条件全量刷新；`once` 模式保持进程常驻，避免 Docker 重启策略反复扫库。
- `core/refresh_metadata.py`：复用 `recordsRefreshed.db` 的系列/书籍记录；已成功匹配的系列仅在媒体库卡片指定字段缺失时重新匹配；`OVERWRITE_FIELDS` 控制字段级覆盖，其他字段仅补充空值。
- `tools/summary_translation.py`：可选的 OpenAI 兼容简介翻译适配层，不影响未启用翻译的原版流程。
- `config/config.template.py`：默认服务模式调整为 `sse` 实时监控。
- `Dockerfile`：声明容器端口 `15600`。

## 耦合与解耦

Web 层只通过保存动作生成原版可导入的 `config/config.py`，刮削核心仍使用原有 API、数据库和配置变量。移除 `web_backend.py` 及 Web 静态文件后，原版命令行配置和核心模块仍可独立运行；保留 `config/config.py` 与 `recordsRefreshed.db` 即可继续使用原版服务。

## API

- `GET /api/config`、`POST /api/config`
- `GET /api/config/backup`、`POST /api/config/restore`
- `GET /api/komga/libraries`
- `GET /api/komga/collections`
- `GET /api/status`
- `GET /api/scrape-records?limit=100&offset=0`
- `GET /api/scrape-records/stats`：返回总记录数、今日刮削、成功数和错误数
- `GET /api/komga/previews?server_id=...&library_id=...`：读取指定库的封面拼贴选择；首次无缓存时生成，之后只读缓存，追加 `refresh=1` 才会重新读取最新系列
- `GET /api/komga/cover?...`：鉴权代理 Komga 封面图片，优先转发已选缩略图原始字节
- `POST /api/refresh`，请求体 `{ "full": false }` 为增量，`true` 为全量
- `POST /api/tasks`：保存计划任务；`functions` 支持元数据补全和卡片拼贴刷新，后者可设置五段 Cron 表达式 `cron`
- `POST /api/tasks/run`：立即运行计划任务；后台调度器同时按本地时间 Cron 自动运行启用的任务

封面拼贴缓存写入数据目录的 `cover_collage_cache.json`（默认位于已挂载的 `config` 目录），不属于 `config/config.py` 的业务配置；删除该文件会让对应媒体库在下次读取时重新生成初始拼贴。

运行日志同时输出至容器 stdout/stderr，Web 运行日志页面提供操作审计与计划任务日志查询。

## 2026-09-10 交互与翻译修复

- `tools/translation_task.py` 独立执行计划任务简介翻译，不依赖刮削增量时间戳，分页遍历所选 Komga 服务的媒体库及卷册。空简介或已锁定简介跳过；中文简介直接锁定；其他简介翻译成功后覆盖并锁定。AI 请求后再次检查锁定与原文，避免覆盖期间用户的修改。翻译失败保留原文且不锁定。
- `tools/summary_translation.py` 接受当前 Web 配置，避免计划任务使用过期的模块级 AI 配置。刮削核心仍可沿用原来的调用方式。
- `web_backend.py` 在查询记录时后台补全旧记录路径，每批最多 20 条，失败后至少间隔五分钟重试。仅使用数据库唯一匹配的 Komga ID 查询真实 `url`，并校验媒体库；跨服务媒体库 ID 重复或缺少历史 ID 时不猜测路径。路径是否完整取决于 Komga 返回值与账号权限。
- `web/tag-picker.js` 统一单选服务与媒体库的浮层样式，元数据及应用媒体库支持全选/全部取消。`web/floating-tooltip.js` 将完整文本提示挂载到页面顶层，避免表格裁切；Esc 优先关闭下拉浮层，再关闭编辑窗口。
- 卡片前端复用已有封面补足九张拼贴，不改动手动/计划刷新机制，也不重新压缩原图。无封面时保持空背景。

解耦时可移除独立翻译任务模块及 `_translate_task_libraries` 调用，保留原刮削路径；提示层脚本仅依赖 `data-tooltip` 属性，不依赖后端接口。修改由 `tests/test_translation_task.py`、`tests/test_web_backend.py` 和 `tests/test_web_ui.cjs` 覆盖。

### AI 与路径联调

- 新记录增加 `komga_id`、`server_id`，数据库自动补列。路径统一通过 `tools/komga_path.py` 提取；列表缺失时查询详情。记录按服务分组，避免不同服务的同名条目合并。
- 旧记录优先使用已存 ID；没有 ID 时按原名查找原系列，再限定该系列查找卷册的文件名或元数据标题。只有唯一精确匹配才回填，不猜测磁盘路径。
- AI URL 可填写域名、带 `/v1` 的基础地址或完整 `/chat/completions` 地址，支持文本及文本数组响应；不强制指定模型可能不支持的 temperature 参数。连接超时 10 秒、响应超时 120 秒，失败保留原文且不锁定。
- `tests/test_integration_http.py` 使用本地 HTTP 服务运行真正的 requests 客户端，验证 AI 请求、Komga 查询/PATCH、简介锁定、记录落库、改名后路径回填及失败保护，不需要生产密钥。
- 真实部署可运行 `docker exec bangumikomga python scripts/check_integrations.py`。该命令读取容器当前配置，向 AI 发送一次固定测试文本，并只读查询已配置媒体库的真实路径；不修改 Komga 元数据，不输出密钥或实际路径。失败时退出码为 1。真实配置不在开发工作区时，本地 HTTP 测试不等同于生产联调通过。

### 计划任务 AI 翻译

界面名称由“简介翻译”改为“AI翻译”，兼容保留原配置功能 ID `summary_translation`。新任务必须选择元数据，支持 `title`、`summary`、`publisher`、`authors`；旧任务没有字段配置时继续按简介处理，不会自动扩大翻译范围。

`tools/translation_task.py` 按字段读取对应 `*Lock`，仅处理选中且非空、未锁定的字段。中文内容直接锁定，其他内容经 AI 翻译成功后覆盖并锁定；失败字段不覆盖、不锁定。写入前重新读取详情，逐字段跳过期间发生变更或被锁定的内容。作者保持原有列表结构及职责，只翻译姓名，任一姓名失败则整个作者字段保留原值。副标题、别名和标题排序不参与。接口中不存在的字段跳过，记录只包含本次实际处理的字段。

侧栏采用一致的 420ms 宽度/正文位移曲线，固定图标位置，移除收缩时的即时居中切换与标签宽度动画；尊重系统减少动态效果设置。浏览器回归逐帧检查图标位置以及侧栏和正文同步。

### 元数据修正与 AI 补全

- 新任务功能 `metadata_correction` 使用文档/编辑笔图标；副功能 `operations` 可选 `simplify`（繁转简）、`extract_title`（标题提取）、`include_locked`（包含锁定项）。默认均不选，至少选择一种实际修正功能；包含锁定项必须单独明确勾选，不能通过全选自动带入。
- `tools/correction_task.py` 使用项目已有 `zhconv` 库繁转简，仅处理选中字段的文本；作者只处理姓名并保留职责。标题提取只作用于 `title`，不会改副标题/别名；先取书名号，其次多个方括号的第一组或独占整个名称的唯一方括号，否则调用已配置 AI。未配置或识别失败时标题保持原值。两项同时选择时先提取再繁转简。
- 修正不自动锁定/解锁字段，保留原锁定状态；默认跳过已锁定项，只有明确包含锁定项时可改写其值。写入前检查字段是否被并发修改，无变化不写入、不产生修正记录。
- 任务配置的 `operations`、`ai_completion`、`fields`、`card_ids` 均保存在 `config/config.py` 的 `METADATA_TASKS` 中，随配置备份/还原。旧配置缺省时副功能关闭。
- 元数据补全新增 `ai_completion` 开关，默认关闭。`services/metadata_task.py` 按服务隔离原刮削核心配置、每批最多 100 个系列，传递所选字段，只补选中且空缺、未锁定的值；取消了原计划任务仅调用增量轮询却忽略字段范围的问题。
- `core/refresh_metadata.py` 只在所有正常匹配步骤都没有结果时调用 `tools/ai_completion.py`。AI 请求使用当前 URL 对应的 `/responses` 接口和 `web_search` 工具，要求实际完成搜索、返回来源引用和字段级来源 URL，才接受类型有效的字段；日志记录来源。接口不支持搜索、身份不明、无来源或请求失败时保留原值；不使用模型记忆代替搜索。封面不会由 AI 生成或下载。
- AI补全不会覆盖非空值或锁定值，不自动锁定新值；写入前再次读取 Komga 校验，并记录实际写入字段及文件路径。元数据操作栏统一将 `summaryLock` 等显示为“简介锁定”等中文。

解耦点：`tools/title_rules.py` 只实现确定性提取；`tools/correction_task.py` 是独立修正器；`tools/ai_completion.py` 是可选搜索补全器。删除任务分发中的对应分支与 UI 候选即可停用，已有普通刮削调用未启用任务标记时保留原行为。新增单元及 HTTP 回归覆盖锁定保护、边界标题、来源验证、任务配置往返与服务隔离。真实 AI 搜索需要部署端接口支持，开发环境协议测试不表示生产配置已通过联调。

### 媒体卡片与自动刮削开关

- 侧栏与页面标题统一为“媒体卡片”。卡片右键只保留带图标的增量刮削、全量刮削、删除操作；拼贴刷新仍可通过计划任务执行。右键刮削传递 `server::library` 标识，只处理当前卡片；删除操作保存到配置。
- 卡片 `MEDIA_TYPE` 三选一：`comic` 仅漫画；`book` 为非漫画书籍（小说、画集和其他书籍）；`mixed` 包含两类。在线与离线 Bangumi 搜索共用类型过滤。旧 `IS_NOVEL_ONLY=True` 迁移为 `book`，否则为 `comic`，旧变量继续写入兼容值。
- `SCRAPE_ENABLED` 默认 `True`。设为 `False` 后仍保存卡片、预览与计划任务关联，但不进入自动 SSE/轮询工作进程。SSE 在读取系列详情前再次检查启用状态。显式右键手动执行和计划任务不受此自动开关阻止。
- 卡片简介翻译已移除，保存时清除旧卡片翻译标记，普通卡片刮削不再触发翻译；计划任务 AI 翻译保留。
- 增量刮削按上次更新时间筛选新增/变更项目；全量遍历选中媒体库的全部项目，两者都复用已有匹配结果，全量不是强制重新搜索或强制覆盖。增量时间记录改为按 Komga 地址和媒体库隔离，避免一个卡片推进其他卡片的时间记录。升级后首次增量会建立新记录，仍会利用原匹配数据库跳过已完整的匹配。
- `services/media_refresh.py` 隔离手动操作配置；`services/media_policy.py` 负责兼容配置与自动开关。自动服务在启动前筛掉停用卡片；空的已配置媒体库不会回退扫描全部 Komga 库。测试见 `tests/test_media_policy.py`。

### 任务停止、执行统计与分页（2026-09-10）

- 计划任务手动与 Cron 触发共用任务 ID、运行状态和单执行锁。运行期间播放图标切换为圆角实心停止方块；`POST /api/tasks/stop` 校验当前任务 ID，终止对应工作进程，等待进程退出后才释放执行锁。不影响其他任务或 Komga 服务本身。停止不回滚此前已完成的元数据修改，也不能撤销 Komga 已经接收的 HTTP 请求。
- 翻译、修正和拼贴刷新移到独立 `services/task_worker.py`；补全与手动刮削保留各自隔离模块，通过 `_run_managed` 管理进程生命周期，不使用无法中止的后台 Python 线程执行 AI 请求。拼贴刷新完成后重新加载磁盘缓存。
- 任务主图标点击切换启用/停用，移除独立开关按钮。停用仅阻止后续定时调度，不会隐式停止正在运行的任务；停止需点击方块按钮。操作区保留执行/停止、编辑、删除三项，移除悬浮提示框，保留读屏标签。
- 刮削记录由 SQLite 完成范围过滤、关键词搜索、分组、排序及分页，主列表上限 50 本/页；每本展开卷册另以 50 条/页读取。运行日志上限 100 条/页，搜索后再分页。接口返回筛选后 `total`，页面定期刷新当前页，避免将全部历史记录载入浏览器或 Python 再截取。
- `tools/execution_outcomes.py` 独立保存 `execution_outcomes` 统计表：按执行 ID、Komga 服务、条目类型及 ID 去重。手动与定时执行均计入；同条目多个字段只算一次，任一字段失败则归入失败，跳过项不计数。拼贴刷新以所选媒体库为处理条目。已有非结构化日志不反推成功/失败，升级后的执行才产生这些统计；统计随日志保留天数清理。
- 侧栏底部仅显示退出登录图标与文字；媒体卡片与计划任务添加按钮复用同一顶栏容器。卡片媒体类型显示漫画媒体库、书籍媒体库或混合媒体库。Bangumi 预览标题增大并与访问原地址对齐。

解耦边界：执行控制集中于 `web_backend.py` 和 `services/task_worker.py`；统计模块无执行 ID 时不写入，因此原项目独立执行流程不受统计扩展影响。分页仅改变管理端历史查询，不改变刮削数据格式。`tests/test_task_controls.py` 覆盖真实进程中止、四类任务状态与锁释放、主记录/卷册/日志分页及按条目去重统计；浏览器测试覆盖手动与模拟定时状态、图标启停、分页请求和预览对齐。
