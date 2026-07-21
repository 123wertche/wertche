# AI 博主采集工作台：项目上下文

> 供新会话继续开发。更新时间：2026-07-21。仓库：`work/ai-boshu-crawler`。

## 1. 项目目标

在 Windows 本机用一个简洁 Web 工作台控制 B 站、抖音和飞书流程：管理博主，抓取最新非置顶视频，下载、后处理/Whisper 转写，采集官方指标与封面，幂等同步飞书，发布转写文档并导出本地交付物。明确不支持小红书。

## 2. 当前目录结构

```text
ai-boshu-crawler/
├─ workbench/                  # 紧凑型前端：index.html/app.js/style.css
├─ workbench_core.py           # 白名单动作、任务队列、环境/Chrome 管理
├─ workbench_creators.py       # B站/抖音博主统一配置
├─ workbench_pipeline.py       # dry-run → 确认 → 正式执行流水线
├─ local_workbench.py          # 仅监听 127.0.0.1:8765 的 HTTP 服务
├─ start_workbench.py
├─ 启动工作台.cmd               # 一键启动入口
├─ download_* / sync_* / enrich_* / publish_*  # 采集与飞书脚本
├─ douyin_metrics.py           # 抖音官方指标纯解析逻辑
├─ transcription_device.py     # CUDA 优先、失败回退 CPU
├─ .agents/skills/             # 项目内抖音/B站评论与 CDP 工具
├─ tests/                      # Python unittest
├─ docs/superpowers/           # 已批准的设计规格和实施计划
├─ downloads/                  # 视频、转写、manifest（运行产物）
├─ deliveries/                 # 整理后的 01–09 交付目录
├─ runtime/                    # Chrome profile、PID、日志、任务状态
├─ .venv/                      # 项目专用 Python/CLI 环境
└─ feishu-base-config.json     # 私密配置；禁止输出或提交
```

## 3. 已完成的功能

- 本地工作台：单选/多选博主、随时添加、抖音/B站筛选、实时日志、任务 ID、状态轮询；默认每位博主 2 条、转写设备 `auto`。
- 两阶段安全执行：先 dry-run，再用短期确认词执行飞书写入；危险操作默认折叠。
- 环境预检：项目 Python、Node、lark-cli、ffmpeg、yt-dlp、Whisper、飞书配置/授权/目标表。
- 项目专用 Chrome/CDP：profile 在 `runtime/chrome-profile`，Chrome 端口 9333，bridge 端口 3457；不会关闭普通浏览器。
- 抖音：主页官方候选、跳过置顶、有限重试；支持精确 `--video-url ...?modal_id=...`。
- 抖音官方数据源：优先首次 `aweme/detail` Network 响应；缺失时自动降级为官方 SSR `app.videoDetail`，严格校验 `aweme_id + sec_uid`，不重放失效签名 URL。
- 指标与封面：播放、点赞、评论、转发、收藏为官方原值；封面上传前检查已有附件。整体完播率、2 秒跳出率、5 秒完播率仅在官方数据明确提供时写入。
- Whisper：优先 CUDA，CUDA 不可用自动回退 CPU；生成原始/清洗转写、JSON/SRT/TSV/VTT。
- 飞书：目标视频表固定为 `tblakZnkghpokyGT`；按“平台视频ID”幂等更新，避免重复记录、重复封面和重复文档。
- B站：下载、后处理/转写、博主同步、评论同步飞书和导出动作已接入工作台；本轮仅做过自动化测试，未做新的线上完整实跑。
- 本地整理与导出：不移动原文件，复制到 `01_视频`–`09_运行清单`；导出视频表 JSON/XLSX，XLSX 可重开、公式错误扫描为 0并完成渲染检查。
- 最近抖音实跑成功：视频 `7661277380173925683`、`7654922676779093282`；交付在 `deliveries/20260720-douyin-explicit-2/`。
- 最近验证：Python `103/103`、CDP Node `6/6` 通过；当时页面 HTTP 200、bridge 正常。2026-07-21 检查时工作台和 bridge 均未运行，需要重新启动。

## 4. 正在开发/尚未完成

- 抖音评论明细：现有 Node CDP 工具能打开页面，但两条实跑均收到官方评论接口空正文 `json_parse_failed`，且 Windows 退出时出现 `UV_HANDLE_CLOSING` 断言。不能把它解释为 0 条评论。
- 缺少正式的 `sync_douyin_comments_to_feishu.py`；当前工作台评论正式同步只覆盖 B站。抖音仅写入“数据不可用/可能风控”的状态与诊断文件。
- 工作台博主输入只接受主页 URL；精确 modal 视频 URL 已由 CLI 支持，但尚未在页面做独立输入区。
- 危险删除/清理目前只允许预览并拒绝执行；尚未实现“备份 → 列出 ID/范围 → 确认词 → 限定删除”。
- 三项留存指标在当前官方 SSR/aweme 数据中未公开，仍是数据源限制，不得推算。

## 5. 关键技术

