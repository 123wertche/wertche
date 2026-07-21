# Local Crawler Workbench Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a local-only web workbench that safely runs and observes the existing Douyin, Bilibili, and Feishu crawler workflows.

**Architecture:** A standard-library Python server serves a static native web UI and a JSON API on `127.0.0.1`. A focused core module owns action whitelisting, structured argument validation, safe project-relative paths, creator-file operations, task lifecycle, and dry-run confirmation proofs; `local_workbench.py` only adapts HTTP requests to that core and starts approved subprocesses.

**Tech Stack:** Python 3 standard library (`ThreadingHTTPServer`, `subprocess`, `threading`, `json`, `pathlib`, `unittest`), native HTML/CSS/JavaScript; existing project `.venv`, Python scripts, Node/CDP bridge, and lark-cli.

## Global Constraints

- Listen only on `127.0.0.1:8765`; do not add public binding, accounts, or multi-user behavior.
- Use the project `.venv`, Python standard library, and native browser APIs; do not install or upgrade dependencies or modify global tools.
- Support only Douyin, Bilibili, and Feishu. Do not expose, invoke, or add Xiaohongshu actions.
- Preserve all existing uncommitted changes and user outputs. Never reset, checkout, bulk-clean, or overwrite an existing artifact.
- Do not return tokens, config contents, authorization headers, or environment secrets. Expose only configured/missing and command/tool status.
- Never accept a raw command string, shell fragment, arbitrary executable, or project-external path from an HTTP request. Execute a fixed executable/argument list with `shell=False` and project root as `cwd`.
- Keep output paths inside the project root. Exports use timestamped new names; creator writes use a temporary sibling and atomic replace.
- Require a successful matching dry-run proof made in the same server process in the prior 30 minutes before every Feishu write or overwrite action. The backend issues and validates the confirmation phrase.
- First-release record deletion and local cleanup remain preview-only and return a rejection for execution, because this repository has no verified narrow deletion script.
- Do not hard-code video IDs, Feishu record IDs, browser PIDs, or secret configuration values.

---

## File structure

| Path | Responsibility |
| --- | --- |
| `workbench_core.py` | Pure validation, safe action builders, creator persistence, artifact indexing, task registry, and proof/confirmation policy. |
| `local_workbench.py` | Local HTTP server, API routing, JSON responses, static-file serving, process launch wiring, and dedicated Chrome/bridge lifecycle. |
| `workbench/index.html` | Accessible local workbench form, status cards, action controls, task/log display, and collapsed danger area. |
| `workbench/app.js` | API client, form serialization, polling, safe rendering, task log cursor handling, and confirmation flow. |
| `workbench/style.css` | Responsive high-contrast local-workbench layout and task-state presentation. |
| `tests/test_workbench_core.py` | Unit tests for the security-sensitive core and task behavior. |
| `tests/test_local_workbench.py` | HTTP smoke tests with a temporary project fixture and fake subprocess runner. |
| `README.md` | Local startup, intended scope, safety behavior, and troubleshooting notes. |

## Fixed action contract

The core returns `ActionSpec(action: str, argv: list[str], write_kind: str | None, output_hints: list[str])`. The only allowed crawler actions are:

| Action | Executable arguments after project Python | Write kind |
| --- | --- | --- |
| `douyin_download` | `download_douyin_latest.py`, one or more validated `--creator-url`, `--max-creators`, `--videos-per-creator`, optional `--dry-run`, `--transcribe`, `--model`, `--device` | `None` for dry-run; `download` otherwise |
| `douyin_sync` | `sync_douyin_to_feishu.py`, optional `--manifest`, `--dry-run` | `feishu` otherwise |
| `douyin_enrich` | `enrich_douyin_feishu.py`, optional `--dry-run`, user-declared `--overwrite` | `feishu` otherwise |
| `douyin_publish_docs` | `publish_transcript_docs_to_feishu.py --platform 抖音 --max-records N`, optional `--dry-run`, user-declared `--overwrite` | `feishu` otherwise |
| `bili_download` | `download_bili_following_latest.py --videos-per-creator N`, optional creator/total/comment limits, `--skip-download`, `--skip-comments` | `download` |
| `bili_postprocess` | `postprocess_bili_videos.py --latest-download-manifest --max-videos N --model M --device D`, optional `--dry-run` | `None` for dry-run; `postprocess` otherwise |
| `bili_comments_sync` | `sync_bilibili_comments_to_feishu.py --latest-download-manifest --max-videos N`, optional comment controls and `--dry-run` | `feishu` otherwise |
| `export_video_table` | `export_feishu_video_table.py --output exports/video-table-YYYYMMDD-HHMMSS` | `export` |
| `preflight` | `preflight_douyin.py` | `None` |

