# One-Click Crawler Workbench Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Simplify the local crawler workbench into a one-click, selectable multi-creator pipeline for Douyin and Bilibili with GPU-first transcription, one consolidated Feishu confirmation, recovery, validation, and export.

**Architecture:** Keep the standard-library loopback server and existing crawler scripts. Add focused modules for a unified creator registry, GPU selection, and a persistent pipeline state machine; expose these through narrow JSON APIs and a simplified native web UI. A small Python launcher behind `启动工作台.cmd` owns idempotent server startup and browser opening.

**Tech Stack:** Python 3 standard library, existing project `.venv`, native HTML/CSS/JavaScript, existing Node/CDP bridge, lark-cli, ffmpeg, yt-dlp, and whisper.

## Global Constraints

- Listen only on `127.0.0.1:8765`; no public binding, account system, or multi-user behavior.
- Support only Douyin, Bilibili, and Feishu; expose no Xiaohongshu action.
- Default to two latest non-pinned videos per selected creator.
- Prefer verified NVIDIA CUDA, then automatically retry only failed transcription work on CPU.
- A pipeline may automate reads, dry-runs, local downloads, and transcription, but must pause once before any Feishu write and require its matching 30-minute confirmation phrase.
- Never print, return, or persist Feishu secrets. Do not accept raw commands, shell fragments, external paths, fixed video IDs, or fixed Feishu record IDs from HTTP.
- Preserve existing uncommitted changes and user files. Use atomic configuration writes and timestamped exports; do not reset, clean, or overwrite unrelated work.
- Deletion and cleanup remain preview-only unless a verified platform/creator-scoped deleter is added separately.
- Do not install or bulk-upgrade dependencies and do not modify global environment configuration.
- Real external writes remain user-triggered from the page after the consolidated confirmation; automated tests use fakes and dry-runs.

---

## File structure

| Path | Responsibility |
| --- | --- |
| `workbench_creators.py` | Unified Douyin/Bilibili creator identity parsing, merge, selection, and atomic local persistence. |
| `workbench-creators.json` | Local additions and UI metadata; generated only when the user saves creators. |
| `transcription_device.py` | CUDA probe, device choice, GPU-failure classification, and CPU fallback helper. |
| `workbench_pipeline.py` | Persistent pipeline registry, stage state machine, single confirmation proof, subprocess sequencing, resume inspection, and retry rules. |
| `start_workbench.py` | Idempotent loopback readiness check, background service startup, and default-browser opening. |
| `启动工作台.cmd` | Double-click wrapper that invokes the project Python launcher. |
| `local_workbench.py` | Ready/health caching, creator and pipeline API routing, and application wiring. |
| `workbench_core.py` | Expanded fixed action builders and project-process primitives. |
| `download_bili_following_latest.py` | Accept selected local Bilibili creator identities and resolve dynamic Feishu creator record IDs. |
| `sync_workbench_creators_to_feishu.py` | Dry-run or idempotently create missing selected Bilibili creator rows and emit dynamic record-ID mappings. |
| `download_douyin_latest.py`, `postprocess_bili_videos.py` | Use GPU-first selection and CPU fallback without re-downloading media. |
| `workbench/index.html`, `workbench/app.js`, `workbench/style.css` | Simplified creator selection, one-click pipeline, progress, confirmation, result, and folded advanced controls. |
| `tests/test_workbench_creators.py` | Creator parsing, merge, dedupe, selection, and atomic-save tests. |
| `tests/test_transcription_device.py` | CUDA selection and CPU fallback tests. |
| `tests/test_workbench_pipeline.py` | Pipeline stages, persistence, confirmation, failure isolation, and retry tests. |
| `tests/test_start_workbench.py` | Idempotent launcher and readiness tests. |
| `tests/test_local_workbench.py`, `tests/test_workbench_core.py` | API, cache, whitelist, page contract, and regression tests. |

### Task 1: Add the unified creator registry

