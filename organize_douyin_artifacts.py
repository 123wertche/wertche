"""Create a delivery-copy tree from a completed Douyin download manifest; never moves originals."""

import argparse
import json
import shutil
from pathlib import Path


ROOT = Path(__file__).resolve().parent
TOP_FOLDERS = [
    "01_视频",
    "02_转写文档",
    "03_封面",
    "04_音频",
    "05_字幕",
    "06_评论",
    "07_元数据与说明",
    "08_飞书视频表导出",
    "09_运行清单",
]


def safe_stem(value):
    return "".join("_" if ch in '<>:"/\\|?*' else ch for ch in (value or "untitled")).strip(" .")[:80] or "untitled"


def copy_file(source, folder, title, aweme_id):
    source = Path(source)
    if not source.is_file():
        return None
    target = folder / f"{safe_stem(title)} [{aweme_id}]{source.suffix.lower()}"
    folder.mkdir(parents=True, exist_ok=True)
    if not target.exists():
        shutil.copy2(source, target)
    return str(target)


def collect_artifacts(success, metadata):
    files = metadata.get("files") or {}
    values = {**files, **success}
    transcript = files.get("transcript") or success.get("transcript") or {}
    values.update(transcript)
    metadata_path = Path(values.get("metadata_path") or "")
    video_dir = metadata_path.parent if str(metadata_path) else Path()
    candidates = [
        (values.get("video_path"), "01_视频"),
        (values.get("speech_clean_path"), "02_转写文档/清洗转写"),
        (values.get("speech_raw_path"), "02_转写文档/原始转写"),
        (values.get("cover_path"), "03_封面"),
        (values.get("audio_path"), "04_音频"),
        (video_dir / "comments-visible.json", "06_评论"),
        (values.get("metadata_path"), "07_元数据与说明/元数据"),
        (values.get("description_path"), "07_元数据与说明/视频说明"),
        (video_dir / "manifest.json", "07_元数据与说明/单视频清单"),
    ]
    asr_dir = Path(values.get("asr_dir") or (Path(values.get("speech_clean_path") or "").parent / "asr"))
    if asr_dir.is_dir():
        candidates.extend((path, "05_字幕") for path in sorted(asr_dir.iterdir()) if path.is_file())
    return [(str(source), folder) for source, folder in candidates if source and Path(source).is_file()]


def main():
    parser = argparse.ArgumentParser(description="Copy local Douyin artifacts into the required delivery layout.")
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--out-root", required=True)
    args = parser.parse_args()
    manifest = json.loads(Path(args.manifest).read_text(encoding="utf-8"))
    out_root = Path(args.out_root)
    for folder in TOP_FOLDERS:
        (out_root / folder).mkdir(parents=True, exist_ok=True)
    copied = []
    for success in manifest.get("successes") or []:
        metadata = json.loads(Path(success["metadata_path"]).read_text(encoding="utf-8"))
        aweme_id = str(success.get("aweme_id") or metadata.get("aweme_id"))
        title = (metadata.get("page_metadata") or {}).get("title") or (metadata.get("selected_card") or {}).get("title") or "untitled"
        for source, folder in collect_artifacts(success, metadata):
            target = copy_file(source, out_root / folder, title, aweme_id)
            if target:
                copied.append({"source": source, "target": target})
    run_dir = out_root / "09_运行清单"
    manifest_target = run_dir / Path(args.manifest).name
    if not manifest_target.exists():
        shutil.copy2(args.manifest, manifest_target)
    print(json.dumps({"out_root": str(out_root), "copied": copied}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
