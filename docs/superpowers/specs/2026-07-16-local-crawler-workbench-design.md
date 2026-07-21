# 本地爬虫工作台设计

## 目标

为 `ai-boshu-crawler` 增加只在本机运行的 Web 操作面板，覆盖抖音、B 站与飞书的既有流程。页面负责配置、状态、日志和安全确认；下载、转写、飞书同步和导出继续调用现有 Python/Node 脚本。

## 范围与约束

- 服务只监听 `127.0.0.1`，不提供公网监听、登录或多用户功能。
- 使用项目 `.venv`、Python 标准库和原生 HTML/CSS/JavaScript；不安装 FastAPI、uvicorn 或其他大型依赖。
- 支持抖音、B 站和飞书；不展示或执行小红书功能。
- 不输出 `feishu-base-config.json` 的 token 或环境变量中的密钥。
- 不拼接任意 shell 字符串。后端只通过动作白名单构造参数列表，并以项目目录为工作目录启动子进程。
- 文件参数必须解析到项目目录内；危险操作没有已验证后端脚本时只提供预览和拒绝执行。
- 不升级依赖、不修改全局环境、不覆盖用户已有输出；导出使用带时间戳的新文件名。

## 架构

`local_workbench.py` 是标准库 `ThreadingHTTPServer` 服务。它提供 JSON API、静态页面和一个内存任务注册表；每个后台任务通过 `subprocess.Popen` 调用已存在的脚本，把 stdout/stderr 逐行保存到任务日志，记录退出码、开始/结束时间、输出路径和失败信息。

前端仅由 `workbench/index.html`、`workbench/app.js` 和 `workbench/style.css` 组成。页面每两秒轮询活动任务和服务状态；不保存 token，也不把服务状态写入项目配置。刷新页面后，运行中的任务仍由服务内存保留；重启服务后历史任务可从 `downloads/manifests` 重新发现，但不恢复已终止的子进程。

## 模块

### 环境与 Chrome/CDP

显示项目 Python、Node、lark-cli、ffmpeg、yt-dlp、whisper、飞书配置和飞书授权状态。飞书配置只显示“已配置/缺失”。

“启动专用浏览器”只使用 `runtime/chrome-profile` 和 CDP 端口 9333；“启动 bridge”只使用项目内 `douyin_cdp_bridge.mjs`，端口 3457；“检查连接”验证两个本地端口。页面明确提示 DevToolsActivePort 缺失、bridge 不可达、Git safe.directory 拦截和 PowerShell 编码问题。

### 抖音博主管理与流程

读取/编辑 `douyin-creators.json`。保存前校验每个 URL 为 `https://www.douyin.com/user/<sec_uid>`，去除重复 URL，返回保存前预览；写入通过临时文件原子替换。

抖音动作：最新视频 dry-run、下载（可选转写、模型、CPU/CUDA、每博主数量）、飞书同步 dry-run/正式、enrich dry-run/正式、转写文档 dry-run/正式、视频表导出。下载动作始终使用主页链接、脚本自身的非置顶选择与详情响应重试逻辑。

### B 站流程

B 站动作：下载关注博主最新视频、后处理/转写、评论同步飞书、视频表导出。页面允许设置已由现有 CLI 支持的数量、评论上限、模型、设备与 dry-run；没有 CLI 参数的行为不在页面新增实现。

### 数据、任务和日志

页面显示最新 manifest、最近下载目录、视频/封面/转写文件和飞书表链接。日志接口按字节偏移返回增量日志，避免轮询时重复传输完整输出。任务 API 返回 `queued/running/succeeded/failed/rejected` 状态、退出码、错误和安全的相对输出路径。

### 危险操作

危险区默认折叠。飞书写入、覆盖转写、删除记录和本地清理均要求前置 dry-run 成功的任务 ID；写操作还要求输入服务返回的确认词。删除和清理在第一版只返回受限范围预览，并拒绝执行，因为当前仓库没有针对指定平台/博主的、可验证的删除脚本。这样不会意外清空飞书表或删除本地业务数据。

## API 边界

- `GET /api/health`：服务与依赖摘要。
- `GET /api/creators`、`PUT /api/creators`：安全读取/更新抖音博主 JSON。
- `POST /api/tasks`：固定动作和经过验证的结构化参数，返回任务 ID。
- `GET /api/tasks`、`GET /api/tasks/<id>`、`GET /api/tasks/<id>/log?offset=N`：任务与增量日志。
- `GET /api/artifacts`：最新 manifest 和项目内产物索引。
- `POST /api/danger/preview`、`POST /api/danger/confirm`：预览/拒绝未实现的删除动作，或对未来白名单删除器执行二次确认。

动作名称、允许参数和命令模板定义在单独的 Python 模块内。服务不接收 `command`、`shell`、绝对项目外路径或未定义动作。

## 失败处理

- 服务、脚本和 bridge 的异常都返回结构化错误，日志中保留非敏感摘要。
- 任务失败不会自动重跑写飞书动作；用户需查看日志后显式再次执行。
- `dry-run` 成功只在同一服务进程内作为短期确认凭据，超过 30 分钟或参数不一致时失效。
- `--overwrite`、清理和删除必须由前端明确声明，并通过后端确认词校验。

## 测试与验收

- 单元测试：动作白名单、命令构造、项目路径限制、确认词、dry-run 凭据、博主 JSON 解析/原子保存、任务状态和日志偏移。
- 冒烟测试：启动服务并访问页面；健康接口识别本地依赖；抖音 dry-run 与同步 dry-run 以任务模型返回。
- 集成测试：使用测试替身验证任务运行、日志流、manifest 发现和写飞书动作的前置 dry-run 规则；真实抓取与飞书写入仍由用户在页面显式触发。
- 安全测试：无确认词、过期 dry-run、参数不一致、项目外路径、未知动作和原始 shell 命令均被拒绝。

## 启动方式

```powershell
Set-Location <项目目录>
& .\.venv\Scripts\python.exe .\local_workbench.py
```

服务启动后显示本机 URL，例如 `http://127.0.0.1:8765`。启动脚本不会自动打开普通 Chrome，也不会启动任何抓取或飞书写入任务。