`chrome_start`, `bridge_start`, and `connection_check` are server-owned lifecycle actions, never browser executable paths supplied by the UI. No action receives a user-supplied output directory, manifest path outside `downloads/manifests`, BVID, aweme ID, Feishu record ID, parent token, or raw additional arguments in the first release.

### Task 1: Add the tested safety and action-building core

**Files:**
- Create: `workbench_core.py`
- Create: `tests/test_workbench_core.py`

**Interfaces:**
- Produces `WorkbenchError(message: str, status: int = 400)`, `ProjectPaths`, `CreatorStore`, `ActionSpec`, `build_action(action: str, params: dict[str, object], paths: ProjectPaths) -> ActionSpec`, `DryRunProofStore`, `TaskRecord`, and `TaskRegistry`.
- Consumes only `PROJECT_ROOT` injected as `pathlib.Path`; no module-level current-working-directory assumptions.

- [ ] **Step 1: Write failing unit tests for the command whitelist and URL/path boundaries**

```python
def test_build_douyin_download_uses_argument_list_and_validated_homepages(self):
    spec = build_action(
        "douyin_download",
        {"creator_urls": ["https://www.douyin.com/user/MS4wLjABAAAAexample"], "videos_per_creator": 1, "dry_run": True},
        self.paths,
    )
    self.assertEqual(spec.argv[:2], [str(self.paths.python), "download_douyin_latest.py"])
    self.assertIn("--creator-url", spec.argv)
    self.assertIn("--dry-run", spec.argv)
    self.assertNotIn("shell", spec.argv)

def test_build_action_rejects_unknown_action_raw_command_and_outside_manifest(self):
    with self.assertRaisesRegex(WorkbenchError, "unsupported action"):
        build_action("powershell", {"command": "Remove-Item C:\\\\"}, self.paths)
    with self.assertRaisesRegex(WorkbenchError, "inside downloads/manifests"):
        build_action("douyin_sync", {"manifest": "C:/outside.json", "dry_run": True}, self.paths)
```

- [ ] **Step 2: Run the focused test to verify it fails**

Run: `& .\.venv\Scripts\python.exe -m unittest tests.test_workbench_core.WorkbenchCoreTests.test_build_douyin_download_uses_argument_list_and_validated_homepages -v`

Expected: FAIL because `workbench_core` does not exist.

- [ ] **Step 3: Implement `ProjectPaths` and `build_action` as an explicit mapping**

```python
@dataclass(frozen=True)
class ActionSpec:
    action: str
    argv: list[str]
    write_kind: str | None
    output_hints: list[str]

def build_action(action: str, params: dict[str, object], paths: ProjectPaths) -> ActionSpec:
    builders = {
        "douyin_download": _build_douyin_download,
        "douyin_sync": _build_douyin_sync,
        "douyin_enrich": _build_douyin_enrich,
        "douyin_publish_docs": _build_douyin_publish_docs,
        "bili_download": _build_bili_download,
        "bili_postprocess": _build_bili_postprocess,
        "bili_comments_sync": _build_bili_comments_sync,
        "export_video_table": _build_export_video_table,
        "preflight": _build_preflight,
    }
    try:
        return builders[action](params, paths)
    except KeyError as exc:
        raise WorkbenchError("unsupported action", 404) from exc
```

Implement each private builder with exact flags in the Fixed action contract, `int` range checks (`1..50` for video/record limits; `0..500` for Bilibili comment limit), `model` from `{"small", "medium", "large-v3-turbo"}`, `device` from `{"cpu", "cuda"}`, and a Douyin homepage regular expression that requires `https://www.douyin.com/user/` followed by a non-empty `sec_uid`. Resolve any manifest through `ProjectPaths.manifests_root` and reject paths escaping it. Return `[str(paths.python), script_name, ...]`, not a command string.

- [ ] **Step 4: Add creator and confirmation tests, then run them to verify failure**

