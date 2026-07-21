"""Two-phase, one-click local workbench pipeline."""

from __future__ import annotations

import hashlib
import json
import secrets
import subprocess
import threading
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Callable

from merge_douyin_download_manifests import merge_download_manifests
from workbench_core import ProjectPaths, WorkbenchError, build_action, project_command_env


def build_pipeline_steps(creators: list[dict[str, object]], options: dict[str, object]) -> tuple[list[tuple[str, dict[str, object]]], list[tuple[str, dict[str, object]]]]:
    count = options.get("videos_per_creator", 2)
    if isinstance(count, bool) or not isinstance(count, int) or not 1 <= count <= 20:
        raise WorkbenchError("videos_per_creator must be between 1 and 20")
    model = str(options.get("model", "small"))
    device = str(options.get("device", "auto"))
    transcribe = options.get("transcribe", True) is not False
    comments = options.get("comments", True) is not False
    douyin = [item for item in creators if item.get("platform") == "抖音"]
    bili = [item for item in creators if item.get("platform") == "B站"]
    dry: list[tuple[str, dict[str, object]]] = [("preflight", {})]
    real: list[tuple[str, dict[str, object]]] = []
    if douyin:
        urls = [str(item["homepage_url"]) for item in douyin]
        base = {"creator_urls": urls, "max_creators": len(urls), "videos_per_creator": count}
        dry.append(("douyin_download", {**base, "dry_run": True, "transcribe": False}))
        real.append(("douyin_download", {**base, "transcribe": transcribe, "model": model, "device": device}))
        real.extend([
            ("douyin_sync", {"dry_run": True}), ("douyin_sync", {}),
            ("douyin_enrich", {"dry_run": True}), ("douyin_enrich", {}),
            ("douyin_publish_docs", {"dry_run": True, "max_records": len(douyin) * count}),
            ("douyin_publish_docs", {"max_records": len(douyin) * count}),
        ])
    if bili:
        ids = [str(item["local_id"]) for item in bili]
        mids = [str(item["platform_id"]) for item in bili]
        dry.extend([
            ("bili_creator_sync", {"creator_ids": ids, "dry_run": True}),
            ("bili_download", {"creator_mids": mids, "max_creators": len(bili), "videos_per_creator": count, "dry_run": True}),
        ])
        real.extend([
            ("bili_creator_sync", {"creator_ids": ids}),
            ("bili_download", {"creator_mids": mids, "max_creators": len(bili), "videos_per_creator": count}),
        ])
        if transcribe:
            real.append(("bili_postprocess", {"max_videos": len(bili) * count, "model": model, "device": device}))
        if comments:
            real.extend([
                ("bili_comments_sync", {"max_videos": len(bili) * count, "dry_run": True}),
                ("bili_comments_sync", {"max_videos": len(bili) * count}),
            ])
    real.append(("export_video_table", {}))
    return dry, real


@dataclass
class PipelineRecord:
    id: str
    selected_creator_ids: list[str]
    options: dict[str, object]
    status: str = "dry_run_queued"
    phase: str = "dry_run"
    current_step: str = ""
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    expires_at: float | None = None
    confirmation_phrase: str | None = None
    confirmation_hash: str | None = None
    log: str = ""
    error: str | None = None
    completed_steps: list[str] = field(default_factory=list)

    def public(self, *, include_phrase: bool = False) -> dict[str, object]:
        result = asdict(self)
        result.pop("confirmation_hash", None)
        result.pop("log", None)
        if not include_phrase:
            result.pop("confirmation_phrase", None)
        return result


