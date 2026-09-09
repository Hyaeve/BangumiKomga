# Web 控制台改造说明

## 组件边界

- `web/`：Vue 3 CDN 前端，只负责登录后的配置编辑、媒体库卡片排序、刮削记录展示和刷新按钮。
- `web/tag-picker.js`、`web/tag-picker.css`：独立的标签多选器组件。组件以 `fieldset/legend` 绘制带描边容器和嵌入标题，已选值通过胶囊标签回显，候选项通过 `teleport` 悬浮到页面层，支持多选、键盘导航、视口内定位、长列表滚动和外部点击关闭。
- `web_backend.py`：标准库 HTTP API，负责会话、配置读写、Komga 连接测试和刷新任务触发。
- `config/config.py`：Web 保存的权威配置文件，包含 Komga 连接、刮削卡片和后台账号哈希。
- `config/web_config.json`：兼容旧版本的状态文件；新保存会同步写入 `config/config.py`。
- `tools/env.py`、`api/komga_api.py`、`api/komga_sse_api.py`：原版刮削服务的认证适配层，支持 Komga 账号密码或 API Key。

## 解耦方式

前端通过 `/api/config` 保存普通 JSON，不直接依赖 Python 模块；因此可替换为其他前端或反向代理。原版刮削核心仍从 `config/config.py` 读取配置，移除 Web 层不会改变核心模块的调用方式。

后台账号密码以 SHA-256 哈希保存在 `/app/config/config.py`，不保存明文密码。默认 compose 将整个 `/app/config` 绑定到宿主机的 `./config`，因此重启或重建容器后仍会保留自定义账号密码。

Komga 支持添加多个连接，每个连接可设置自定义名称，并在账号密码/API Key 中二选一。媒体库卡片保存连接 ID、库 ID、小说过滤、缺失字段规则和 `OVERWRITE_FIELDS` 覆盖字段；未选中的字段只在 Komga 原值为空时填入，选中的字段会以 Bangumi 匹配结果覆盖。新增或编辑卡片时，点击编辑窗口的“确定”将配置写入 `config/config.py` 的 `KOMGA_LIBRARY_LIST`，顶栏不再提供单独的“保存卡片”按钮。

系统设置中的“备份”会下载完整 JSON 配置，“还原”会校验并覆盖当前配置，同时同步更新 `config/config.py`。

本地 UI 回归检查位于 `tests/test_web_ui.cjs`，使用独立的 HTTP fixture 验证卡片拼贴、标签选择、任务媒体库长列表、键盘关闭、配置保存请求以及窄屏布局，不会访问真实 Komga 或写入用户配置。安装 Playwright 后执行 `node tests/test_web_ui.cjs`；默认使用本机 Edge，可用 `BK_BROWSER_CHANNEL` 指定其他浏览器通道。截图保存在被忽略的 `test_results/web-ui/` 目录。

刮削卡片会根据绑定的 Komga 连接和媒体库读取最新系列封面。首次没有缓存时生成拼贴，之后保持当前拼贴，不再按 24 小时自动换图；卡片右键菜单的“刷新封面拼贴”或计划任务的“卡片拼贴刷新”才会重新读取最新系列并更新缓存。缓存选择保存在数据目录的 `cover_collage_cache.json`（默认位于已挂载的 `config` 目录），容器重启后仍保持不变。

计划任务支持“元数据补全”和“卡片拼贴刷新”两类功能。选择后者会显示五段 Cron 表达式输入器（例如 `0 3 * * *`），按本地时间自动执行；后者只强制刷新所选媒体库卡片的封面拼贴，不会触发元数据刮削；同时选择两项时按元数据补全、封面拼贴刷新的顺序执行。已创建的任务横条可点击非按钮区域进入编辑，立即执行、编辑、删除使用图标按钮。

2026-09-09 的拼贴布局仅调整 `web/final-overrides.css`：整组图片网格统一右倾 19 度，等距排列、统一圆角，卡片边缘裁切，边缘图片降低不透明度。保留服务名、媒体库名和漫画/小说类型；无可用封面时不渲染占位图片。封面代理优先使用 Komga 已选缩略图资源并原样转发字节，浏览器缓存通过手动刷新版本号失效，避免低质量重复压缩。

标签多选器在卡片的功能选项、缺失元数据、元数据覆盖，以及计划任务的任务功能、元数据候选、应用媒体库中复用。组件只接收 `modelValue` 和 `options`，不请求 API、不改变后端配置格式。替换组件时保留这两个数据契约及 `update:modelValue` 事件即可解耦；`OVERWRITE_FIELDS: []` 会保持全不选，不再重新加载为默认全选。

OpenAI 翻译是独立的可选集成：`tools/summary_translation.py` 使用既有的 `requests` 依赖调用 OpenAI 兼容的 `/chat/completions` 接口。配置 `OPENAI_BASE_URL`、`OPENAI_API_KEY`、`OPENAI_MODEL` 并启用 `TRANSLATE_SUMMARY_TO_ZH` 后，匹配到的简介会交给模型输出简体中文；未配置或接口失败时保留原文。删除该模块并清空四项配置即可解除该集成，不影响原版刮削。

## 增量运行

`services/service_runner.py` 不再在容器启动时无条件执行全量扫描；`poll`/`sse` 模式由各自服务执行增量流程，Web 的“全量刮削”按钮才显式触发全量任务。刷新任务由 `web_backend.py` 的互斥锁限制为同时一个，避免 `restart: always` 造成重复扫描。

## 刮削记录

刮削成功后由核心模块写入 `recordsRefreshed.db` 的 `scrape_records` 表，保存类型、条目标题、媒体库、时间和更新字段。后台通过 `GET /api/scrape-records` 分页读取记录；运行日志不再在 Web 页面展示，统一输出到容器 stdout/stderr，可使用 `docker logs` 查看。