```python
def test_creator_store_deduplicates_and_writes_atomically(self):
    preview = self.store.preview([self.url, self.url + "?from_tab_name=main"])
    self.assertEqual(preview["normalized_urls"], [self.url])
    saved = self.store.save(preview["normalized_urls"])
    self.assertEqual(saved["count"], 1)
    self.assertEqual(json.loads(self.paths.creators.read_text(encoding="utf-8"))["creators"][0]["url"], self.url)

def test_feishu_write_requires_matching_recent_dry_run_and_confirmation_phrase(self):
    spec = ActionSpec("douyin_sync", ["python", "sync_douyin_to_feishu.py"], "feishu", [])
    proof = self.proofs.issue_from_successful_dry_run("douyin_sync", {"manifest": None}, now=100)
    self.assertTrue(self.proofs.authorize(spec, {"manifest": None}, proof.phrase, now=101))
    self.assertFalse(self.proofs.authorize(spec, {"manifest": "other.json"}, proof.phrase, now=101))
    self.assertFalse(self.proofs.authorize(spec, {"manifest": None}, proof.phrase, now=1901))
```

- [ ] **Step 5: Implement `CreatorStore` and `DryRunProofStore`**

```python
def save(self, urls: list[str]) -> dict[str, object]:
    payload = {"creators": [{"url": url} for url in urls]}
    temporary = self.path.with_suffix(self.path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(self.path)
    return {"count": len(urls), "normalized_urls": urls}

def authorize(self, spec: ActionSpec, params: dict[str, object], phrase: str, now: float) -> bool:
    proof = self._proofs.get(self._fingerprint(spec.action, params))
    return bool(proof and proof.phrase == phrase and now - proof.completed_at <= 1800)
```

Normalize a creator URL by dropping query/fragment portions, preserve its `https` scheme/host/path, reject invalid values before opening the temporary file, and fingerprint canonical JSON with SHA-256. Generate the phrase with `secrets.token_urlsafe(12)`; do not log it except in the explicit successful dry-run task response.

- [ ] **Step 6: Implement task registry tests and minimal thread-safe registry**

```python
def test_task_registry_keeps_incremental_log_offset_and_terminal_state(self):
    task = self.registry.create("preflight", ["python", "preflight_douyin.py"])
    self.registry.append_log(task.id, "line one\n")
    self.registry.append_log(task.id, "line two\n")
    chunk = self.registry.log_after(task.id, offset=len("line one\n"))
    self.assertEqual(chunk["text"], "line two\n")
    self.registry.finish(task.id, 0)
    self.assertEqual(self.registry.get(task.id).status, "succeeded")
```

Use a `threading.Lock`, UUID task IDs, statuses exactly `queued`, `running`, `succeeded`, `failed`, and `rejected`, and relative `output_hints`. Reject missing task IDs with a 404-style `WorkbenchError`.

- [ ] **Step 7: Run the core suite**

Run: `& .\.venv\Scripts\python.exe -m unittest tests.test_workbench_core -v`

Expected: PASS; tests cover the action mapping, parameter limits, source URL validation, path containment, atomic creator persistence, dry-run proof expiry/match, confirmation, and log offsets.

- [ ] **Step 8: Review the staged diff without committing user work**

Run: `git diff --check -- workbench_core.py tests/test_workbench_core.py`

Expected: no output. Do not commit unless the user explicitly asks to commit these new files; existing worktree changes must remain untouched.

### Task 2: Add process/lifecycle orchestration and project health inspection

**Files:**
- Modify: `workbench_core.py`
- Modify: `tests/test_workbench_core.py`

**Interfaces:**
- Consumes `TaskRegistry`, `ActionSpec`, and `ProjectPaths` from Task 1.
- Produces `ProcessRunner.start(spec, params) -> TaskRecord`, `HealthInspector.snapshot() -> dict[str, object]`, and `BrowserLifecycle` methods `start_chrome()`, `start_bridge()`, `status()`.

- [ ] **Step 1: Write failing tests using a fake `Popen` factory**

