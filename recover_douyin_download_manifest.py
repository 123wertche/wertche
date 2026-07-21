"""Rebuild an aggregate download manifest from an intact per-video manifest."""

import argparse
import json
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parent
MANIFEST_ROOT = ROOT / "downloads" / "manifests"


def load_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def build_recovered_manifest(video_manifest, metadata):
    if video_manifest.get("ok") is not True:
        raise RuntimeError("per-video manifest is not successful")
    creator = video_manifest.get("creator") or metadata.get("creator") or {}
    selected = dict(metadata.get("selected_card") or {})
    if metadata.get("selection_reason") and not selected.get("selection_reason"):
        selected["selection_reason"] = metadata["selection_reason"]
    parsed = {
        "creator": creator,
        "page_url": creator.get("url"),
        "page_title": (metadata.get("page_metadata") or {}).get("title"),
        "candidates": [selected],
        "selected": [selected],
        "attempts": 1,
        "recovered_from_local_artifacts": True,
    }
    return {
        "platform": "抖音",
        "started_at": video_manifest.get("started_at"),
        "ended_at": video_manifest.get("ended_at"),
        "dry_run": False,
        "transcribe": bool((video_manifest.get("transcript") or {}).get("speech_clean_path")),
        "out_root": str(ROOT / "downloads" / "douyin"),
        "creators": [creator],
        "successes": [video_manifest],
        "would_download": [],
        "skipped_existing": [],
        "failures": [],
        "parsed": [parsed],
        "summary": {"downloaded": 1, "failed": 0, "recovered": True},
    }


def write_new_json(path, payload):
    path = Path(path)
    if path.exists():
        raise FileExistsError(f"refusing to overwrite existing file: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(allow_abbrev=False)
    parser.add_argument("--video-manifest", required=True)
    parser.add_argument("--output")
    args = parser.parse_args()

    source = Path(args.video_manifest)
    if not source.is_absolute():
        source = ROOT / source
    video_manifest = load_json(source)
    metadata_path = Path(video_manifest.get("metadata_path") or "")
    metadata = load_json(metadata_path)
    for key in ("video_path", "metadata_path", "cover_path"):
        target = Path(video_manifest.get(key) or "")
        if not target.is_file():
            raise FileNotFoundError(f"required local artifact missing: {key}")

    recovered = build_recovered_manifest(video_manifest, metadata)
    output = (
        Path(args.output)
        if args.output
        else MANIFEST_ROOT / f"{datetime.now():%Y%m%d-%H%M%S}-recovered-douyin-latest-download.json"
    )
    if not output.is_absolute():
        output = ROOT / output
    write_new_json(output, recovered)
    print(json.dumps({"output": str(output), "successes": 1, "source_preserved": True}, ensure_ascii=False))


if __name__ == "__main__":
    main()
