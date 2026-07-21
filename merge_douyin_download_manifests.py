"""Merge partial Douyin download manifests without duplicating video IDs."""

from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parent
MANIFEST_ROOT = ROOT / "downloads" / "manifests"


def _creator_url(value):
    return str((value or {}).get("url") or "").split("?", 1)[0].rstrip("/")


def _canonicalize_creator(value, canonical_by_url):
    creator = dict(value or {})
    canonical = canonical_by_url.get(_creator_url(creator))
    return dict(canonical) if canonical else creator


def merge_download_manifests(manifests, source_names=None, excluded_ids=None):
    if not manifests:
        raise ValueError("at least one manifest is required")
    excluded_ids = {str(value) for value in (excluded_ids or set())}
    canonical_by_url = {}
    creators = []
    for manifest in manifests:
        for creator in manifest.get("creators", []):
            url = _creator_url(creator)
            if url and url not in canonical_by_url:
                canonical_by_url[url] = dict(creator)
                creators.append(dict(creator))

    successes_by_id = {}
    would_download_by_id = {}
    skipped_existing_by_id = {}
    parsed_by_url = {}
    failures = []
    for manifest in manifests:
        for success in manifest.get("successes", []):
            item = dict(success)
            item["creator"] = _canonicalize_creator(item.get("creator"), canonical_by_url)
            aweme_id = str(item.get("aweme_id") or "")
            if aweme_id and aweme_id not in excluded_ids:
                successes_by_id[aweme_id] = item
        for source_key, target in (
            ("would_download", would_download_by_id),
            ("skipped_existing", skipped_existing_by_id),
        ):
            for candidate in manifest.get(source_key, []):
                item = dict(candidate)
                item["creator"] = _canonicalize_creator(item.get("creator"), canonical_by_url)
                aweme_id = str(item.get("aweme_id") or "")
                if aweme_id and aweme_id not in excluded_ids:
                    target[aweme_id] = item
        for parsed in manifest.get("parsed", []):
            item = dict(parsed)
            item["creator"] = _canonicalize_creator(item.get("creator"), canonical_by_url)
            url = _creator_url(item.get("creator"))
            previous = parsed_by_url.get(url)
            if previous is None or item.get("selected") or not previous.get("selected"):
                parsed_by_url[url] = item
        failures.extend(dict(item) for item in manifest.get("failures", []))

    successful_urls = {
        _creator_url(item.get("creator"))
        for group in (successes_by_id, would_download_by_id, skipped_existing_by_id)
        for item in group.values()
    }
    unresolved_failures = []
    for failure in failures:
        failure["creator"] = _canonicalize_creator(failure.get("creator"), canonical_by_url)
        url = _creator_url(failure.get("creator"))
        if not url or url not in successful_urls:
            unresolved_failures.append(failure)

    first, last = manifests[0], manifests[-1]
    dry_run = all(bool(item.get("dry_run")) for item in manifests)
    return {
        "platform": "douyin",
        "started_at": first.get("started_at"),
        "ended_at": last.get("ended_at"),
        "dry_run": dry_run,
        "transcribe": any(bool(item.get("transcribe")) for item in manifests),
        "out_root": last.get("out_root") or first.get("out_root"),
        "creators": creators,
        "successes": list(successes_by_id.values()),
        "would_download": list(would_download_by_id.values()),
        "skipped_existing": list(skipped_existing_by_id.values()),
        "failures": unresolved_failures,
        "parsed": list(parsed_by_url.values()),
        "source_manifests": list(source_names or []),
        "summary": {
            "creators": len(creators),
            "downloaded": len(successes_by_id),
            "would_download": len(would_download_by_id),
            "skipped_existing": len(skipped_existing_by_id),
            "failed": len(unresolved_failures),
            "dry_run": dry_run,
            "transcribe": any(bool(item.get("transcribe")) for item in manifests),
            "merged": True,
        },
    }


def main():
    parser = argparse.ArgumentParser(allow_abbrev=False)
    parser.add_argument("--manifest", action="append", required=True)
    parser.add_argument("--exclude-id", action="append", default=[])
    parser.add_argument("--output")
    args = parser.parse_args()
    paths = []
    for value in args.manifest:
        path = Path(value)
        paths.append(path if path.is_absolute() else ROOT / path)
    payloads = [json.loads(path.read_text(encoding="utf-8")) for path in paths]
    output = Path(args.output) if args.output else MANIFEST_ROOT / f"{datetime.now():%Y%m%d-%H%M%S}-merged-douyin-latest-download.json"
    if not output.is_absolute():
        output = ROOT / output
    if output.exists():
        raise FileExistsError(f"refusing to overwrite existing file: {output}")
    output.parent.mkdir(parents=True, exist_ok=True)
    merged = merge_download_manifests(
        payloads,
        [str(path) for path in paths],
        excluded_ids=set(args.exclude_id),
    )
    output.write_text(json.dumps(merged, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"output": str(output), "summary": merged["summary"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
