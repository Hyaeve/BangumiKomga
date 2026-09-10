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