**Files:**
- Create: `workbench_creators.py`
- Create: `tests/test_workbench_creators.py`
- Modify: `local_workbench.py`
- Modify: `tests/test_local_workbench.py`

**Interfaces:**
- Produces `CreatorIdentity(local_id, platform, platform_id, homepage_url, display_name, enabled, source, feishu_record_id)`.
- Produces `CreatorRegistry.load(feishu_bili: list[dict] | None = None)`, `preview(urls: list[str])`, `save(creators: list[dict])`, and `select(local_ids: list[str])`.
- HTTP produces `GET /api/creators?platform=抖音|B站`, `POST /api/creators/preview`, and `PUT /api/creators`.

- [ ] **Step 1: Write failing identity and merge tests**

```python
def test_preview_recognizes_douyin_and_bilibili_homepages_and_deduplicates():
    registry = CreatorRegistry(paths)
    result = registry.preview([
        "https://www.douyin.com/user/MS4wLjABAAAAabc?from_tab_name=main",
        "https://space.bilibili.com/12345/",
        "https://space.bilibili.com/12345",
    ])
    assert [(item["platform"], item["platform_id"]) for item in result["creators"]] == [
        ("抖音", "MS4wLjABAAAAabc"),
        ("B站", "12345"),
    ]

def test_load_merges_legacy_douyin_local_and_feishu_bili_without_overwriting_sources():
    merged = registry.load(feishu_bili=[{"mid": "12345", "name": "B博主", "record_id": "rec1"}])
    assert len([item for item in merged if item.platform_id == "12345"]) == 1
    assert next(item for item in merged if item.platform_id == "12345").feishu_record_id == "rec1"
```

- [ ] **Step 2: Run the focused tests and confirm the missing-module failure**

Run: `& .\.venv\Scripts\python.exe -m unittest tests.test_workbench_creators -v`

Expected: FAIL because `workbench_creators` does not exist.

- [ ] **Step 3: Implement strict platform parsing and stable local IDs**

```python
@dataclass(frozen=True)
class CreatorIdentity:
    local_id: str
    platform: str
    platform_id: str
    homepage_url: str
    display_name: str
    enabled: bool
    source: str
    feishu_record_id: str | None = None

def parse_creator_homepage(value: str) -> tuple[str, str, str]:
    split = urlsplit(value.strip())
    normalized = urlunsplit(("https", split.netloc.lower(), split.path.rstrip("/"), "", ""))
    if split.netloc.lower() == "www.douyin.com" and split.path.startswith("/user/"):
        platform_id = split.path.removeprefix("/user/").split("/", 1)[0]
        if platform_id:
            return "抖音", platform_id, f"https://www.douyin.com/user/{platform_id}"
    if split.netloc.lower() == "space.bilibili.com" and split.path.strip("/").isdigit():
        mid = split.path.strip("/")
        return "B站", mid, f"https://space.bilibili.com/{mid}"
    raise CreatorError("主页链接无法识别；仅支持抖音 user 主页和 B站 space 主页")
```

Derive `local_id` as `sha256(f"{platform}:{platform_id}".encode()).hexdigest()[:16]`. Load legacy Douyin entries read-only, merge local entries and injected Feishu Bilibili rows by `(platform, platform_id)`, and prefer a non-empty Feishu record ID without replacing local display names.

- [ ] **Step 4: Implement atomic persistence and selection validation**

```python
def save(self, creators: list[dict[str, object]]) -> list[CreatorIdentity]:
    normalized = self._normalize_payload(creators)
    temporary = self.local_path.with_suffix(".json.tmp")
    temporary.write_text(json.dumps({"version": 1, "creators": [asdict(item) for item in normalized]}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(self.local_path)
    return normalized

def select(self, local_ids: list[str]) -> list[CreatorIdentity]:
    selected = [item for item in self.load() if item.local_id in set(local_ids) and item.enabled]
    if len(selected) != len(set(local_ids)):
        raise CreatorError("所选博主不存在或已停用")
    return selected
```

