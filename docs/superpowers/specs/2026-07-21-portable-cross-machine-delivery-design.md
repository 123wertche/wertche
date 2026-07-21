# 跨电脑可复现交付设计

## 目标

让 Windows 新电脑在克隆仓库后，通过项目内的一次初始化完成 Python、项目本地 Node/Lark CLI 与工作台准备；随后经由明确的预检结果完成用户自己的飞书配置、飞书授权、Chrome/抖音登录。

## 边界与约束

- 只支持本机 Windows 使用；不修改系统 PATH、注册表或全局 Python/Node 环境。
- 不提交 `.venv`、Node 模块、媒体、运行缓存、飞书配置、令牌、私钥或浏览器配置文件。
- 飞书真实配置、飞书授权和抖音登录必须由每台电脑的用户单独完成；初始化脚本不得读取或打印密钥。
- Chrome 与 ffmpeg 是宿主机前置条件；脚本只检测并提供修复提示，不自动安装或替换浏览器。
- Python 依赖与 Node/Lark CLI 版本必须固定，初始化过程仅使用项目目录中的 `.venv`、`tools/node`、`tools/lark`。

## 方案

### 初始化入口

新增 `初始化项目.cmd` 作为双击入口，调用 `setup_project.ps1`。PowerShell 脚本执行以下有界步骤：

1. 检查可用的 Python；创建或复用 `.venv`，从固定 `requirements.txt` 安装依赖。
2. 下载并校验固定版本的官方 Node Windows x64 zip 到 `tools/node`；不设置全局 PATH。
3. 用项目 Node 在 `tools/lark` 安装固定版本 `@larksuite/cli`。
4. 运行 `preflight_douyin.py --json`，输出机器可读结果和面向用户的修复建议。
5. 只有预检通过时启动工作台；否则不启动采集流程。

脚本应支持 `-SkipDownload`（离线诊断）和 `-CheckOnly`（只执行检查）两种安全模式。

### 环境与授权检查

扩展 `preflight_douyin.py` 的 JSON 输出，使每个检查含 `status`、`path_or_version` 与 `hint`：项目 Python、项目 Node、项目 Lark CLI、ffmpeg、yt-dlp、Whisper、Chrome、飞书配置、目标视频表和飞书用户授权。

飞书授权沿用只读 `lark-cli auth status --verify`；所有输出仅包含状态和命令退出结果，不包含配置内容、token 或 Base token。Chrome 检查只探测可执行文件和项目 CDP/bridge 健康状态。

工作台的 `/api/health` 复用同一状态模型并直接展示修复提示，避免页面与 CLI 的结果不一致。

### 配置与文档

保留可提交的 `feishu-base-config.example.json`；新增新电脑说明，明确从安全渠道复制真实配置、进行飞书登录/授权、在项目专用 Chrome 中登录抖音的步骤。README 只引用配置文件名，绝不记录密钥。

### 验证

新增单元测试覆盖：项目路径限制、固定下载 URL/哈希选择、离线模式不下载、缺少依赖时提示、授权失败时不泄密、工作台健康状态映射。

用临时空目录从 Git 暂存内容生成全新工作副本，验证：初始化脚本能诊断缺少的宿主机条件；已满足条件时可创建项目虚拟环境和本地 Lark CLI；工作台可启动并返回健康状态。测试不复制任何真实飞书配置、浏览器 profile 或下载文件。

## 非目标

- 不上传、同步或迁移用户密钥、飞书授权、抖音 Cookie 或 Chrome profile。
- 不打包或自动安装 Chrome/ffmpeg。
- 不执行 Git push。
