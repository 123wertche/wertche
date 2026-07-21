# Portable Cross-Machine Delivery Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make a fresh Windows checkout reproducibly initialize project-local Python and Node/Lark dependencies, expose clear preflight remediation, and start the local workbench without committing user credentials or runtime data.

**Architecture:** `setup_project.ps1` owns deterministic project-local setup and delegates all readiness evaluation to `preflight_douyin.py`. `preflight_douyin.py` becomes the single JSON status contract shared by the CLI and workbench health API. CMD wrappers only locate the project root and invoke the project-local Python or PowerShell script.

**Tech Stack:** Windows PowerShell, Python standard library, project virtual environment, official Node Windows zip, npm, `@larksuite/cli`, unittest.

## Global Constraints

- Do not modify global PATH, registry, system Python, system Node, Chrome, ffmpeg, or Git.
- Node is pinned to `v24.17.0` x64 zip with SHA-256 `f2aa33b35b75aca5f3f7b85675a6f6423201053e9381911e64961f3bda2528ab`.
- Never print, stage, or copy `feishu-base-config.json`, tokens, cookie stores, browser profiles, or private-key material.
- Keep the workbench bound to `127.0.0.1`; only project-owned Chrome/CDP processes may be started or stopped.
- Keep Bilibili, Douyin, and Feishu support; do not add Xiaohongshu behavior.
- `ffmpeg` and Chrome are checked host prerequisites; they are not automatically installed.
- No `git push`.

---

### Task 1: Create reproducible local dependency manifests

**Files:**
- Create: `requirements.txt`
- Create: `tools/lark/package.json`
- Create: `tools/lark/package-lock.json`
- Modify: `.gitignore`
- Test: `tests/test_setup_project.py`

**Interfaces:**
- Consumes: Python package versions from current `.venv`; Lark CLI version `1.0.70`.
- Produces: files consumed by `setup_project.ps1` without relying on `.venv` or `node_modules` being committed.

- [ ] **Step 1: Write failing manifest tests**

```python
def test_dependency_manifests_pin_runtime_dependencies():
    self.assertIn("openai-whisper==", REQUIREMENTS.read_text(encoding="utf-8"))
    package = json.loads(LARK_PACKAGE.read_text(encoding="utf-8"))
    self.assertEqual(package["dependencies"]["@larksuite/cli"], "1.0.70")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `& .\.venv\Scripts\python.exe -m unittest tests.test_setup_project.SetupProjectTests.test_dependency_manifests_pin_runtime_dependencies -v`

Expected: FAIL because the manifest files do not exist.

- [ ] **Step 3: Create exact manifests**

Write `requirements.txt` with the current pinned production dependency set and `tools/lark/package.json` with exactly `@larksuite/cli: 1.0.70`; generate lockfile using the project-local Node after Task 2's downloader is available. Add `tools/node/`, `tools/lark/node_modules/`, and downloaded Node archives to `.gitignore` while retaining `tools/lark/package*.json`.

- [ ] **Step 4: Run test to verify it passes**

Run the Task 1 test again. Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
& .\tools\git\cmd\git.exe add requirements.txt tools/lark/package.json tools/lark/package-lock.json .gitignore tests/test_setup_project.py
& .\tools\git\cmd\git.exe commit -m "build: add reproducible local dependencies"
```

### Task 2: Add project-local initialization script and CMD entrypoint

**Files:**
- Create: `setup_project.ps1`
- Create: `初始化项目.cmd`
- Test: `tests/test_setup_project.py`

**Interfaces:**
- Consumes: `requirements.txt`, `tools/lark/package-lock.json`.
- Produces: `.venv`, `tools/node/node.exe`, `tools/lark/node_modules/.bin/lark-cli.cmd`; emits a JSON preflight result without secrets.

- [ ] **Step 1: Write failing setup contract tests**