- Python 标准库 HTTP 服务 + 线程任务队列；前端为原生 HTML/CSS/JS。
- 所有后端动作映射为固定 argv 白名单，`shell=False`，路径限制在项目目录。
- Chrome DevTools Protocol：bridge 持久连接、Network 首次响应捕获、专用 profile/PID。
- 抖音 SSR：URL 解码后读取 `app.videoDetail`，兼容 `playAddr: [{src: ...}]` 和多码率列表。
- lark-cli 用户授权访问飞书 Base/Doc；写入前 dry-run，写入后重新读取验证。
- JSON manifest 串联下载、同步、补充、文档、导出；`successes + skipped_existing` 都可作为后续作用域。
- ffmpeg/ffprobe、yt-dlp、OpenAI Whisper；GPU 自动检测与 CPU 回退。
- 测试：Python `unittest` + Node `--test`；Excel 导出使用 openpyxl，QA 使用 bundled artifact-tool 导入、扫描和渲染。

## 6. 重要文件说明

| 文件 | 作用 |
|---|---|
| `启动工作台.cmd` / `start_workbench.py` | 一键启动并打开 `http://127.0.0.1:8765/` |
| `local_workbench.py` | HTTP/API 入口，只允许 loopback |
| `workbench_core.py` | 动作白名单、确认词、任务、环境和 Chrome 生命周期 |
| `workbench_pipeline.py` | 默认 2 条、auto 设备、跨平台执行顺序与失败恢复 |
| `workbench_creators.py` | 博主校验、去重、保存、选择 |
| `download_douyin_latest.py` | 抖音候选、SSR 降级、下载、转写、manifest |
| `douyin_metrics.py` | 五项基础指标和三项留存指标的无猜测解析 |
| `sync_douyin_to_feishu.py` | 按平台视频 ID 同步、指标、封面附件幂等 |
| `enrich_douyin_feishu.py` | 摘要、路径、处理状态补充 |
| `publish_transcript_docs_to_feishu.py` | 创建飞书转写文档并回写链接 |
| `download_bili_following_latest.py` | B站最新视频采集 |
| `postprocess_bili_videos.py` | B站字幕/Whisper 后处理 |
| `sync_bilibili_comments_to_feishu.py` | B站评论抓取与飞书同步 |
| `export_feishu_video_table.py` | 全字段 JSON/XLSX 导出；长文本行高已限制 |
| `organize_douyin_artifacts.py` | 建立 01–09 交付副本，不移动原件 |
| `.agents/skills/douyin-comments/scripts/` | CDP bridge、Network 捕获、抖音评论实验工具 |
| `tests/` | 安全、去重、SSR、重试、UI、流水线和导出回归测试 |

## 7. 已知问题

- 抖音评论接口可能返回空正文或触发风控；评论明细当前“数据不可用”。
- 抖音网页官方 `play_count` 可能为 0；必须按 0 记录并说明可能未公开真实播放量。
- 三项留存率常为空；必须写 `null/数据不可用`，不能填 0 或按页面缩写推算。
- 无 CUDA 时长视频 `small` 模型 CPU 转写很慢（约 20 分钟视频曾耗时约 30 分钟）。
- README、CMD 或 PowerShell 在非 UTF-8 代码页下可能显示中文乱码，但源文件为 UTF-8；日志统一用 UTF-8。
- Codex 沙箱读 Git 时可能触发 `dubious ownership`；只读检查可用 `git -c safe.directory=<repo> ...`，不要擅自修改全局 Git 配置。
- 工作树已有大量用户未提交/未跟踪改动；绝对不能 reset、checkout 或覆盖。

## 8. 下一步

1. 运行 `启动工作台.cmd`，先执行环境/飞书预检和 Chrome/CDP 健康检查。
2. 优先修复抖音评论：捕获首次官方 comment 响应正文，修复 Node bridge 关闭断言；保留限次重试和风控说明。
3. 新增抖音评论飞书同步：以 `comment_id` 去重，以 `aweme_id` 关联视频，必须支持 dry-run 和重新读取验证。
4. 将“精确 modal 视频 URL”加入页面，并让任务结果清楚区分主页候选与指定视频。
5. 选 1 个 B站博主、1 条视频做完整线上冒烟：下载 → 转写 → 评论 → 飞书 → 导出。
6. 仅在明确提出清理需求时，实现严格限定的备份/预览/确认/删除流程。

常用验证命令：

```powershell
& .\.venv\Scripts\python.exe .\preflight_douyin.py
& .\.venv\Scripts\python.exe -m unittest discover -s tests -q
node --test .\.agents\skills\douyin-comments\scripts\douyin_cdp_capture.test.mjs
```

## 9. 不能改动/注意约束

- 不执行任何小红书功能；只支持 B站、抖音、飞书。
- 不批量升级依赖、不修改全局环境；始终优先项目 `.venv` 和项目 lark-cli。
- 不输出、复制到日志或提交 `feishu-base-config.json` 的 token/密钥。
- 飞书视频表必须是 `tblakZnkghpokyGT`；不匹配立即停止正式写入。
- 所有指标只能来自首次官方响应/官方 SSR；未知即“数据不可用”，禁止猜测。
- 平台视频 ID 是视频去重主键；附件已有 token 时跳过；record_id 必须动态查询，禁止写死到新博主。
- 写飞书、覆盖摘要/转写前必须有同参数 dry-run 和确认；删除必须额外备份、列范围并获得明确确认。
- 不移动原始下载；整理只复制。不得删除或覆盖用户既有文件。
- 只管理本项目启动的 Chrome/CDP 进程，不能影响用户其他浏览器。
- 保留当前 dirty worktree；开始修改前先检查 Git 状态并阅读本文件及现有 specs/plans。