- [ ] **Step 5: Add creator API tests and wire the registry into `WorkbenchApp`**

```python
def test_creator_api_filters_platform_and_saves_previewed_items(self):
    status, preview = self.request("POST", "/api/creators/preview", {"urls": [DOUYIN_URL, BILI_URL]})
    self.assertEqual(status, 200)
    self.assertEqual({item["platform"] for item in preview["creators"]}, {"抖音", "B站"})
    status, saved = self.request("PUT", "/api/creators", {"creators": preview["creators"]})
    self.assertEqual(status, 200)
    self.assertEqual(saved["count"], 2)
```

The API returns only non-sensitive fields. It never creates a Feishu record during preview or save.

- [ ] **Step 6: Run creator and HTTP regression tests**

Run: `& .\.venv\Scripts\python.exe -m unittest tests.test_workbench_creators tests.test_local_workbench -v`

Expected: PASS with no changes to the existing `douyin-creators.json` fixture.

### Task 2: Support selected Bilibili creators and dynamic Feishu identity resolution

**Files:**
- Modify: `download_bili_following_latest.py`
- Create: `sync_workbench_creators_to_feishu.py`
- Modify: `workbench_core.py`
- Create: `tests/test_bili_creator_selection.py`
- Create: `tests/test_sync_workbench_creators.py`
- Modify: `tests/test_workbench_core.py`

**Interfaces:**
- Produces CLI flags `--creator-mid MID` (repeatable) and `--creators-json PATH` limited to the project root.
- Produces `resolve_selected_creators(config, mids, creator_file, dry_run) -> list[dict]`.
- Produces `sync_workbench_creators_to_feishu.py --creators workbench-creators.json --creator-id ID [--creator-id ID] --dry-run`, with a timestamped manifest mapping local IDs/MIDs to dynamic Feishu record IDs.
- `bili_download` action accepts `creator_mids: list[str]`, defaults `videos_per_creator` to `2`, and never accepts UI-supplied record IDs.

- [ ] **Step 1: Write failing CLI-selection tests**

```python
def test_selected_bili_mids_filter_feishu_rows_and_reject_unknown_mid_for_real_write():
    rows = [{"mid": "1", "record_id": "rec1"}, {"mid": "2", "record_id": "rec2"}]
    self.assertEqual([item["mid"] for item in resolve_selected_creators({}, ["2"], None, True, rows=rows)], ["2"])
    with self.assertRaisesRegex(RuntimeError, "缺少飞书博主记录"):
        resolve_selected_creators({}, ["3"], self.creator_file, False, rows=rows)
```

- [ ] **Step 2: Run the test and confirm the missing-function failure**

Run: `& .\.venv\Scripts\python.exe -m unittest tests.test_bili_creator_selection -v`

Expected: FAIL because selected-creator resolution is not implemented.

- [ ] **Step 3: Implement selected MID filtering and dry-run preview**

```python
def resolve_selected_creators(config, mids, creator_file, dry_run, *, rows=None):
    existing = rows if rows is not None else load_creators(config)
    by_mid = {str(item["mid"]): item for item in existing}
    local = load_local_bili_creators(creator_file) if creator_file else {}
    result = []
    for mid in dict.fromkeys(str(value) for value in mids):
        if mid in by_mid:
            result.append(by_mid[mid])
        elif dry_run and mid in local:
            result.append({**local[mid], "record_id": None, "missing_feishu_creator": True})
        else:
            raise RuntimeError(f"B站 MID {mid} 缺少飞书博主记录")
    return result
```

Dry-run manifests list missing Feishu creator rows; real download cannot start until the confirmed pipeline has created/resolved them dynamically.

- [ ] **Step 4: Expand the fixed action builder**

