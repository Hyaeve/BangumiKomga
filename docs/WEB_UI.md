# Web 控制台改造说明

## 组件边界

- `web/`：Vue 3 CDN 前端，只负责登录后的配置编辑、媒体库卡片排序、日志展示和刷新按钮。
- `web_backend.py`：标准库 HTTP API，负责会话、配置读写、Komga 连接测试和刷新任务触发。
- `config/web_config.json`：Web 配置持久化文件；后端同时生成 `config/config.py`，保持原版服务可继续导入。
- `config/web_auth.json`：后台账号密码的 SHA-256 哈希，不保存明文密码。
- `tools/env.py`、`api/komga_api.py`、`api/komga_sse_api.py`：原版刮削服务的认证适配层，支持 Komga 账号密码或 API Key。

## 解耦方式

前端通过 `/api/config` 保存普通 JSON，不直接依赖 Python 模块；因此可替换为其他前端或反向代理。原版刮削核心仍从 `config/config.py` 读取配置，移除 Web 层不会改变核心模块的调用方式。

Komga 认证采用二选一：选择 API Key 时后端清空账号密码，选择账号密码时清空 API Key。媒体库卡片只保存库 ID、小说过滤和缺失字段规则；右键删除与拖拽排序均在前端完成，点击“保存卡片”后才写入配置。

## 增量运行

`services/service_runner.py` 不再在容器启动时无条件执行全量扫描；`poll`/`sse` 模式由各自服务执行增量流程，Web 的“全量刮削”按钮才显式触发全量任务。刷新任务由 `web_backend.py` 的互斥锁限制为同时一个，避免 `restart: always` 造成重复扫描。

## 日志读取

`GET /api/logs` 只读取日志文件尾部，默认返回最近 80 行，前端在固定高度窗口内滚动显示，避免一次性把历史日志加载进浏览器内存。