```python
def test_process_runner_records_streamed_output_exit_code_and_safe_cwd(self):
    task = self.runner.start(ActionSpec("preflight", ["python", "preflight_douyin.py"], None, []), {})
    self.fake_process.emit("checked Python\n")
    self.fake_process.complete(0)
    self.runner.join(task.id, timeout=1)
    finished = self.registry.get(task.id)
    self.assertEqual(finished.status, "succeeded")
    self.assertEqual(finished.exit_code, 0)
    self.assertEqual(self.popen_calls[0]["cwd"], str(self.paths.root))
    self.assertFalse(self.popen_calls[0]["shell"])
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `& .\.venv\Scripts\python.exe -m unittest tests.test_workbench_core.ProcessRunnerTests.test_process_runner_records_streamed_output_exit_code_and_safe_cwd -v`

Expected: FAIL because `ProcessRunner` is undefined.

- [ ] **Step 3: Implement `ProcessRunner` with list argv and line streaming**

```python
process = self._popen_factory(
    spec.argv,
    cwd=str(self.paths.root),
    stdin=subprocess.DEVNULL,
    stdout=subprocess.PIPE,
    stderr=subprocess.STDOUT,
    text=True,
    encoding="utf-8",
    errors="replace",
    shell=False,
)
```

Start a daemon reader thread that marks the task `running`, appends each line, waits, stores the integer exit code, and chooses `succeeded` only for `0`; all launch exceptions become a `failed` record with only the exception class and safe message. On real dry-run success, issue the proof for its paired non-dry action using the canonical parameter dictionary and append a sentence that says the proof expires in 30 minutes. Do not automatically start any follow-up action.

- [ ] **Step 4: Write and run failing health/lifecycle tests**

```python
def test_health_masks_feishu_config_and_reports_missing_tools_without_secret_contents(self):
    state = self.inspector.snapshot()
    self.assertEqual(state["feishu_config"], "configured")
    self.assertNotIn("app_secret", json.dumps(state))
    self.assertIn(state["python"]["status"], {"ok", "missing"})

def test_browser_status_requires_project_profile_and_local_ports(self):
    state = self.lifecycle.status()
    self.assertEqual(state["cdp_port"], 9333)
    self.assertEqual(state["bridge_port"], 3457)
    self.assertFalse(state["chrome"]["running"])
```

Run: `& .\.venv\Scripts\python.exe -m unittest tests.test_workbench_core.HealthAndLifecycleTests -v`

Expected: FAIL because health and lifecycle classes are undefined.

- [ ] **Step 5: Implement safe health inspection and dedicated-browser lifecycle**

```python
def _tool_state(command: list[str]) -> dict[str, str]:
    try:
        completed = subprocess.run(command, capture_output=True, text=True, timeout=8, check=False)
        return {"status": "ok" if completed.returncode == 0 else "missing", "detail": _first_line(completed.stdout or completed.stderr)}
    except (OSError, subprocess.TimeoutExpired):
        return {"status": "missing", "detail": "unavailable"}
```

Check project Python, `node --version`, project lark-cli, `ffmpeg -version`, `yt-dlp --version`, `whisper --help`, config presence, and local TCP connects to 127.0.0.1 ports 9333/3457. Never pass config content to a result. Detect the Chrome executable from approved Windows locations only, create/use `runtime/chrome-profile`, and launch it with `--remote-debugging-port=9333 --user-data-dir=<project profile>` through `Popen([...], shell=False)`. Launch only project bridge script with project `node`, `.agents/skills/douyin-comments/scripts/douyin_cdp_bridge.mjs`, and port `3457`; retain only PIDs created by this service.

- [ ] **Step 6: Run the full core suite**

Run: `& .\.venv\Scripts\python.exe -m unittest tests.test_workbench_core -v`

Expected: PASS; no real browser, bridge, or crawler process is launched by tests.

- [ ] **Step 7: Check changed files**

Run: `git diff --check -- workbench_core.py tests/test_workbench_core.py`

Expected: no output. Leave all modifications uncommitted unless the user requests a commit.

### Task 3: Expose a loopback-only HTTP and static UI server

**Files:**
- Create: `local_workbench.py`
- Create: `tests/test_local_workbench.py`
- Modify: `workbench_core.py`

**Interfaces:**
- Consumes Task 1 core types and Task 2 runner/health/lifecycle services.
- Produces `create_server(root: Path, host: str = "127.0.0.1", port: int = 8765, popen_factory=...) -> ThreadingHTTPServer` and JSON responses for all specified API endpoints.

- [ ] **Step 1: Write API smoke tests against an ephemeral loopback port**

```python
def test_health_creators_and_unknown_action_api_contract(self):
    health = self.get_json("/api/health")
    self.assertEqual(health["listen_host"], "127.0.0.1")
    creators = self.get_json("/api/creators")
    self.assertIn("urls", creators)
    rejected = self.post_json("/api/tasks", {"action": "cmd", "params": {}})
    self.assertEqual(rejected.status, 404)