```python
def _build_bili_download(params, paths):
    mids = _numeric_string_list(params, "creator_mids", maximum=50)
    videos = _positive_int(params, "videos_per_creator", 2)
    args = ["--videos-per-creator", str(videos), "--creators-json", "workbench-creators.json"]
    for mid in mids:
        args.extend(["--creator-mid", mid])
    if _bool(params, "dry_run"):
        args.append("--dry-run")
    return ActionSpec("bili_download", _argv(paths, "download_bili_following_latest.py", *args), None if params.get("dry_run") else "feishu", ["downloads/manifests"])
```

- [ ] **Step 5: Write failing tests for idempotent Bilibili creator creation**

```python
def test_creator_sync_dry_run_plans_missing_mid_and_real_mode_reuses_existing_record():
    selected = [CreatorIdentity("b1", "B站", "123", "https://space.bilibili.com/123", "博主", True, "local")]
    plan = plan_creator_sync(selected, existing_rows=[])
    self.assertEqual(plan["create"][0]["mid"], "123")
    reused = plan_creator_sync(selected, existing_rows=[{"_record_id": "rec1", "B站MID": "123"}])
    self.assertEqual(reused["mapping"], {"b1": "rec1"})
    self.assertEqual(reused["create"], [])
```

- [ ] **Step 6: Implement creator sync as its own confirmed Feishu action**

Read the selected local creator IDs, list the Feishu creator table fields `博主名称`, `B站MID`, `主页链接`, and `是否持续跟踪`, and match existing rows by MID. Dry-run writes a manifest containing `create`, `reuse`, and an empty/known mapping without modifying Feishu. Real mode batch-creates only missing rows using `+record-batch-create`, re-reads the creator table, verifies every selected MID resolves to exactly one record, and writes the dynamic mapping to the manifest. Reject duplicate Feishu rows for the same MID as an ambiguous-data error rather than choosing one.

Add action `bili_creator_sync` to `build_action`; dry-run has no write kind and real mode has `write_kind="feishu"`. The pipeline runs its dry-run before the consolidated pause and its real action immediately after confirmation, then passes only selected MIDs to `bili_download`, which re-reads record IDs dynamically.

- [ ] **Step 7: Run Bilibili, creator-sync, core, and dry-run regressions**

Run: `& .\.venv\Scripts\python.exe -m unittest tests.test_bili_creator_selection tests.test_sync_workbench_creators tests.test_bili_dry_run tests.test_workbench_core -v`

Expected: PASS; dry-run creates no Feishu records, duplicate MID rows are rejected, and real mode resolves all selected MIDs dynamically.

### Task 3: Add GPU-first selection and CPU fallback

**Files:**
- Create: `transcription_device.py`
- Create: `tests/test_transcription_device.py`
- Modify: `download_douyin_latest.py`
- Modify: `postprocess_bili_videos.py`
- Modify: `workbench_core.py`

**Interfaces:**
- Produces `DeviceDecision(requested, selected, cuda_available, reason)`.
- Produces `choose_device(requested: str, probe: Callable) -> DeviceDecision` and `transcribe_with_fallback(run: Callable[[str], Path], decision) -> tuple[Path, DeviceDecision]`.
- CLI accepts `--device auto|cuda|cpu`; workbench defaults to `auto`.

- [ ] **Step 1: Write failing device selection and fallback tests**

```python
def test_auto_prefers_verified_cuda_and_falls_back_to_cpu_on_gpu_error():
    decision = choose_device("auto", probe=lambda: (True, "cuda ready"))
    calls = []
    def run(device):
        calls.append(device)
        if device == "cuda":
            raise TranscriptionDeviceError("CUDA out of memory", gpu_related=True)
        return Path("speech.txt")
    path, final = transcribe_with_fallback(run, decision)
    self.assertEqual(calls, ["cuda", "cpu"])
    self.assertEqual(final.selected, "cpu")
    self.assertIn("CUDA out of memory", final.reason)
```

- [ ] **Step 2: Run the test and confirm the missing-module failure**

Run: `& .\.venv\Scripts\python.exe -m unittest tests.test_transcription_device -v`

Expected: FAIL because `transcription_device` does not exist.

