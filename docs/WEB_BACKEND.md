# Web 后台与增量刮削改造说明

## 新增文件

- `web_backend.py`：标准库 HTTP 服务，监听 `15600`，提供配置、Komga 媒体库读取、刷新任务和状态 API。
- `config/web_config.json`：Web 卡片配置的持久化文件。它与原版 `config/config.py` 解耦，删除该文件不会影响原版配置文件。
- `web/index.html`、`web/config.js`、`web/style.css`：后台控制台页面和刮削记录列表。

## 修改文件

- `main.py`：先启动 Web 服务；首次安装没有 `config.py` 时不会阻塞在交互式配置生成器，而是等待页面保存配置。
- `services/service_runner.py`：移除启动时无条件全量刷新；`once` 模式保持进程常驻，避免 Docker 重启策略反复扫库。
- `core/refresh_metadata.py`：复用 `recordsRefreshed.db` 的系列/书籍记录；已成功匹配的系列仅在媒体库卡片指定字段缺失时重新匹配；修复增量扫描缓存时间取值，并正确处理增量列表。
- `config/config.template.py`：默认服务模式调整为 `poll`。
- `Dockerfile`：声明容器端口 `15600`。

## 耦合与解耦

Web 层只通过保存动作生成原版可导入的 `config/config.py`，刮削核心仍使用原有 API、数据库和配置变量。移除 `web_backend.py` 及 Web 静态文件后，原版命令行配置和核心模块仍可独立运行；保留 `config/config.py` 与 `recordsRefreshed.db` 即可继续使用原版服务。

## API

- `GET /api/config`、`POST /api/config`
- `GET /api/komga/libraries`
- `GET /api/komga/collections`
- `GET /api/status`
- `GET /api/scrape-records?limit=100&offset=0`
- `POST /api/refresh`，请求体 `{ "full": false }` 为增量，`true` 为全量

运行日志不再通过 Web 页面或日志文件读取，统一输出到容器 stdout/stderr，使用 `docker logs bangumikomga` 查看。
