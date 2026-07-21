"""Loopback-only local control panel for existing crawler scripts."""

from __future__ import annotations

import json
import mimetypes
import subprocess
import time
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, unquote, urlsplit

from workbench_creators import CreatorError, CreatorRegistry
from workbench_pipeline import PipelineManager

from workbench_core import (
    ArtifactIndexer,
    BrowserLifecycle,
    DryRunProofStore,
    HealthInspector,
    ProcessRunner,
    ProjectPaths,
    TaskRegistry,
    WorkbenchError,
    build_action,
)


MAX_BODY_BYTES = 64 * 1024


class WorkbenchApp:
    def __init__(self, root: Path, popen_factory=subprocess.Popen):
        self.paths = ProjectPaths.from_root(root)
        self.creators = CreatorRegistry(self.paths.root / "workbench-creators.json", self.paths.creators)
        self.proofs = DryRunProofStore()
        self.tasks = TaskRegistry()
        self.runner = ProcessRunner(self.paths, self.tasks, self.proofs, popen_factory=popen_factory)
        self.health_inspector = HealthInspector(self.paths)
        self.lifecycle = BrowserLifecycle(self.paths, popen_factory=popen_factory)
        self._health_cache: tuple[float, dict[str, object]] | None = None
        self.pipelines = PipelineManager(self.paths, self.selected_creators, self.lifecycle, popen_factory=popen_factory)

    def selected_creators(self, local_ids: list[str]) -> list[dict[str, object]]:
        return [item.public() for item in self.creators.select(local_ids)]

    def creator_snapshot(self, platform: str | None = None) -> dict[str, object]:
        items = self.creators.load()
        if platform:
            if platform not in {"抖音", "B站"}:
                raise WorkbenchError("platform must be 抖音 or B站")
            items = [item for item in items if item.platform == platform]
        creators = [item.public() for item in items]
        return {
            "count": len(creators),
            "creators": creators,
            "urls": [item["homepage_url"] for item in creators if item["platform"] == "抖音"],
        }

    def health(self, force: bool = False) -> dict[str, object]:
        if not force and self._health_cache and time.time() - self._health_cache[0] < 30:
            return self._health_cache[1]
        result = self.health_inspector.snapshot()
        result["browser"] = self.lifecycle.status()
        self._health_cache = (time.time(), result)
        return result

    def start_task(self, action: object, params: object, phrase: object = None) -> dict[str, object]:
        if not isinstance(action, str):
            raise WorkbenchError("action must be a string")
        if not isinstance(params, dict):
            raise WorkbenchError("params must be an object")
        spec = build_action(action, params, self.paths)
        if spec.write_kind == "feishu" and not self.proofs.authorize(spec, params, phrase):
            task = self.tasks.create(spec.action, spec.argv, spec.output_hints)
            self.tasks.reject(task.id, "matching successful dry-run confirmation phrase is required")
            return task.public()
        return self.runner.start(spec, params).public()

    def artifact_index(self) -> dict[str, object]:
        return ArtifactIndexer(self.paths).latest()

    @staticmethod
    def danger_preview(payload: dict[str, object]) -> dict[str, object]:
        scope = payload.get("scope", "")
        return {
            "status": "rejected",
            "scope": scope if isinstance(scope, str) else "",
            "message": "Deletion and local cleanup are preview-only in this release because no verified scoped deletion script exists.",
        }