```python
def test_setup_script_uses_project_local_paths_and_safe_switches():
    script = SETUP.read_text(encoding="utf-8")
    self.assertIn("[switch]$CheckOnly", script)
    self.assertIn("[switch]$SkipDownload", script)
    self.assertIn("tools\\node", script)
    self.assertIn("preflight_douyin.py", script)
    self.assertNotIn("setx PATH", script)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `& .\.venv\Scripts\python.exe -m unittest tests.test_setup_project.SetupProjectTests.test_setup_script_uses_project_local_paths_and_safe_switches -v`

Expected: FAIL because `setup_project.ps1` does not exist.

- [ ] **Step 3: Implement deterministic setup**

`setup_project.ps1` must:

```powershell
param([switch]$CheckOnly, [switch]$SkipDownload)
# resolve $PSScriptRoot; reject execution outside the repository root
# create .venv with the discovered Python only when absent
# install requirements.txt through .venv\Scripts\python.exe -m pip
# download https://nodejs.org/dist/v24.17.0/node-v24.17.0-win-x64.zip only if tools\node\node.exe is absent,
# require SHA-256 f2aa33b35b75aca5f3f7b85675a6f6423201053e9381911e64961f3bda2528ab,
# verify SHA-256 before Expand-Archive, then remove only the verified temporary archive
# invoke tools\node\npm.cmd ci --prefix tools\lark
# call .venv\Scripts\python.exe preflight_douyin.py --json
```

The script returns nonzero for failed required checks but leaves completed local setup artifacts intact. `初始化项目.cmd` calls the PowerShell script with `-ExecutionPolicy Bypass -File` and forwards arguments. It must not invoke a global Python executable after setup.

- [ ] **Step 4: Run focused tests**

Run: `& .\.venv\Scripts\python.exe -m unittest tests.test_setup_project -v`

Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
& .\tools\git\cmd\git.exe add setup_project.ps1 初始化项目.cmd tests/test_setup_project.py
& .\tools\git\cmd\git.exe commit -m "feat: add project-local setup entrypoint"
```

### Task 3: Establish a single, actionable preflight contract

**Files:**
- Modify: `preflight_douyin.py`
- Modify: `workbench_core.py`
- Modify: `local_workbench.py`
- Test: `tests/test_preflight_douyin.py`
- Test: `tests/test_workbench_core.py`

**Interfaces:**
- Produces: `{"checks": {name: {"status", "path_or_version", "hint"}}, "auth", "table", "ok"}` from `preflight_douyin.py --json`.
- Consumes: that contract in `HealthInspector.snapshot()` and `/api/health`.

- [ ] **Step 1: Add failing tests for status and no-secret output**

```python
def test_preflight_marks_missing_tool_with_hint_without_config_contents(self):
    result = preflight.build_result(root=self.root, command_runner=failing_runner)
    self.assertEqual(result["checks"]["ffmpeg"]["status"], "missing")
    self.assertIn("ffmpeg", result["checks"]["ffmpeg"]["hint"])
    self.assertNotIn("private-value", json.dumps(result))
```

```python
def test_health_uses_preflight_status_contract(self):
    state = HealthInspector(self.paths, command_runner=runner).snapshot()
    self.assertIn("hint", state["checks"]["node"])
```

- [ ] **Step 2: Run focused tests to verify failure**

Run: `& .\.venv\Scripts\python.exe -m unittest tests.test_preflight_douyin tests.test_workbench_core -v`

Expected: FAIL because checks currently contain booleans/string placeholders.

- [ ] **Step 3: Implement preflight model and health mapping**

Create a pure `build_result(root, command_runner=run_utf8_command)` function. It must detect project Python, `tools/node/node.exe` before global Node, project Lark CLI, ffmpeg, yt-dlp, Whisper, Chrome executable, config presence, target video table, read-only Lark auth verification, and CDP/bridge reachability. Assign only `ok`, `missing`, `invalid`, `not_authorized`, `unreachable`, or `not_checked`. Include no raw configuration or command stdout.

Update `HealthInspector` to use the same key names and hints; update `/api/health` only through that inspector.

- [ ] **Step 4: Run focused tests to verify pass**