- [ ] **Step 3: Implement CUDA probe and fallback classification**

```python
def default_cuda_probe() -> tuple[bool, str]:
    command = [sys.executable, "-c", "import torch; print('1' if torch.cuda.is_available() else '0')"]
    result = subprocess.run(command, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=15, check=False)
    return result.returncode == 0 and result.stdout.strip() == "1", _safe_reason(result)

def transcribe_with_fallback(run, decision):
    try:
        return run(decision.selected), decision
    except TranscriptionDeviceError as exc:
        if decision.requested == "auto" and decision.selected == "cuda" and exc.gpu_related:
            return run("cpu"), replace(decision, selected="cpu", reason=f"GPU 降级：{exc}")
        raise
```

Classify only CUDA initialization, driver, cuDNN, allocation, and out-of-memory failures as GPU-related. Content, network, corrupt media, and permission failures do not trigger CPU retry.

- [ ] **Step 4: Integrate both transcription entry points without re-downloading**

Resolve the device immediately before calling whisper. Wrap only the existing `transcribe_audio` invocation; on CPU fallback reuse the already-created audio file and ASR directory. Add `device_requested`, `device_used`, and `device_fallback_reason` to each manifest result.

- [ ] **Step 5: Run focused and existing transcription tests**

Run: `& .\.venv\Scripts\python.exe -m unittest tests.test_transcription_device tests.test_douyin_streams tests.test_bili_creator_selection -v`

Expected: PASS; test call order is CUDA then CPU and download functions are called once.

### Task 4: Add the persistent one-click pipeline state machine

**Files:**
- Create: `workbench_pipeline.py`
- Create: `tests/test_workbench_pipeline.py`
- Modify: `workbench_core.py`

**Interfaces:**
- Produces statuses `queued`, `running`, `awaiting_confirmation`, `succeeded`, `partially_succeeded`, and `failed`.
- Produces `PipelineRegistry.create(request)`, `get(id)`, `list()`, `append_log(id, text)`, `persist(id)`, and `load_existing()`.
- Produces `PipelineRunner.start(pipeline_id)`, `confirm(pipeline_id, phrase)`, and `retry(pipeline_id, stage_name)`.

- [ ] **Step 1: Write failing stage and persistence tests**

```python
def test_pipeline_runs_all_dry_stages_then_pauses_before_any_feishu_write():
    pipeline = runner.start_request(selected_ids=["d1", "b1"], videos_per_creator=2, device="auto")
    runner.join(pipeline.id, timeout=2)
    saved = registry.get(pipeline.id)
    self.assertEqual(saved.status, "awaiting_confirmation")
    self.assertEqual(executor.actions, ["preflight", "project_prepare", "douyin_download:dry", "bili_download:dry"])
    self.assertFalse(any(item.write_kind == "feishu" for item in executor.specs))

def test_pipeline_persists_nonsecret_state_and_rejects_changed_fingerprint():
    payload = json.loads(registry.path_for(pipeline.id).read_text(encoding="utf-8"))
    self.assertNotIn("confirmation_phrase", json.dumps(payload))
    with self.assertRaisesRegex(PipelineError, "参数已变化"):
        runner.confirm(pipeline.id, phrase, request_override={"videos_per_creator": 3})
```

- [ ] **Step 2: Run the test and confirm the missing-module failure**

Run: `& .\.venv\Scripts\python.exe -m unittest tests.test_workbench_pipeline -v`

Expected: FAIL because `workbench_pipeline` does not exist.

- [ ] **Step 3: Implement canonical requests, stages, proof hashing, and atomic persistence**

```python
PIPELINE_STAGES = (
    "preflight", "project_prepare", "candidate_dry_run", "write_preview",
    "download", "transcribe", "feishu_sync", "enrich", "comments",
    "publish_docs", "verify", "export", "report",
)

def canonical_request(payload):
    return {
        "selected_creator_ids": sorted(set(payload["selected_creator_ids"])),
        "videos_per_creator": _bounded_int(payload.get("videos_per_creator", 2), 1, 50),
        "device": _choice(payload.get("device", "auto"), {"auto", "cuda", "cpu"}),
        "transcribe": bool(payload.get("transcribe", True)),
        "sync_comments": bool(payload.get("sync_comments", True)),
    }
```