def test_task_api_returns_id_and_incremental_logs(self):
    response = self.post_json("/api/tasks", {"action": "preflight", "params": {}})
    self.assertEqual(response.status, 202)
    task_id = response.body["task"]["id"]
    log = self.get_json(f"/api/tasks/{task_id}/log?offset=0")
    self.assertIn("next_offset", log)
```

- [ ] **Step 2: Run the HTTP test to verify it fails**

Run: `& .\.venv\Scripts\python.exe -m unittest tests.test_local_workbench.LocalWorkbenchHttpTests -v`

Expected: FAIL because `local_workbench` does not exist.

- [ ] **Step 3: Implement routing and response helpers**

```python
class WorkbenchHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/api/health":
            return self.json(200, self.server.app.health())
        if self.path == "/api/creators":
            return self.json(200, self.server.app.creators.read())
        if self.path.startswith("/api/tasks/") and "/log" in self.path:
            return self.json(200, self.server.app.task_log(self.path))
        if self.path == "/api/tasks":
            return self.json(200, self.server.app.tasks.list())
        if self.path == "/api/artifacts":
            return self.json(200, self.server.app.artifacts())
        return self.static_file()
```

Use a `urlsplit` parser, limit request JSON bodies to 64 KiB, require `Content-Type: application/json` for writes, return `application/json; charset=utf-8`, map `WorkbenchError.status` to responses, and use 404 for unknown paths. Serve only files resolved within `workbench/`, with exact MIME types for `.html`, `.js`, `.css`, `.svg`, and no directory listings. Set host default to `127.0.0.1`; reject any non-loopback host at construction.

- [ ] **Step 4: Implement POST and PUT boundaries**

```python
if self.path == "/api/creators":
    preview = self.server.app.creators.preview(body["urls"])
    if body.get("save") is True:
        return self.json(200, self.server.app.creators.save(preview["normalized_urls"]))
    return self.json(200, preview)
if self.path == "/api/tasks":
    return self.json(202, {"task": self.server.app.start_task(body["action"], body.get("params", {}))})
```

Implement `POST /api/danger/preview` and `POST /api/danger/confirm` as preview/reject only with a `rejected` result explaining that no verified scoped deleter exists. Implement `POST /api/chrome/start`, `POST /api/bridge/start`, and `GET /api/connection` via the service-owned lifecycle. Do not introduce a generic POST route that can launch a process.

- [ ] **Step 5: Add server shutdown tests and run all HTTP tests**

```python
def test_server_refuses_non_loopback_bind(self):
    with self.assertRaisesRegex(ValueError, "127.0.0.1"):
        create_server(self.root, host="0.0.0.0", port=0)
```

Run: `& .\.venv\Scripts\python.exe -m unittest tests.test_local_workbench -v`

Expected: PASS; tests use a temporary root and `server.shutdown()` / `server.server_close()` in teardown.

- [ ] **Step 6: Run combined tests and diff validation**

Run: `& .\.venv\Scripts\python.exe -m unittest tests.test_workbench_core tests.test_local_workbench -v; git diff --check -- local_workbench.py workbench_core.py tests/test_workbench_core.py tests/test_local_workbench.py`

Expected: all tests PASS and no diff-check output.

### Task 4: Build the local workbench UI

**Files:**
- Create: `workbench/index.html`
- Create: `workbench/app.js`
- Create: `workbench/style.css`
- Modify: `tests/test_local_workbench.py`

**Interfaces:**
- Consumes API endpoints from Task 3; the browser sends only `{action, params}` to `/api/tasks`.
- Produces user controls for dry-run and real workflows, status cards, creator preview/save, task logs, artifact display, and safe danger preview.

- [ ] **Step 1: Add static asset smoke tests**

```python
def test_root_serves_workbench_and_no_xiaohongshu_markup(self):
    response = self.get("/")
    self.assertEqual(response.status, 200)
    self.assertIn(b"Douyin", response.body)
    self.assertIn(b"Bilibili", response.body)
    self.assertNotIn(b"xiaohongshu", response.body.lower())
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `& .\.venv\Scripts\python.exe -m unittest tests.test_local_workbench.LocalWorkbenchHttpTests.test_root_serves_workbench_and_no_xiaohongshu_markup -v`

Expected: FAIL with a static-file 404.

- [ ] **Step 3: Implement semantic HTML with fixed workflow forms**

