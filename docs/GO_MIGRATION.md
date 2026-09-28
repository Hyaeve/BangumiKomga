# Go 原生迁移

## 目标与部署边界

参考 komf-rs 的元数据提供商、Komga REST/SSE 和 Bangumi 离线索引机制，
在本项目内重新实现，不部署 komf-rs，不连接 komf-rs HTTP 服务。
目标后端语言为 Go，保留 Vue 页面、15600 端口和单容器部署方式；
Docker 仅构建 `linux/amd64`。

这是分阶段迁移，不将“有 Go 二进制”表述为“已完成全 Go 重写”。

## 当前可运行部分

- `cmd/bangumikomga-core`：原生 Go 本地命令，不监听端口。
- `internal/archive`：使用纯 Go SQLite 驱动，以只读方式查询既有
  `bangumi.sqlite3`，包括名称/别名精确查询、FTS5 trigram、短标题查询、
  条目详情和关联条目；搜索最多返回 200 个候选。
- `internal/coreprotocol`：版本化 JSON 输入输出，验证操作、条目 ID 和索引版本。
- `tools/native_core.py`：过渡桥接；通过标准输入传 JSON，不通过 shell，
  不传递 Komga 密钥；离线请求 25 秒、提供商请求 185 秒超时，
  Windows 无终端弹窗。提供商凭据仅通过标准输入传递。
- `api/bangumi_api.py`：存在 Go 二进制时，离线读取实际走 Go，
  名称规范化和匹配评分暂保留现有逻辑。
- Docker 多阶段编译 Go，最终镜像携带二进制，不要求另一个容器或服务。

现阶段索引建立、官方归档下载、在线搜索回退、REST/SSE、
Web API、认证、任务调度、Komga 写入和记录持久化仍由 Python 执行。
不删除这些模块，直到替代实现有兼容测试并真正接入。

## 构建与兼容

```powershell
go test ./...
go build -trimpath -o bin/bangumikomga-core.exe ./cmd/bangumikomga-core
```

```sh
CGO_ENABLED=0 go build -trimpath -o bin/bangumikomga-core ./cmd/bangumikomga-core
python -m unittest tests.test_native_core tests.test_archive_sqlite
```

`bin/` 不提交。默认检测项目内二进制；源码环境未构建时沿用 Python
读取器。可用 `BANGUMIKOMGA_CORE` 指定绝对路径，或设置为 `off`
进行对照诊断。已发现二进制但执行失败时，必须上报错误，
不能伪装成“没有匹配结果”而意外触发后续刮削。

Go 端查询不会创建缺失数据库，也不会修改配置或媒体库。
现有 SQLite 索引版本为 1，未知版本直接拒绝，不做猜测读取。
纯离线查库不会连接网络；严格 Bangumi 策略继续由现有数据源保证：
离线匹配未命中才在线搜索，条目详情和关联数据仍从离线库取。

## 后续移植顺序与约束

1. 提供商接口使用独立的提供商名称和条目 ID，避免不同站点数字 ID 冲突。
   首先遍历 Bangumi 的所有标题候选，再允许其他提供商回退；
   不能某个 Bangumi 候选未命中就提前用其他来源抢占结果。
2. 分批实现参考项目实际存在的提供商：MangaUpdates、MyAnimeList、
   AniList、MangaDex、BookWalker、ComicVine、YenPress、Viz、
   Webtoons、MangaBaka、eHentai。现已接入系列搜索、详情和基础过滤，
   并增加来源专用匹配及六个书目来源的卷册关联/写入，
   但未完整移植所有后处理能力，详见 `METADATA_PROVIDERS.md`。
   各来源分别验证搜索、媒体类型、详情字段、鉴权、限流和失败行为。
3. 移植归档下载与流式建库，再移植 Komga REST/SSE。保留事件按系列合并、
   队列空闲触发、持续重连、未配置媒体库隔离和正在运行期间新事件不丢失。
4. 迁移任务执行、元数据锁策略、记录快照、Web API 和登录会话。
   用相同 fixture 和 HTTP 模拟服务进行双实现对照。
5. 认证凭据和配置迁移只读取受支持的结构，不在 Go 中执行任意 `config.py`。
   未完成配置兼容、还原验证和会话验证前，不移除现有启动入口。
6. 全部功能及迁移路径验证通过后，才能删除 Python 运行时和桥接层，
   切换到单 Go 主程序镜像。保留升级与回退说明。

## 模块解耦

原生核心依赖 SQLite 索引协议和外部提供商 API。它没有 Komga 写权限，不持有登录
Cookie，也不能直接调度任务。移除 Go 核心或显式关闭它时，Python
数据源仍可读取同一数据库，便于逐步替换和定位问题。

不复制参考仓库整体工程，不修改参考仓库。后续若复制具体实现，
须单独核对文件许可证并保留归属信息。