Persist to `runtime/workbench/tasks/<pipeline-id>.json.tmp` then atomically replace. Store `confirmation_hash`, issued/expiry times, request fingerprint, stages, task IDs, safe relative outputs, errors, and logs; never store the plain phrase or command containing secrets.

- [ ] **Step 4: Implement dry-run sequencing and one consolidated pause**

Use selected CreatorIdentity values to build Douyin URLs and Bilibili MIDs. Execute preflight, project preparation, and platform dry-runs sequentially. Build a write preview from manifests, issue one phrase, store only its SHA-256 hash, and set `awaiting_confirmation`. Do not enqueue any Feishu-writing action before `confirm` succeeds.

- [ ] **Step 5: Implement confirmed stages, creator failure isolation, and retry rules**

After confirmation, execute per-platform download/transcription, sync, enrich, comments, document publication, re-read verification, export, and report. Track each creator/video independently. Set `partially_succeeded` when at least one selected creator succeeds and another fails. Retry only `transcribe`, `comments`, `publish_docs`, `verify`, or a failed per-creator download after rechecking existing manifests/records; never blindly retry an unknown Feishu write result.

- [ ] **Step 6: Run pipeline and core tests**

Run: `& .\.venv\Scripts\python.exe -m unittest tests.test_workbench_pipeline tests.test_workbench_core -v`

Expected: PASS for pause/confirm, expiry, changed parameters, persistence, partial success, allowed retry, and forbidden retry.

### Task 5: Add lightweight readiness, health caching, pipeline APIs, and the launcher

**Files:**
- Modify: `local_workbench.py`
- Create: `start_workbench.py`
- Create: `启动工作台.cmd`
- Create: `tests/test_start_workbench.py`
- Modify: `tests/test_local_workbench.py`

**Interfaces:**
- Produces `GET /api/ready`, cached `GET /api/health?force=0|1`, pipeline CRUD/confirm/retry routes, and `POST /api/project/start`.
- Produces `ensure_workbench(root, host, port, opener, popen_factory) -> StartResult`.

- [ ] **Step 1: Write failing readiness, cache, and launcher tests**

```python
def test_ready_does_not_run_health_commands_and_health_is_cached():
    self.assertEqual(self.get_json("/api/ready")["ready"], True)
    self.get_json("/api/health")
    self.get_json("/api/health")
    self.assertEqual(self.server.app.health_inspector.calls, 1)
    self.get_json("/api/health?force=1")
    self.assertEqual(self.server.app.health_inspector.calls, 2)

def test_launcher_reuses_ready_server_and_opens_once_without_spawning():
    result = ensure_workbench(root, opener=opened.append, popen_factory=fake_popen, probe=lambda: True)
    self.assertEqual(fake_popen.calls, [])
    self.assertEqual(opened, ["http://127.0.0.1:8765/"])
```

- [ ] **Step 2: Run the tests and confirm missing ready/cache/launcher behavior**

Run: `& .\.venv\Scripts\python.exe -m unittest tests.test_start_workbench tests.test_local_workbench -v`

Expected: FAIL because the launcher and ready/cache routes do not exist.

- [ ] **Step 3: Implement ready and 30-second health caching**

```python
def health(self, force=False):
    now = time.monotonic()
    with self._health_lock:
        if not force and self._health_cache and now - self._health_cached_at < 30:
            return self._health_cache
        value = {**self.health_inspector.snapshot(), "browser": self.lifecycle.status()}
        self._health_cache, self._health_cached_at = value, now
        return value
```

`/api/ready` returns immediately with `{ready: true, host: "127.0.0.1", port: 8765, version: 1}` and does not inspect external tools.

