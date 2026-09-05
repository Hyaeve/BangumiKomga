# Web 控制台改造说明

## 组件边界

- `web/`：Vue 3 CDN 前端，只负责登录后的配置编辑、媒体库卡片排序、刮削记录展示和刷新按钮。
- `web_backend.py`：标准库 HTTP API，负责会话、配置读写、Komga 连接测试和刷新任务触发。
- `config/web_config.json`：Web 配置持久化文件；后端同时生成 `config/config.py`，保持原版服务可继续导入。
- `config/web_auth.json`：后台账号密码的 SHA-256 哈希，不保存明文密码。
- `tools/env.py`、`api/komga_api.py`、`api/komga_sse_api.py`：原版刮削服务的认证适配层，支持 Komga 账号密码或 API Key。

## 解耦方式

前端通过 `/api/config` 保存普通 JSON，不直接依赖 Python 模块；因此可替换为其他前端或反向代理。原版刮削核心仍从 `config/config.py` 读取配置，移除 Web 层不会改变核心模块的调用方式。

账号密码保存在容器路径 `/app/config/web_auth.json`，默认 compose 将其绑定到宿主机的 `./config`。不要删除该文件或使用不带 `/app/config` 数据卷的 `docker run`，否则容器重建后只能回到默认账号 `admin`、密码 `password`。

Komga 认证采用二选一：选择 API Key 时后端清空账号密码，选择账号密码时清空 API Key。媒体库卡片只保存库 ID、小说过滤和缺失字段规则；右键删除与拖拽排序均在前端完成，点击“保存卡片”后才写入配置。

## 增量运行

`services/service_runner.py` 不再在容器启动时无条件执行全量扫描；`poll`/`sse` 模式由各自服务执行增量流程，Web 的“全量刮削”按钮才显式触发全量任务。刷新任务由 `web_backend.py` 的互斥锁限制为同时一个，避免 `restart: always` 造成重复扫描。

## 刮削记录

刮削成功后由核心模块写入 `recordsRefreshed.db` 的 `scrape_records` 表，保存类型、条目标题、媒体库、时间和更新字段。后台通过 `GET /api/scrape-records` 分页读取记录；运行日志不再在 Web 页面展示，统一输出到容器 stdout/stderr，可使用 `docker logs` 查看。