class WorkbenchHandler(BaseHTTPRequestHandler):
    server: "WorkbenchServer"

    def log_message(self, format: str, *args: Any) -> None:
        return

    def _json(self, status: int, payload: dict[str, object] | list[dict[str, object]]) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _error(self, error: Exception) -> None:
        if isinstance(error, WorkbenchError):
            self._json(error.status, {"error": str(error)})
        elif isinstance(error, CreatorError):
            self._json(400, {"error": str(error)})
        else:
            self._json(500, {"error": "internal server error"})

    def _read_json(self) -> dict[str, object]:
        length_raw = self.headers.get("Content-Length")
        if not length_raw:
            raise WorkbenchError("Content-Length is required")
        try:
            length = int(length_raw)
        except ValueError as exc:
            raise WorkbenchError("Content-Length must be an integer") from exc
        if length < 0 or length > MAX_BODY_BYTES:
            raise WorkbenchError("request body is too large", HTTPStatus.REQUEST_ENTITY_TOO_LARGE)
        if "application/json" not in self.headers.get("Content-Type", ""):
            raise WorkbenchError("Content-Type must be application/json", HTTPStatus.UNSUPPORTED_MEDIA_TYPE)
        try:
            payload = json.loads(self.rfile.read(length).decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise WorkbenchError("request body must be valid UTF-8 JSON") from exc
        if not isinstance(payload, dict):
            raise WorkbenchError("request JSON must be an object")
        return payload

    def do_GET(self) -> None:
        try:
            parsed = urlsplit(self.path)
            if parsed.path == "/api/ready":
                return self._json(200, {"ready": True, "host": "127.0.0.1"})
            if parsed.path == "/api/health":
                force = parse_qs(parsed.query).get("force", ["0"])[0] == "1"
                return self._json(200, self.server.app.health(force=force))
            if parsed.path == "/api/connection":
                return self._json(200, self.server.app.lifecycle.status())
            if parsed.path == "/api/creators":
                platform = parse_qs(parsed.query).get("platform", [None])[0]
                return self._json(200, self.server.app.creator_snapshot(platform))
            if parsed.path == "/api/tasks":
                return self._json(200, {"tasks": self.server.app.tasks.list()})
            if parsed.path == "/api/pipelines":
                return self._json(200, {"pipelines": self.server.app.pipelines.list()})
            if parsed.path.startswith("/api/pipelines/") and parsed.path.endswith("/log"):
                pipeline_id = parsed.path.removeprefix("/api/pipelines/").removesuffix("/log").rstrip("/")
                offset = int(parse_qs(parsed.query).get("offset", ["0"])[0])
                return self._json(200, self.server.app.pipelines.log_after(pipeline_id, offset))
            if parsed.path.startswith("/api/pipelines/"):
                pipeline_id = parsed.path.removeprefix("/api/pipelines/")
                return self._json(200, {"pipeline": self.server.app.pipelines.get(pipeline_id).public(include_phrase=True)})
            if parsed.path.startswith("/api/tasks/") and parsed.path.endswith("/log"):
                task_id = parsed.path.removeprefix("/api/tasks/").removesuffix("/log").rstrip("/")
                raw_offset = parse_qs(parsed.query).get("offset", ["0"])[0]
                try:
                    offset = int(raw_offset)
                except ValueError as exc:
                    raise WorkbenchError("offset must be an integer") from exc
                return self._json(200, self.server.app.tasks.log_after(task_id, offset))
            if parsed.path.startswith("/api/tasks/"):
                task_id = parsed.path.removeprefix("/api/tasks/")
                return self._json(200, {"task": self.server.app.tasks.get(task_id).public()})
            if parsed.path == "/api/artifacts":
                return self._json(200, self.server.app.artifact_index())
            return self._static(parsed.path)
        except Exception as exc:
            self._error(exc)

    def do_POST(self) -> None:
        try:
            payload = self._read_json()
            if self.path == "/api/tasks":
                task = self.server.app.start_task(payload.get("action"), payload.get("params"), payload.get("confirmation_phrase"))
                return self._json(202, {"task": task})
            if self.path == "/api/pipelines":
                pipeline = self.server.app.pipelines.start(payload.get("selected_creator_ids"), payload.get("options", {}))
                return self._json(202, {"pipeline": pipeline.public(include_phrase=True)})
            if self.path.startswith("/api/pipelines/") and self.path.endswith("/confirm"):
                pipeline_id = self.path.removeprefix("/api/pipelines/").removesuffix("/confirm").rstrip("/")
                pipeline = self.server.app.pipelines.confirm(pipeline_id, payload.get("confirmation_phrase"))
                return self._json(202, {"pipeline": pipeline.public()})
            if self.path == "/api/creators/preview":
                return self._json(200, self.server.app.creators.preview(payload.get("urls")))
            if self.path == "/api/chrome/start":
                return self._json(202, self.server.app.lifecycle.start_chrome())
            if self.path == "/api/bridge/start":
                return self._json(202, self.server.app.lifecycle.start_bridge())
            if self.path in {"/api/danger/preview", "/api/danger/confirm"}:
                return self._json(409, self.server.app.danger_preview(payload))
            raise WorkbenchError("endpoint not found", 404)
        except Exception as exc:
            self._error(exc)

    def do_PUT(self) -> None:
        try:
            if self.path != "/api/creators":
                raise WorkbenchError("endpoint not found", 404)
            payload = self._read_json()
            creators = payload.get("creators")
            if creators is None:
                preview = self.server.app.creators.preview(payload.get("urls"))
                creators = preview["creators"]
            saved = self.server.app.creators.save(creators)
            return self._json(200, {"count": len(saved), "creators": [item.public() for item in saved]})
        except Exception as exc:
            self._error(exc)

    def _static(self, requested: str) -> None:
        relative = "index.html" if requested in {"", "/"} else unquote(requested).lstrip("/")
        root = (self.server.app.paths.root / "workbench").resolve()
        candidate = (root / relative).resolve()
        try:
            candidate.relative_to(root)
        except ValueError as exc:
            raise WorkbenchError("static path is outside workbench", 404) from exc
        if not candidate.is_file():
            raise WorkbenchError("endpoint not found", 404)
        content_type = {".html": "text/html; charset=utf-8", ".js": "text/javascript; charset=utf-8", ".css": "text/css; charset=utf-8", ".svg": "image/svg+xml"}.get(candidate.suffix.lower(), mimetypes.guess_type(candidate.name)[0] or "application/octet-stream")
        data = candidate.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)


class WorkbenchServer(ThreadingHTTPServer):
    daemon_threads = True
    app: WorkbenchApp


def create_server(root: Path, host: str = "127.0.0.1", port: int = 8765, popen_factory=subprocess.Popen) -> WorkbenchServer:
    if host != "127.0.0.1":
        raise ValueError("local workbench may listen only on 127.0.0.1")
    server = WorkbenchServer((host, port), WorkbenchHandler)
    server.app = WorkbenchApp(Path(root), popen_factory=popen_factory)
    return server


def main() -> None:
    root = Path(__file__).resolve().parent
    server = create_server(root)
    print(f"AI 博主采集工作台：http://127.0.0.1:{server.server_port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.app.lifecycle.shutdown()
        server.server_close()


if __name__ == "__main__":
    main()