- [ ] **Step 4: Add pipeline APIs with strict route parsing**

`POST /api/pipelines` accepts only canonical fields. `POST /api/pipelines/<id>/confirm` accepts only `confirmation_phrase`; `retry` accepts one allowed stage name. Task/log paths validate UUID-like IDs and nonnegative offsets. Unknown keys, raw command/shell fields, and paths return 400/404 without launching a process.

- [ ] **Step 5: Implement the idempotent launcher and CMD wrapper**

```python
def ensure_workbench(root, host="127.0.0.1", port=8765, opener=webbrowser.open, popen_factory=subprocess.Popen, probe=None):
    url = f"http://{host}:{port}/"
    ready = probe or (lambda: ready_probe(host, port))
    if not ready():
        popen_factory([str(root / ".venv" / "Scripts" / "python.exe"), str(root / "local_workbench.py")], cwd=str(root), creationflags=WINDOWS_HIDDEN_FLAGS)
        wait_until_ready(ready, timeout=15)
    opener(url)
    return StartResult(url=url, reused=ready())
```

`启动工作台.cmd` contains only:

```bat
@echo off
cd /d "%~dp0"
".venv\Scripts\python.exe" "start_workbench.py"
if errorlevel 1 pause
```

- [ ] **Step 6: Run launcher and HTTP tests**

Run: `& .\.venv\Scripts\python.exe -m unittest tests.test_start_workbench tests.test_local_workbench -v`

Expected: PASS for first start, reuse, wrong service on port, failed start, ready latency, health cache, pipeline creation, confirmation, and retry rejection.

### Task 6: Replace the button grid with the simplified one-click UI

**Files:**
- Modify: `workbench/index.html`
- Modify: `workbench/app.js`
- Modify: `workbench/style.css`
- Modify: `tests/test_local_workbench.py`

**Interfaces:**
- Consumes creator and pipeline APIs from Tasks 1, 4, and 5.
- Produces creator filters/search/multi-select/add preview, default count 2, one primary pipeline button, confirmation panel, progress/result views, and folded advanced controls.

- [ ] **Step 1: Write failing static contract tests**

```python
def test_page_exposes_one_primary_pipeline_and_creator_multiselect_defaults():
    html = (PROJECT_ROOT / "workbench" / "index.html").read_text(encoding="utf-8")
    self.assertIn('id="run-pipeline"', html)
    self.assertIn('value="2"', html)
    self.assertIn('id="creator-list"', html)
    self.assertIn('id="add-creators"', html)
    self.assertIn('<details id="advanced"', html)
    self.assertNotIn('data-task-action="douyin_sync"', html)
```

- [ ] **Step 2: Run the contract test and confirm it fails against the current button grid**

Run: `& .\.venv\Scripts\python.exe -m unittest tests.test_local_workbench.LocalWorkbenchHttpTests.test_page_exposes_one_primary_pipeline_and_creator_multiselect_defaults -v`

Expected: FAIL because the simplified controls do not exist.

- [ ] **Step 3: Implement the simplified semantic layout**

Create five visible regions: status, creator selection/addition, run settings, pipeline progress/confirmation, and result summary. Move environment lifecycle and all individual actions into `<details id="advanced">`; keep dangerous operations in a separate collapsed `<details id="danger">`. The only prominent action is `<button id="run-pipeline">运行所选博主完整流程</button>`.

- [ ] **Step 4: Implement creator selection and pipeline UI state**

Use `textContent` for all server data. Store selection in a `Set` of local IDs, render filter/search without losing selection, preview multiple pasted URLs before save, and refresh the creator list after save. Submit:

```javascript
const request = {
  selected_creator_ids: [...selectedCreatorIds],
  videos_per_creator: Number(document.querySelector("#videos-per-creator").value || 2),
  device: document.querySelector("#device").value,
  transcribe: document.querySelector("#transcribe").checked,
  sync_comments: document.querySelector("#sync-comments").checked,
};
```

