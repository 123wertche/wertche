"""Security-focused primitives for the local crawler workbench.

This module deliberately contains no HTTP handling and no shell command
parsing.  The server can only choose one of the argument-list builders below.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
import shutil
import socket
import subprocess
import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit, urlunsplit

import preflight_douyin


DOUYIN_HOME_RE = re.compile(r"^https://www\.douyin\.com/user/[^/?#]+$")
MODELS = {"small", "medium", "large-v3-turbo"}
DEVICES = {"auto", "cpu", "cuda"}


def project_command_env(paths: "ProjectPaths") -> dict[str, str]:
    """Match the project-local PATH policy used by crawler entry points."""
    env = os.environ.copy()
    command_dirs = (
        paths.root / ".venv" / "Scripts",
        paths.root / "tools" / "node",
        paths.root / "tools" / "lark" / "node_modules" / ".bin",
        paths.root / ".venv" / "lark" / "node_modules" / ".bin",
        Path.home() / ".cache" / "codex-runtimes" / "codex-primary-runtime" / "dependencies" / "node" / "bin",
    )
    env["PATH"] = os.pathsep.join(str(path) for path in command_dirs if path.exists()) + os.pathsep + env.get("PATH", "")
    env["PYTHONUTF8"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    return env


class WorkbenchError(ValueError):
    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.status = status


@dataclass(frozen=True)
class ProjectPaths:
    root: Path
    python: Path
    creators: Path
    manifests_root: Path

    @classmethod
    def from_root(cls, root: Path) -> "ProjectPaths":
        resolved = root.resolve()
        return cls(
            root=resolved,
            python=resolved / ".venv" / "Scripts" / "python.exe",
            creators=resolved / "douyin-creators.json",
            manifests_root=resolved / "downloads" / "manifests",
        )

    def relative(self, path: Path) -> str:
        try:
            return str(path.resolve().relative_to(self.root)).replace("\\", "/")
        except ValueError as exc:
            raise WorkbenchError("path must stay inside project root") from exc

    def manifest(self, value: object) -> str | None:
        if value in (None, ""):
            return None
        if not isinstance(value, str):
            raise WorkbenchError("manifest must be a string")
        candidate = Path(value)
        if candidate.is_absolute():
            resolved = candidate.resolve()
        else:
            resolved = (self.root / candidate).resolve()
        try:
            resolved.relative_to(self.manifests_root.resolve())
        except ValueError as exc:
            raise WorkbenchError("manifest must stay inside downloads/manifests") from exc
        if resolved.suffix.lower() != ".json":
            raise WorkbenchError("manifest must be a JSON file")
        return self.relative(resolved)


@dataclass(frozen=True)
class ActionSpec:
    action: str
    argv: list[str]
    write_kind: str | None
    output_hints: list[str]


def _params(value: object) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise WorkbenchError("params must be an object")
    return value


def _positive_int(params: dict[str, Any], name: str, default: int | None = None, maximum: int = 50) -> int:
    raw = params.get(name, default)
    if isinstance(raw, bool) or not isinstance(raw, int) or not 1 <= raw <= maximum:
        raise WorkbenchError(f"{name} must be an integer between 1 and {maximum}")
    return raw


def _nonnegative_int(params: dict[str, Any], name: str, default: int, maximum: int) -> int:
    raw = params.get(name, default)
    if isinstance(raw, bool) or not isinstance(raw, int) or not 0 <= raw <= maximum:
        raise WorkbenchError(f"{name} must be an integer between 0 and {maximum}")
    return raw


def _choice(params: dict[str, Any], name: str, allowed: set[str], default: str) -> str:
    raw = params.get(name, default)
    if raw not in allowed:
        raise WorkbenchError(f"{name} must be one of: {', '.join(sorted(allowed))}")
    return str(raw)


def _string_list(params: dict[str, Any], name: str, *, pattern: str, maximum: int = 50) -> list[str]:
    raw = params.get(name, [])
    if not isinstance(raw, list) or len(raw) > maximum:
        raise WorkbenchError(f"{name} must be an array with at most {maximum} items")
    result: list[str] = []
    for value in raw:
        if not isinstance(value, str) or not re.fullmatch(pattern, value):
            raise WorkbenchError(f"{name} contains an invalid value")
        if value not in result:
            result.append(value)
    return result


def _bool(params: dict[str, Any], name: str, default: bool = False) -> bool:
    raw = params.get(name, default)
    if not isinstance(raw, bool):
        raise WorkbenchError(f"{name} must be true or false")
    return raw


def normalize_douyin_url(value: object) -> str:
    if not isinstance(value, str) or not value.strip():
        raise WorkbenchError("Douyin creator URL is required")
    split = urlsplit(value.strip())
    normalized = urlunsplit((split.scheme, split.netloc, split.path.rstrip("/"), "", ""))
    if not DOUYIN_HOME_RE.fullmatch(normalized):
        raise WorkbenchError("Douyin URL must be a creator homepage at https://www.douyin.com/user/<sec_uid>")
    return normalized


def _creator_urls(params: dict[str, Any]) -> list[str]:
    values = params.get("creator_urls")
    if not isinstance(values, list) or not values:
        raise WorkbenchError("at least one Douyin creator URL is required")
    unique: list[str] = []
    for value in values:
        normalized = normalize_douyin_url(value)
        if normalized not in unique:
            unique.append(normalized)
    if len(unique) > 50:
        raise WorkbenchError("at most 50 Douyin creator URLs are allowed")
    return unique


def _argv(paths: ProjectPaths, script: str, *arguments: str) -> list[str]:
    return [str(paths.python), script, *arguments]


def _build_douyin_download(params: dict[str, Any], paths: ProjectPaths) -> ActionSpec:
    urls = _creator_urls(params)
    videos = _positive_int(params, "videos_per_creator", 2)
    maximum_creators = _positive_int(params, "max_creators", len(urls))
    dry_run = _bool(params, "dry_run")
    transcribe = _bool(params, "transcribe")
    if dry_run and transcribe:
        raise WorkbenchError("dry-run cannot transcribe")
    args: list[str] = ["--from-feishu"]
    for url in urls:
        args.extend(["--creator-url", url])
    args.extend(["--max-creators", str(maximum_creators), "--videos-per-creator", str(videos)])
    if dry_run:
        args.append("--dry-run")
    elif transcribe:
        args.extend(["--transcribe", "--model", _choice(params, "model", MODELS, "small"), "--device", _choice(params, "device", DEVICES, "auto")])
    else:
        args.append("--skip-transcribe")
    return ActionSpec("douyin_download", _argv(paths, "download_douyin_latest.py", *args), None if dry_run else "download", ["downloads/manifests"])


def _build_douyin_sync(params: dict[str, Any], paths: ProjectPaths) -> ActionSpec:
    dry_run = _bool(params, "dry_run")
    args: list[str] = []
    manifest = paths.manifest(params.get("manifest"))
    if manifest:
        args.extend(["--manifest", manifest])
    if dry_run:
        args.append("--dry-run")
    return ActionSpec("douyin_sync", _argv(paths, "sync_douyin_to_feishu.py", *args), None if dry_run else "feishu", ["downloads/manifests"])


def _build_douyin_enrich(params: dict[str, Any], paths: ProjectPaths) -> ActionSpec:
    dry_run = _bool(params, "dry_run")
    overwrite = _bool(params, "overwrite")
    args: list[str] = []
    manifest = paths.manifest(params.get("manifest"))
    if manifest:
        args.extend(["--manifest", manifest])
    if dry_run:
        args.append("--dry-run")
    if overwrite:
        args.append("--overwrite")
    return ActionSpec("douyin_enrich", _argv(paths, "enrich_douyin_feishu.py", *args), None if dry_run else "feishu", ["downloads/manifests"])


def _build_douyin_publish_docs(params: dict[str, Any], paths: ProjectPaths) -> ActionSpec:
    dry_run = _bool(params, "dry_run")
    maximum = _positive_int(params, "max_records", 1)
    overwrite = _bool(params, "overwrite")
    args = ["--platform", "抖音", "--max-records", str(maximum)]
    manifest = paths.manifest(params.get("manifest"))
    if manifest:
        args.extend(["--manifest", manifest])
    if dry_run:
        args.append("--dry-run")
    if overwrite:
        args.append("--overwrite")
    return ActionSpec("douyin_publish_docs", _argv(paths, "publish_transcript_docs_to_feishu.py", *args), None if dry_run else "feishu", ["downloads/manifests"])


def _build_bili_download(params: dict[str, Any], paths: ProjectPaths) -> ActionSpec:
    videos = _positive_int(params, "videos_per_creator", 2)
    dry_run = _bool(params, "dry_run")
    args = ["--videos-per-creator", str(videos), "--creators-json", "workbench-creators.json"]
    for mid in _string_list(params, "creator_mids", pattern=r"\d+"):
        args.extend(["--creator-mid", mid])
    for name in ("max_creators", "max_total_videos"):
        if name in params:
            args.extend([f"--{name.replace('_', '-')}", str(_positive_int(params, name, maximum=50))])
    if "comment_limit" in params:
        args.extend(["--comment-limit", str(_nonnegative_int(params, "comment_limit", 50, 500))])
    for name, flag in (("skip_download", "--skip-download"), ("skip_comments", "--skip-comments")):
        if _bool(params, name):
            args.append(flag)
    if dry_run:
        args.append("--dry-run")
    return ActionSpec("bili_download", _argv(paths, "download_bili_following_latest.py", *args), None if dry_run else "feishu", ["downloads/manifests"])


def _build_bili_creator_sync(params: dict[str, Any], paths: ProjectPaths) -> ActionSpec:
    creator_ids = _string_list(params, "creator_ids", pattern=r"[a-f0-9]{6,64}")
    if not creator_ids:
        raise WorkbenchError("creator_ids must include at least one local creator ID")
    dry_run = _bool(params, "dry_run")
    args = ["--creators", "workbench-creators.json"]
    for creator_id in creator_ids:
        args.extend(["--creator-id", creator_id])
    if dry_run:
        args.append("--dry-run")
    return ActionSpec("bili_creator_sync", _argv(paths, "sync_workbench_creators_to_feishu.py", *args), None if dry_run else "feishu", ["downloads/manifests"])


def _build_bili_postprocess(params: dict[str, Any], paths: ProjectPaths) -> ActionSpec:
    dry_run = _bool(params, "dry_run")
    maximum = _positive_int(params, "max_videos", 1)
    args = ["--latest-download-manifest", "--max-videos", str(maximum), "--model", _choice(params, "model", MODELS, "small"), "--device", _choice(params, "device", DEVICES, "auto")]
    if dry_run:
        args.append("--dry-run")
    return ActionSpec("bili_postprocess", _argv(paths, "postprocess_bili_videos.py", *args), None if dry_run else "postprocess", ["downloads/manifests"])


def _build_bili_comments_sync(params: dict[str, Any], paths: ProjectPaths) -> ActionSpec:
    dry_run = _bool(params, "dry_run")
    maximum = _positive_int(params, "max_videos", 1)
    args = ["--latest-download-manifest", "--max-videos", str(maximum)]
    if "max_root" in params:
        args.extend(["--max-root", str(_nonnegative_int(params, "max_root", 10, 500))])
    if _bool(params, "no_replies"):
        args.append("--no-replies")
    if dry_run:
        args.append("--dry-run")
    return ActionSpec("bili_comments_sync", _argv(paths, "sync_bilibili_comments_to_feishu.py", *args), None if dry_run else "feishu", ["downloads/manifests"])


def _build_export_video_table(params: dict[str, Any], paths: ProjectPaths) -> ActionSpec:
    if params:
        raise WorkbenchError("export_video_table does not accept parameters")
    stamp = time.strftime("%Y%m%d-%H%M%S", time.localtime())
    output = f"exports/video-table-{stamp}.json"
    xlsx_output = f"exports/video-table-{stamp}.xlsx"
    return ActionSpec(
        "export_video_table",
        _argv(paths, "export_feishu_video_table.py", "--output", output, "--xlsx-output", xlsx_output),
        "export",
        [output, xlsx_output],
    )


def _build_preflight(params: dict[str, Any], paths: ProjectPaths) -> ActionSpec:
    if params:
        raise WorkbenchError("preflight does not accept parameters")
    return ActionSpec("preflight", _argv(paths, "preflight_douyin.py"), None, [])


def build_action(action: str, params: dict[str, object], paths: ProjectPaths) -> ActionSpec:
    builders = {
        "douyin_download": _build_douyin_download,
        "douyin_sync": _build_douyin_sync,
        "douyin_enrich": _build_douyin_enrich,
        "douyin_publish_docs": _build_douyin_publish_docs,
        "bili_download": _build_bili_download,
        "bili_creator_sync": _build_bili_creator_sync,
        "bili_postprocess": _build_bili_postprocess,
        "bili_comments_sync": _build_bili_comments_sync,
        "export_video_table": _build_export_video_table,
        "preflight": _build_preflight,
    }
    try:
        return builders[action](_params(params), paths)
    except KeyError as exc:
        raise WorkbenchError("unsupported action", 404) from exc


class CreatorStore:
    def __init__(self, path: Path):
        self.path = path

    def read(self) -> dict[str, object]:
        if not self.path.exists():
            return {"urls": []}
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise WorkbenchError("douyin-creators.json is not valid JSON") from exc
        creators = raw.get("creators", []) if isinstance(raw, dict) else []
        urls = [entry.get("url") for entry in creators if isinstance(entry, dict) and isinstance(entry.get("url"), str)]
        return {"urls": self.preview(urls)["normalized_urls"]}

    def preview(self, urls: object) -> dict[str, object]:
        if not isinstance(urls, list):
            raise WorkbenchError("urls must be an array")
        normalized: list[str] = []
        for url in urls:
            value = normalize_douyin_url(url)
            if value not in normalized:
                normalized.append(value)
        if len(normalized) > 50:
            raise WorkbenchError("at most 50 Douyin creator URLs are allowed")
        return {"normalized_urls": normalized, "count": len(normalized)}

    def save(self, urls: object) -> dict[str, object]:
        preview = self.preview(urls)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(self.path.suffix + ".tmp")
        payload = {"creators": [{"url": url} for url in preview["normalized_urls"]]}
        temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        temporary.replace(self.path)
        return preview


@dataclass(frozen=True)
class DryRunProof:
    phrase: str
    completed_at: float


class DryRunProofStore:
    def __init__(self):
        self._proofs: dict[str, DryRunProof] = {}
        self._lock = threading.Lock()

    @staticmethod
    def _fingerprint(action: str, params: dict[str, object]) -> str:
        canonical = {key: value for key, value in params.items() if key != "dry_run"}
        encoded = json.dumps({"action": action, "params": canonical}, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(encoded.encode("utf-8")).hexdigest()

    def issue_from_successful_dry_run(self, action: str, params: dict[str, object], now: float | None = None) -> DryRunProof:
        proof = DryRunProof(secrets.token_urlsafe(12), time.time() if now is None else now)
        with self._lock:
            self._proofs[self._fingerprint(action, params)] = proof
        return proof

    def authorize(self, spec: ActionSpec, params: dict[str, object], phrase: object, now: float | None = None) -> bool:
        if spec.write_kind != "feishu" or not isinstance(phrase, str):
            return False
        current = time.time() if now is None else now
        with self._lock:
            proof = self._proofs.get(self._fingerprint(spec.action, params))
        return bool(proof and secrets.compare_digest(proof.phrase, phrase) and current - proof.completed_at <= 1800)


@dataclass
class TaskRecord:
    id: str
    action: str
    argv: list[str]
    output_hints: list[str]
    status: str = "queued"
    created_at: float = field(default_factory=time.time)
    started_at: float | None = None
    finished_at: float | None = None
    exit_code: int | None = None
    error: str | None = None
    log: str = ""

    def public(self) -> dict[str, object]:
        return {
            "id": self.id,
            "action": self.action,
            "status": self.status,
            "created_at": self.created_at,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "exit_code": self.exit_code,
            "error": self.error,
            "output_hints": self.output_hints,
        }


class TaskRegistry:
    def __init__(self):
        self._tasks: dict[str, TaskRecord] = {}
        self._lock = threading.RLock()

    def create(self, action: str, argv: list[str], output_hints: list[str]) -> TaskRecord:
        task = TaskRecord(uuid.uuid4().hex, action, list(argv), list(output_hints))
        with self._lock:
            self._tasks[task.id] = task
        return task

    def get(self, task_id: str) -> TaskRecord:
        with self._lock:
            task = self._tasks.get(task_id)
            if task is None:
                raise WorkbenchError("task not found", 404)
            return task

    def list(self) -> list[dict[str, object]]:
        with self._lock:
            return [task.public() for task in sorted(self._tasks.values(), key=lambda item: item.created_at, reverse=True)]

    def start(self, task_id: str) -> None:
        with self._lock:
            task = self.get(task_id)
            task.status = "running"
            task.started_at = time.time()

    def reject(self, task_id: str, error: str) -> None:
        with self._lock:
            task = self.get(task_id)
            task.status = "rejected"
            task.error = error
            task.finished_at = time.time()

    def append_log(self, task_id: str, text: str) -> None:
        with self._lock:
            self.get(task_id).log += text

    def finish(self, task_id: str, exit_code: int, error: str | None = None) -> None:
        with self._lock:
            task = self.get(task_id)
            task.exit_code = exit_code
            task.error = error
            task.finished_at = time.time()
            task.status = "succeeded" if exit_code == 0 and error is None else "failed"

    def log_after(self, task_id: str, offset: int) -> dict[str, object]:
        if offset < 0:
            raise WorkbenchError("offset must be non-negative")
        with self._lock:
            log = self.get(task_id).log
            if offset > len(log):
                offset = len(log)
            return {"text": log[offset:], "next_offset": len(log)}


class ProcessRunner:
    """Launch a whitelisted action and copy combined output into its task."""

    def __init__(self, paths: ProjectPaths, registry: TaskRegistry, proofs: DryRunProofStore | None = None, popen_factory=subprocess.Popen):
        self.paths = paths
        self.registry = registry
        self.proofs = proofs
        self._popen_factory = popen_factory
        self._threads: dict[str, threading.Thread] = {}
        self._lock = threading.Lock()

    def start(self, spec: ActionSpec, params: dict[str, object]) -> TaskRecord:
        task = self.registry.create(spec.action, spec.argv, spec.output_hints)
        try:
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
        except (OSError, ValueError) as exc:
            self.registry.finish(task.id, 1, f"process launch failed: {exc.__class__.__name__}")
            return task

        def consume() -> None:
            self.registry.start(task.id)
            try:
                if process.stdout is not None:
                    for line in process.stdout:
                        self.registry.append_log(task.id, line)
                exit_code = int(process.wait())
                self.registry.finish(task.id, exit_code)
                if exit_code == 0 and params.get("dry_run") is True and self.proofs is not None:
                    proof = self.proofs.issue_from_successful_dry_run(spec.action, params)
                    self.registry.append_log(task.id, f"Dry-run confirmation phrase: {proof.phrase} (expires in 30 minutes)\n")
            except Exception as exc:  # The task status must not remain running after reader failure.
                self.registry.finish(task.id, 1, f"process output failed: {exc.__class__.__name__}")

        thread = threading.Thread(target=consume, name=f"workbench-task-{task.id}", daemon=True)
        with self._lock:
            self._threads[task.id] = thread
        thread.start()
        return task

    def join(self, task_id: str, timeout: float | None = None) -> None:
        with self._lock:
            thread = self._threads.get(task_id)
        if thread is not None:
            thread.join(timeout)


def _first_line(value: str) -> str:
    return value.splitlines()[0][:200] if value else "available"


class HealthInspector:
    def __init__(self, paths: ProjectPaths, command_runner=subprocess.run):
        self.paths = paths
        self._command_runner = command_runner

    def _tool_state(self, command: list[str], present: bool | None = None) -> dict[str, str]:
        if present is False:
            return {"status": "missing", "detail": "not found"}
        env = project_command_env(self.paths)
        executable = command[0] if Path(command[0]).is_absolute() else shutil.which(command[0], path=env.get("PATH"))
        if not executable:
            return {"status": "missing", "detail": "unavailable"}
        try:
            result = self._command_runner(
                [executable, *command[1:]],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=8,
                check=False,
                env=env,
            )
            detail = _first_line((getattr(result, "stdout", "") or "") + (getattr(result, "stderr", "") or ""))
            return {"status": "ok" if result.returncode == 0 else "missing", "detail": detail}
        except (OSError, subprocess.TimeoutExpired):
            return {"status": "missing", "detail": "unavailable"}

    def snapshot(self) -> dict[str, object]:
        lark = self.paths.root / ".venv" / "lark" / "node_modules" / ".bin" / "lark-cli.cmd"
        result = {
            "listen_host": "127.0.0.1",
            "python": self._tool_state([str(self.paths.python), "--version"], self.paths.python.exists()),
            "node": self._tool_state(["node", "--version"]),
            "lark_cli": self._tool_state([str(lark), "--version"], lark.exists()),
            "ffmpeg": self._tool_state(["ffmpeg", "-version"]),
            "yt_dlp": self._tool_state(["yt-dlp", "--version"]),
            "whisper": self._tool_state(["whisper", "--help"]),
            "feishu_config": "configured" if (self.paths.root / "feishu-base-config.json").is_file() else "missing",
            "feishu_authorization": "run preflight to verify",
        }
        def preflight_runner(args, *, timeout, root):
            return self._command_runner(
                args,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=timeout,
                check=False,
                env=preflight_douyin.project_env(root),
            )

        result["checks"] = preflight_douyin.build_result(root=self.paths.root, command_runner=preflight_runner)["checks"]
        return result


class BrowserLifecycle:
    """Own only Chrome and CDP bridge processes started by this server."""

    CDP_PORT = 9333
    BRIDGE_PORT = 3457

    def __init__(self, paths: ProjectPaths, popen_factory=subprocess.Popen):
        self.paths = paths
        self._popen_factory = popen_factory
        self._chrome: Any | None = None
        self._bridge: Any | None = None
        self._lock = threading.RLock()

    @staticmethod
    def _running(process: Any | None) -> bool:
        return bool(process is not None and getattr(process, "poll", lambda: 0)() is None)

    @staticmethod
    def _reachable(port: int) -> bool:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.3):
                return True
        except OSError:
            return False

    def status(self) -> dict[str, object]:
        with self._lock:
            chrome_running = self._running(self._chrome)
            bridge_running = self._running(self._bridge)
        return {
            "cdp_port": self.CDP_PORT,
            "bridge_port": self.BRIDGE_PORT,
            "chrome": {"running": chrome_running, "reachable": self._reachable(self.CDP_PORT)},
            "bridge": {"running": bridge_running, "reachable": self._reachable(self.BRIDGE_PORT)},
        }

    def _chrome_executable(self) -> Path:
        candidates: list[Path] = []
        local_app_data = os.environ.get("LOCALAPPDATA")
        if local_app_data:
            candidates.append(Path(local_app_data) / "Google" / "Chrome" / "Application" / "chrome.exe")
        candidates.extend([
            Path("C:/Program Files/Google/Chrome/Application/chrome.exe"),
            Path("C:/Program Files (x86)/Google/Chrome/Application/chrome.exe"),
        ])
        for candidate in candidates:
            if candidate.is_file():
                return candidate
        raise WorkbenchError("Google Chrome executable is unavailable", 503)

    def start_chrome(self) -> dict[str, object]:
        with self._lock:
            if self._running(self._chrome):
                return self.status()
            profile = self.paths.root / "runtime" / "chrome-profile"
            profile.mkdir(parents=True, exist_ok=True)
            self._chrome = self._popen_factory(
                [str(self._chrome_executable()), f"--remote-debugging-port={self.CDP_PORT}", f"--user-data-dir={profile}", "--no-first-run"],
                cwd=str(self.paths.root), stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, shell=False,
            )
        return self.status()

    def start_bridge(self) -> dict[str, object]:
        bridge = self.paths.root / ".agents" / "skills" / "douyin-comments" / "scripts" / "douyin_cdp_bridge.mjs"
        if not bridge.is_file():
            raise WorkbenchError("project CDP bridge script is unavailable", 503)
        with self._lock:
            if self._running(self._bridge):
                return self.status()
            env = project_command_env(self.paths)
            env["DOUYIN_CDP_PORT"] = str(self.CDP_PORT)
            env["DOUYIN_CDP_BRIDGE_PORT"] = str(self.BRIDGE_PORT)
            env["DOUYIN_CHROME_USER_DATA_DIR"] = str(self.paths.root / "runtime" / "chrome-profile")
            node = shutil.which("node", path=env.get("PATH"))
            if not node:
                raise WorkbenchError("project Node executable is unavailable", 503)
            self._bridge = self._popen_factory(
                [node, str(bridge), "--port", str(self.BRIDGE_PORT)],
                cwd=str(self.paths.root), stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, shell=False, env=env,
            )
        return self.status()

    def shutdown(self) -> None:
        with self._lock:
            processes = [self._bridge, self._chrome]
            self._bridge = None
            self._chrome = None
        for process in processes:
            if self._running(process):
                try:
                    process.terminate()
                except OSError:
                    pass


class ArtifactIndexer:
    """Read a bounded, project-relative list of user-facing outputs."""

    VIDEO_TABLE_URL = "https://my.feishu.cn/wiki/HifXwc4uDiaeD7kCvqocRxHCnlc?table=tblakZnkghpokyGT&view=vewIltNX4z"

    def __init__(self, paths: ProjectPaths):
        self.paths = paths

    def _allowed_files(self) -> list[Path]:
        files: list[Path] = []
        for name in ("downloads", "outputs", "exports"):
            directory = self.paths.root / name
            if not directory.is_dir():
                continue
            for path in directory.rglob("*"):
                try:
                    resolved = path.resolve()
                    resolved.relative_to(self.paths.root)
                    if path.is_file() and not path.is_symlink() and path.stat().st_size <= 2 * 1024 * 1024 * 1024:
                        files.append(path)
                except (OSError, ValueError):
                    continue
        return files

    def latest(self) -> dict[str, object]:
        manifests = sorted(self.paths.manifests_root.glob("*.json"), key=lambda path: path.stat().st_mtime, reverse=True)[:10] if self.paths.manifests_root.exists() else []
        files = sorted(self._allowed_files(), key=lambda path: path.stat().st_mtime, reverse=True)[:40]
        return {
            "latest_manifests": [self.paths.relative(path) for path in manifests],
            "recent_files": [self.paths.relative(path) for path in files],
            "video_table_url": self.VIDEO_TABLE_URL,
        }