Run the Task 3 test command. Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
& .\tools\git\cmd\git.exe add preflight_douyin.py workbench_core.py local_workbench.py tests/test_preflight_douyin.py tests/test_workbench_core.py
& .\tools\git\cmd\git.exe commit -m "feat: add actionable cross-machine preflight"
```

### Task 4: Document secure new-computer setup and startup behavior

**Files:**
- Modify: `README.md`
- Modify: `feishu-base-config.example.json`
- Modify: `启动工作台.cmd`
- Test: `tests/test_setup_project.py`

**Interfaces:**
- Consumes: setup command and preflight JSON from Tasks 2-3.
- Produces: a README procedure that a new Windows user can follow without guessing or exposing secrets.

- [ ] **Step 1: Write failing documentation tests**

```python
def test_readme_documents_secure_first_run_and_manual_auth_boundaries():
    text = README.read_text(encoding="utf-8")
    self.assertIn("初始化项目.cmd", text)
    self.assertIn("feishu-base-config.json", text)
    self.assertIn("不会上传", text)
```

- [ ] **Step 2: Run test to verify failure**

Run the Task 1 unittest command. Expected: FAIL until the new setup procedure is documented.

- [ ] **Step 3: Update docs and startup guard**

Document clone → `初始化项目.cmd` → secure config copy → Feishu authorization → project Chrome Douyin login → `启动工作台.cmd`. State that ffmpeg and Chrome are host prerequisites and that the preflight hint is authoritative. `启动工作台.cmd` must invoke `preflight_douyin.py --json` first and stop with an actionable message if required checks fail.

- [ ] **Step 4: Run documentation tests**

Run: `& .\.venv\Scripts\python.exe -m unittest tests.test_setup_project -v`

Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
& .\tools\git\cmd\git.exe add README.md feishu-base-config.example.json 启动工作台.cmd tests/test_setup_project.py
& .\tools\git\cmd\git.exe commit -m "docs: document secure new-computer startup"
```

### Task 5: Validate a fresh-copy workflow without user data

**Files:**
- Create: `tests/test_fresh_checkout.py`
- Modify: `README.md`

**Interfaces:**
- Consumes: staged project files and all setup/preflight entrypoints.
- Produces: verification that an isolated copy contains no ignored credentials, runtime profile, or downloaded media and exposes an executable initialization/check-only path.

- [ ] **Step 1: Write failing isolated-copy test**

```python
def test_fresh_copy_excludes_private_and_runtime_files(self):
    with tempfile.TemporaryDirectory() as temp:
        copy = make_clean_copy(PROJECT_ROOT, Path(temp))
        self.assertFalse((copy / "feishu-base-config.json").exists())
        self.assertFalse((copy / "runtime").exists())
        self.assertTrue((copy / "初始化项目.cmd").is_file())
```

- [ ] **Step 2: Run test to verify failure**

Run: `& .\.venv\Scripts\python.exe -m unittest tests.test_fresh_checkout -v`

Expected: FAIL until the test helper and checklist are supplied.

- [ ] **Step 3: Implement safe fresh-copy validation**

Use `git archive --format=zip --output <temporary zip> HEAD` plus the staged worktree overlay from `git diff --cached --binary` only in a temporary directory. Do not copy `.venv`, `tools/node`, `tools/lark/node_modules`, `runtime`, downloads, outputs, deliveries, exports, or config. Run `setup_project.ps1 -CheckOnly -SkipDownload` in the extracted copy; assert it reports missing host prerequisites without leaking secrets and does not create files outside that temporary copy.

- [ ] **Step 4: Run full verification**

Run:

```powershell
& .\tools\git\cmd\git.exe diff --cached --check
& .\.venv\Scripts\python.exe -m unittest discover -s tests -p "test_*.py" -v
& .\tools\git\cmd\git.exe status --short
```

Expected: all tests pass; only intended source, docs, tests and manifests are staged; no secret or runtime artifact is staged.

- [ ] **Step 5: Commit**

```powershell
& .\tools\git\cmd\git.exe add tests/test_fresh_checkout.py README.md
& .\tools\git\cmd\git.exe commit -m "test: verify fresh checkout readiness"
```
