# AI博主爬取

Local ingestion scripts for tracking AI creators on Bilibili and Douyin, downloading recent videos, creating transcript artifacts, and syncing selected metadata back to Feishu Base.

## What Is Included

- `download_bili_following_latest.py`: load tracked Bilibili creators from Feishu Base, download latest videos, collect first-stage metadata, and write task records.
- `postprocess_bili_videos.py`: backfill Bilibili subtitles or Whisper transcripts for local downloads.
- `sync_bilibili_comments_to_feishu.py`: fetch and sync representative Bilibili comments into Feishu.
- `download_douyin_latest.py`: download latest videos from configured Douyin creators.
- `sync_douyin_to_feishu.py`: sync local Douyin download artifacts into Feishu.
- `enrich_douyin_feishu.py`: backfill Douyin insight fields from local artifacts.
- `publish_transcript_docs_to_feishu.py`: create Feishu docs from local transcripts and write document URLs back to Base.
- `.agents/skills/`: project-local Codex skills for repeated crawl/comment workflows.

## Local Setup

### 新电脑首次使用（Windows）

1. 克隆仓库后双击 `初始化项目.cmd`。它只在项目目录创建 `.venv`、`tools/node` 和 `tools/lark`，不会修改系统 PATH、注册表或全局 Python/Node。
2. 从安全渠道复制真实 `feishu-base-config.json` 到项目根目录；不要提交、发送或上传该文件。
3. 按预检提示安装本机的 Google Chrome 与 ffmpeg；随后完成飞书用户授权，并在“项目专用 Chrome”中自行登录抖音。
4. 双击 `启动工作台.cmd`，在浏览器打开 `http://127.0.0.1:8765/`。

飞书密钥、授权状态、抖音登录状态、Chrome profile、下载视频和转写结果均不会上传到 Git。每台电脑都必须单独完成配置和登录。

1. Copy the example config and fill in local Feishu Base values:

   ```powershell
   Copy-Item .\feishu-base-config.example.json .\feishu-base-config.json
   ```

2. Make sure the external CLIs used by the workflows are available in your shell:

   - `python`
   - `lark-cli`
   - `ffmpeg`
   - `yt-dlp` or the project Bilibili download backend
   - `whisper` for ASR post-processing
   - `node` for CDP-based comment tools

3. Runtime outputs are intentionally ignored by git. Downloaded media, transcripts, manifests, browser profiles, QR codes, and local Feishu config stay on the local machine.

## Common Commands

Run the cross-platform latest-video workflow:

```powershell
python .\download_all_platform_latest.py --platform all
```

Run Bilibili latest-video ingestion only:

```powershell
python .\download_bili_following_latest.py --videos-per-creator 3
```

Run Bilibili transcript post-processing:

```powershell
python .\postprocess_bili_videos.py --model large-v3-turbo --device cuda
```

Run Douyin latest-video download:

```powershell
python .\download_douyin_latest.py --videos-per-creator 1
```

Preview transcript doc publishing without writing Feishu:

```powershell
python .\publish_transcript_docs_to_feishu.py --dry-run
```

## 本地可视化工作台

使用项目自身的虚拟环境启动工作台：

```powershell
Set-Location "<项目目录>"
& .\.venv\Scripts\python.exe .\local_workbench.py
```

在浏览器打开 `http://127.0.0.1:8765`。该服务只监听本机，不提供公网访问、账号或多人功能。

- 支持 Douyin、Bilibili 和飞书：博主链接管理、最新视频下载、后处理/转写、评论同步、视频表导出与转写文档发布。
- 工作台继续调用现有 Python/Node 脚本，不会升级依赖、修改全局环境或显示 `feishu-base-config.json` 中的密钥。
- 飞书写入、覆盖转写或覆盖摘要字段，必须先以相同参数完成 dry-run，再输入该 dry-run 任务日志给出的确认词；确认词 30 分钟后失效。
- “危险操作”默认折叠。第一版只能预览范围并拒绝执行删除或清理，因为当前没有可验证、可限制到指定平台或博主的删除脚本。
- “启动项目专用 Chrome”只使用 `runtime/chrome-profile` 和 CDP 9333；bridge 使用端口 3457。服务停止时只会关闭自己启动的 Chrome/bridge 进程，不会影响普通浏览器。

如果状态页显示 `DevToolsActivePort`、3457 端口不可达、飞书配置缺失、Git `safe.directory` 拦截或 PowerShell 编码问题，请先运行“飞书预检”并查看任务日志。配置或授权无法确认时，页面会显示对应状态，不会猜测授权有效性。