Poll pipeline/task/log state every 2 seconds. Poll health every 30 seconds; the manual refresh calls `force=1`. Show the confirmation input only for `awaiting_confirmation`, then post to `/confirm`. Do not auto-submit the phrase.

- [ ] **Step 5: Implement responsive states and browser-safe accessibility**

Use visible labels, keyboard-focus outlines, a minimum 44px primary button height, platform badges, selected count, stage status icons/text, and desktop/mobile grids. Do not encode success or failure by color alone.

- [ ] **Step 6: Run HTTP/static tests and perform a read-only browser inspection**

Run: `& .\.venv\Scripts\python.exe -m unittest tests.test_local_workbench -v`

Expected: PASS. Start `local_workbench.py`, open the page, verify creator add/selection layout, default 2, advanced controls folded, no console errors, and do not confirm a real pipeline during UI inspection.

### Task 7: Document, regress, and verify the complete delivery

**Files:**
- Modify: `README.md`
- Modify: `docs/superpowers/specs/2026-07-16-one-click-workbench-design.md` only if implementation reveals a factual correction

**Interfaces:**
- Documents double-click and PowerShell startup, creator management, one-click flow, confirmation, GPU fallback, outputs, and safe stop behavior.

- [ ] **Step 1: Update README with exact user operation**

Document double-clicking `启动工作台.cmd`, the equivalent PowerShell command `& .\.venv\Scripts\python.exe .\start_workbench.py`, selection/addition for both platforms, default two videos, GPU auto behavior, one confirmation, and the distinction between safe one-click stages and destructive operations.

- [ ] **Step 2: Run the complete test suite**

Run: `& .\.venv\Scripts\python.exe -m unittest discover -s tests -p "test_*.py" -v`

Expected: all existing and new tests PASS with zero failures.

- [ ] **Step 3: Run static security and file checks**

```powershell
$matches = rg -n -i "xiaohongshu|shell=True|os\.system|subprocess\.run\(.*shell|confirmation_phrase.*write_text" .\local_workbench.py .\workbench .\workbench_core.py .\workbench_pipeline.py .\workbench_creators.py .\start_workbench.py
if ($LASTEXITCODE -eq 1) { "security_scan=clean" }
git diff --check
```

Expected: `security_scan=clean` and no diff errors.

- [ ] **Step 4: Run a safe launcher and page smoke test**

Run `& .\.venv\Scripts\python.exe .\start_workbench.py`, verify `/api/ready` returns immediately, double-run the launcher and confirm one listening PID, inspect the rendered page, create a fake/test pipeline only through the test server, then stop only the test-started workbench/Chrome/bridge processes.

- [ ] **Step 5: Review the working tree without committing unrelated work**

Run: `git status --short`

Expected: new one-click workbench files are visible alongside preserved pre-existing changes. Do not stage, commit, reset, merge, or delete the unused worktree unless the user separately requests Git cleanup.

## Spec coverage self-review

- Unified Douyin/Bilibili add, select-one, select-many, and dedupe: Tasks 1 and 2.
- Default two latest non-pinned candidates: Tasks 2, 4, and 6.
- One-click startup and duplicate-process avoidance: Task 5.
- Simplified page with advanced actions folded: Task 6.
- Automated preflight, Chrome/CDP, dry-runs, download, transcription, Feishu stages, verification, and export: Task 4.
- One consolidated Feishu confirmation and parameter fingerprint: Tasks 4 and 5.
- GPU preference and CPU fallback without re-download: Task 3.
- Health caching, 2-second task polling, and restart-safe task summaries: Tasks 4 through 6.
- Failure isolation, partial success, safe retry, missing-data language, and idempotency: Tasks 4 and 7.
- Security, unit, API, launcher, integration, page, and regression verification: Tasks 1 through 7.

Self-review found no unresolved placeholders. Function names, statuses, request keys, default quantity, device values, confirmation lifetime, and API paths are consistent across tasks.