```html
<main class="workbench">
  <header><h1>AI 博主采集工作台</h1><p>仅本机运行 · 127.0.0.1</p></header>
  <section id="environment"><h2>环境与专用浏览器</h2><div id="health-cards"></div></section>
  <section id="douyin"><h2>抖音</h2><textarea id="creator-urls"></textarea><button data-creator-preview>保存前预览</button><button data-creator-save>保存博主链接</button></section>
  <section id="bilibili"><h2>B 站</h2></section>
  <section id="tasks"><h2>任务与日志</h2><ol id="task-list"></ol><pre id="task-log" aria-live="polite"></pre></section>
  <details id="danger"><summary>危险操作</summary><p>第一版仅提供范围预览，不执行删除。</p></details>
</main>
```

Create explicit labeled controls for: preflight; dedicated Chrome start; bridge start; connection check; Douyin latest dry-run; Douyin download/transcribe; Douyin sync dry-run/real; enrich dry-run/real; transcript-doc dry-run/real; Bilibili latest download; Bilibili postprocess/transcribe; Bilibili comments dry-run/real; export; artifact refresh. Use number inputs with the core maximums and select inputs for model/device. For every Feishu write/overwrite UI, show the dry-run proof phrase field only after a completed eligible dry-run; never render a config/token value.

- [ ] **Step 4: Implement API client, polling, and safe DOM rendering**

```javascript
async function request(path, options = {}) {
  const response = await fetch(path, {headers: {"Content-Type": "application/json"}, ...options});
  const payload = await response.json();
  if (!response.ok) throw new Error(payload.error || `HTTP ${response.status}`);
  return payload;
}

function appendLog(text) {
  logElement.textContent += text;
  logElement.scrollTop = logElement.scrollHeight;
}
```

Use `textContent`, not `innerHTML`, for server logs, filenames, errors, and artifact strings. Poll `/api/health`, `/api/tasks`, and `/api/artifacts` every 2 seconds while visible; fetch active task logs with each stored byte offset and update that offset from `next_offset`. Disable submit buttons while their own request is in flight, show backend rejection messages as text, and do not retry Feishu writes automatically.

- [ ] **Step 5: Implement responsive CSS and visible safety states**

```css
:root { color-scheme: light dark; font-family: system-ui, sans-serif; }
.grid { display: grid; gap: 1rem; grid-template-columns: repeat(auto-fit, minmax(18rem, 1fr)); }
.task-succeeded { border-inline-start: .35rem solid #15803d; }
.task-failed, .task-rejected { border-inline-start: .35rem solid #b91c1c; }
pre { max-block-size: 28rem; overflow: auto; white-space: pre-wrap; }
```

Keep the danger section collapsed by default, visually distinguish dry-run from real write, and keep all controls usable at 320px width with visible labels and keyboard focus.

- [ ] **Step 6: Run static and API tests**

Run: `& .\.venv\Scripts\python.exe -m unittest tests.test_local_workbench -v`

Expected: PASS, including `/`, `/workbench/app.js`, `/workbench/style.css`, loopback check, and API behavior.

- [ ] **Step 7: Manually inspect the page without launching crawler work**

Run: `& .\.venv\Scripts\python.exe .\local_workbench.py`

Expected: server prints `http://127.0.0.1:8765`; open that address in a browser, confirm all modules display, no secrets appear, danger is folded, and stop the server with `Ctrl+C`. Do not click download, sync, publish, enrich, or deletion buttons during this check.

### Task 5: Add artifact indexing, documentation, and final verification

**Files:**
- Modify: `workbench_core.py`
- Modify: `tests/test_workbench_core.py`
- Modify: `README.md`

**Interfaces:**
- Produces `ArtifactIndexer.latest() -> dict[str, object]` returned by `GET /api/artifacts`.
- Consumes project-local `downloads/manifests`, `downloads`, `outputs`, and timestamped exports only; does not mutate them.

- [ ] **Step 1: Write failing artifact-indexing tests**