class PipelineManager:
    def __init__(self, paths: ProjectPaths, creator_loader: Callable[[list[str]], list[dict[str, object]]], lifecycle, popen_factory=subprocess.Popen):
        self.paths = paths
        self.creator_loader = creator_loader
        self.lifecycle = lifecycle
        self.popen_factory = popen_factory
        self.records: dict[str, PipelineRecord] = {}
        self.lock = threading.RLock()
        self.root = paths.root / "runtime" / "workbench" / "pipelines"

    def _save(self, record: PipelineRecord) -> None:
        record.updated_at = time.time()
        self.root.mkdir(parents=True, exist_ok=True)
        target = self.root / f"{record.id}.json"
        temporary = target.with_suffix(".json.tmp")
        temporary.write_text(json.dumps({**record.public(include_phrase=False), "log": record.log}, ensure_ascii=False, indent=2), encoding="utf-8")
        temporary.replace(target)

    def _append(self, record: PipelineRecord, text: str) -> None:
        with self.lock:
            record.log += text
            self._save(record)

    def get(self, pipeline_id: str) -> PipelineRecord:
        with self.lock:
            if pipeline_id not in self.records:
                raise WorkbenchError("pipeline not found", 404)
            return self.records[pipeline_id]

    def list(self) -> list[dict[str, object]]:
        with self.lock:
            return [item.public() for item in sorted(self.records.values(), key=lambda value: value.created_at, reverse=True)]

    def log_after(self, pipeline_id: str, offset: int) -> dict[str, object]:
        log = self.get(pipeline_id).log
        offset = max(0, min(offset, len(log)))
        return {"text": log[offset:], "next_offset": len(log)}

    def start(self, selected_ids: object, options: object) -> PipelineRecord:
        if not isinstance(selected_ids, list) or not selected_ids or any(not isinstance(item, str) for item in selected_ids):
            raise WorkbenchError("select at least one creator")
        if not isinstance(options, dict):
            raise WorkbenchError("options must be an object")
        with self.lock:
            active_statuses = {"dry_run_queued", "running", "awaiting_confirmation", "execution_queued"}
            active = next((item for item in self.records.values() if item.status in active_statuses), None)
            if active is not None:
                raise WorkbenchError(f"pipeline already running: {active.id}", 409)
            creators = self.creator_loader(selected_ids)
            build_pipeline_steps(creators, options)
            record = PipelineRecord(uuid.uuid4().hex, list(selected_ids), dict(options))
            self.records[record.id] = record
            self._save(record)
        threading.Thread(target=self._run_dry, args=(record, creators), daemon=True, name=f"pipeline-dry-{record.id}").start()
        return record

    def _run_step(self, record: PipelineRecord, action: str, params: dict[str, object]) -> None:
        spec = build_action(action, params, self.paths)
        record.current_step = action
        record.status = "running"
        self._append(record, f"\n=== {action} ===\n")
        process = self.popen_factory(
            spec.argv, cwd=str(self.paths.root), env=project_command_env(self.paths), stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace", shell=False,
        )
        if process.stdout is not None:
            for line in process.stdout:
                self._append(record, line)
        code = int(process.wait())
        if code != 0:
            raise RuntimeError(f"{action} failed with exit code {code}")
        record.completed_steps.append(action)
        self._save(record)

    def _download_manifest_snapshot(self) -> set[str]:
        return {str(path.resolve()) for path in self.paths.manifests_root.glob("*-douyin-latest-download.json")}

    def _new_download_manifest(self, before: set[str]) -> Path | None:
        candidates = [
            path for path in self.paths.manifests_root.glob("*-douyin-latest-download.json")
            if str(path.resolve()) not in before
        ]
        return max(candidates, key=lambda path: (path.stat().st_mtime_ns, path.name)) if candidates else None

    def _run_douyin_download(self, record: PipelineRecord, params: dict[str, object]) -> Path:
        before = self._download_manifest_snapshot()
        try:
            self._run_step(record, "douyin_download", params)
        except Exception:
            partial_path = self._new_download_manifest(before)
            if partial_path is None:
                raise
            partial = json.loads(partial_path.read_text(encoding="utf-8"))
            retry_urls = []
            for failure in partial.get("failures", []):
                url = str((failure.get("creator") or {}).get("url") or "").split("?", 1)[0].rstrip("/")
                if url and url not in retry_urls:
                    retry_urls.append(url)
            has_progress = any(partial.get(key) for key in ("successes", "would_download", "skipped_existing"))
            if not has_progress or not retry_urls:
                raise
            self._append(record, f"\n检测到部分成功；5 秒后仅重试 {len(retry_urls)} 位失败博主。\n")
            time.sleep(5)
            retry_params = dict(params)
            retry_params["creator_urls"] = retry_urls
            retry_params["max_creators"] = len(retry_urls)
            retry_before = self._download_manifest_snapshot()
            self._run_step(record, "douyin_download", retry_params)
            retry_path = self._new_download_manifest(retry_before)
            if retry_path is None:
                raise RuntimeError("Douyin recovery completed without a new manifest")
            retry = json.loads(retry_path.read_text(encoding="utf-8"))
            merged = merge_download_manifests(
                [partial, retry],
                source_names=[self.paths.relative(partial_path), self.paths.relative(retry_path)],
            )
            if merged.get("failures"):
                raise RuntimeError("Douyin recovery still has unresolved creator failures")
            output = self.paths.manifests_root / f"{time.strftime('%Y%m%d-%H%M%S')}-{record.id[:8]}-merged-douyin-latest-download.json"
            output.write_text(json.dumps(merged, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            self._append(record, f"已合并恢复清单：{self.paths.relative(output)}\n")
            return output
        result = self._new_download_manifest(before)
        if result is None:
            raise RuntimeError("Douyin download completed without a new manifest")
        return result

    def _run_resilient_step(self, record: PipelineRecord, action: str, params: dict[str, object], retry_delays=(2, 5)) -> None:
        for attempt in range(len(retry_delays) + 1):
            try:
                self._run_step(record, action, params)
                return
            except Exception:
                if attempt >= len(retry_delays):
                    raise
                delay = retry_delays[attempt]
                self._append(record, f"\n{action} 失败；{delay} 秒后进行第 {attempt + 1} 次幂等重试。\n")
                time.sleep(delay)

    def _run_dry(self, record: PipelineRecord, creators: list[dict[str, object]]) -> None:
        try:
            self.lifecycle.start_chrome()
            self.lifecycle.start_bridge()
            dry, _ = build_pipeline_steps(creators, record.options)
            for action, params in dry:
                if action == "douyin_download":
                    self._run_douyin_download(record, params)
                else:
                    self._run_step(record, action, params)
            phrase = f"确认同步-{secrets.token_hex(3).upper()}"
            record.confirmation_phrase = phrase
            record.confirmation_hash = hashlib.sha256(phrase.encode("utf-8")).hexdigest()
            record.expires_at = time.time() + 1800
            record.phase = "confirmation"
            record.status = "awaiting_confirmation"
            record.current_step = "等待确认"
            self._append(record, "\nDry-run 全部成功。确认后才会写入飞书。\n")
        except Exception as exc:
            record.status = "failed"
            record.error = str(exc)
            self._append(record, f"\n失败：{exc}\n")

    def confirm(self, pipeline_id: str, phrase: object) -> PipelineRecord:
        record = self.get(pipeline_id)
        if record.status != "awaiting_confirmation":
            raise WorkbenchError("pipeline is not awaiting confirmation")
        if not isinstance(phrase, str) or not record.confirmation_hash or hashlib.sha256(phrase.encode("utf-8")).hexdigest() != record.confirmation_hash:
            raise WorkbenchError("confirmation phrase does not match")
        if not record.expires_at or time.time() > record.expires_at:
            raise WorkbenchError("confirmation has expired")
        record.confirmation_phrase = None
        record.phase = "execution"
        record.status = "execution_queued"
        self._save(record)
        creators = self.creator_loader(record.selected_creator_ids)
        threading.Thread(target=self._run_real, args=(record, creators), daemon=True, name=f"pipeline-real-{record.id}").start()
        return record

    def _run_real(self, record: PipelineRecord, creators: list[dict[str, object]]) -> None:
        try:
            _, real = build_pipeline_steps(creators, record.options)
            download_manifest: Path | None = None
            for action, params in real:
                if action == "douyin_download":
                    download_manifest = self._run_douyin_download(record, params)
                    continue
                scoped = dict(params)
                if download_manifest is not None and action in {"douyin_sync", "douyin_enrich", "douyin_publish_docs"}:
                    scoped["manifest"] = self.paths.relative(download_manifest)
                if action in {"douyin_sync", "douyin_enrich"}:
                    self._run_resilient_step(record, action, scoped)
                else:
                    self._run_step(record, action, scoped)
            record.phase = "complete"
            record.status = "succeeded"
            record.current_step = "完成"
            self._append(record, "\n一键流水线完成。\n")
        except Exception as exc:
            record.status = "failed"
            record.error = str(exc)
            self._append(record, f"\n失败：{exc}\n")