```python
def test_artifact_indexer_returns_project_relative_latest_manifest_and_files_only(self):
    (self.paths.manifests_root / "douyin-latest-download-20260716.json").write_text("{}", encoding="utf-8")
    (self.paths.root / "outputs" / "video [123].mp4").parent.mkdir(exist_ok=True)
    (self.paths.root / "outputs" / "video [123].mp4").write_bytes(b"x")
    payload = ArtifactIndexer(self.paths).latest()
    self.assertEqual(payload["latest_manifests"][0], "downloads/manifests/douyin-latest-download-20260716.json")
    self.assertTrue(all(not Path(item).is_absolute() for item in payload["recent_files"]))
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `& .\.venv\Scripts\python.exe -m unittest tests.test_workbench_core.ArtifactIndexerTests -v`

Expected: FAIL because `ArtifactIndexer` is undefined.

- [ ] **Step 3: Implement read-only, bounded artifact discovery**

```python
def latest(self) -> dict[str, object]:
    manifests = sorted(self.paths.manifests_root.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)[:10]
    files = sorted(self._allowed_files(), key=lambda p: p.stat().st_mtime, reverse=True)[:40]
    return {
        "latest_manifests": [self.paths.relative(path) for path in manifests],
        "recent_files": [self.paths.relative(path) for path in files],
        "video_table_url": "https://my.feishu.cn/wiki/HifXwc4uDiaeD7kCvqocRxHCnlc?table=tblakZnkghpokyGT&view=vewIltNX4z",
    }
```

Search only `downloads`, `outputs`, and `exports`; skip directories, symlinks resolving outside root, files above 2 GiB, and config files. Do not read or return file contents. Use a timestamped output hint for the export builder so repeated runs cannot choose a prior export name.

- [ ] **Step 4: Update README with exact local operation and safety behavior**

```markdown
## 本地可视化工作台

```powershell
Set-Location "<项目目录>"
& .\.venv\Scripts\python.exe .\local_workbench.py
```

打开 `http://127.0.0.1:8765`。服务只监听本机，不读取或展示飞书密钥；飞书写入必须先在页面完成同参数 dry-run，再输入该任务返回的确认词。删除和本地清理第一版仅预览并拒绝执行。
```

Document the supported Douyin/Bilibili workflows, dedicated Chrome profile/bridge behavior, troubleshooting messages for DevToolsActivePort, port 3457, missing config, Git safe.directory, and PowerShell encoding. State that normal browsers are not stopped; only service-owned project Chrome/bridge PIDs may be stopped on shutdown.

- [ ] **Step 5: Run the complete regression suite**

Run: `& .\.venv\Scripts\python.exe -m unittest discover -s tests -p "test_*.py" -v`

Expected: PASS, including all pre-existing tests and both new workbench test modules.

- [ ] **Step 6: Run static safety scans and manual smoke validation**

Run:

```powershell
rg -n -i "xiaohongshu|shell=True|os\.system|subprocess\.run\(.*shell" .\local_workbench.py .\workbench .\workbench_core.py
git diff --check -- local_workbench.py workbench_core.py workbench tests README.md
& .\.venv\Scripts\python.exe .\local_workbench.py
```

Expected: the scan has no Xiaohongshu or shell execution matches; `git diff --check` has no output; `GET http://127.0.0.1:8765/api/health` reports `listen_host` as `127.0.0.1`; `GET /api/creators` returns URLs without secrets; an invalid `/api/tasks` request is rejected. Stop the server after testing. Do not run real crawler, Feishu write, deletion, or cleanup actions merely for this implementation verification.

- [ ] **Step 7: Review only the new workbench changes**

Run: `git status --short; git diff --check`

Expected: the workbench files and plan are visible alongside pre-existing user changes; no whitespace error. Do not stage, commit, reset, or modify unrelated files without explicit user direction.

## Spec coverage self-review

- Local loopback server, no FastAPI, no global installs: Tasks 2 and 3.
- Environment tools, secret masking, project Chrome/CDP: Task 2.
- Douyin creator management and complete workflow controls: Tasks 1 and 4.
- Bilibili latest download, postprocess/transcribe, comments sync, export: Tasks 1 and 4.
- Fixed action whitelist, task queue, log/status lifecycle: Tasks 1 through 3.
- Dry-run/confirmation requirements and preview-only destructive actions: Tasks 1 and 3.
- Manifest/artifact visibility and Feishu table link: Task 5.
- Unit, HTTP, smoke, safety, regression, UI inspection: Tasks 1 through 5.
- No platform/video data are fabricated; the workbench shows real script output or the backend’s explicit error/data-unavailable state.

Placeholder scan performed: no `TODO`, `TBD`, “implement later”, or unresolved task references are present. Action names, statuses, proof lifetime, and parameter interfaces are consistent across tasks.
