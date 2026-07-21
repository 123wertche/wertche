"""Idempotently resolve selected local Bilibili creators to Feishu records."""

from __future__ import annotations

import argparse
import json
import tempfile
from datetime import datetime
from pathlib import Path

from download_bili_following_latest import list_records, load_config, run_lark
from workbench_creators import CreatorIdentity, CreatorRegistry


ROOT = Path(__file__).resolve().parent
MANIFEST_ROOT = ROOT / "downloads" / "manifests"


class CreatorSyncError(RuntimeError):
    pass


def plan_creator_sync(selected: list[CreatorIdentity], existing_rows: list[dict[str, object]]) -> dict[str, object]:
    by_mid: dict[str, list[dict[str, object]]] = {}
    for row in existing_rows:
        mid = str(row.get("B站MID") or row.get("mid") or "").strip()
        if mid:
            by_mid.setdefault(mid, []).append(row)
    mapping: dict[str, str] = {}
    create: list[dict[str, str]] = []
    reuse: list[dict[str, str]] = []
    for creator in selected:
        if creator.platform != "B站":
            continue
        matches = by_mid.get(creator.platform_id, [])
        if len(matches) > 1:
            raise CreatorSyncError(f"飞书博主表存在重复 B站 MID：{creator.platform_id}")
        if matches:
            record_id = str(matches[0].get("_record_id") or matches[0].get("record_id") or "").strip()
            if not record_id:
                raise CreatorSyncError(f"B站 MID {creator.platform_id} 的飞书 record ID 数据不可用")
            mapping[creator.local_id] = record_id
            reuse.append({"local_id": creator.local_id, "mid": creator.platform_id, "record_id": record_id})
        else:
            create.append({
                "local_id": creator.local_id,
                "mid": creator.platform_id,
                "name": creator.display_name,
                "homepage_url": creator.homepage_url,
            })
    return {"mapping": mapping, "create": create, "reuse": reuse}


def _batch_create(config: dict[str, object], items: list[dict[str, str]]) -> list[str]:
    if not items:
        return []
    payload = {
        "fields": ["博主名称", "B站MID", "主页链接", "是否持续跟踪"],
        "rows": [[item["name"], item["mid"], item["homepage_url"], True] for item in items],
    }
    tmp_dir = ROOT / ".tmp-lark"
    tmp_dir.mkdir(exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", suffix=".json", dir=tmp_dir, delete=False) as f:
        json.dump(payload, f, ensure_ascii=False)
        payload_path = Path(f.name)
    try:
        result = run_lark(
            config,
            [
                "+record-batch-create", "--as", "user",
                "--base-token", config["base_token"],
                "--table-id", config["tables"]["creators"]["table_id"],
                "--json", f"@{payload_path.relative_to(ROOT)}",
            ],
            timeout=120,
        )
    finally:
        payload_path.unlink(missing_ok=True)
    return list(result["data"].get("record_id_list", []))


def _write_manifest(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def parse_args(argv=None):
    parser = argparse.ArgumentParser(allow_abbrev=False)
    parser.add_argument("--creators", default="workbench-creators.json")
    parser.add_argument("--creator-id", action="append", required=True)
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)
    creator_path = (ROOT / args.creators).resolve() if not Path(args.creators).is_absolute() else Path(args.creators).resolve()
    try:
        creator_path.relative_to(ROOT)
    except ValueError as exc:
        raise CreatorSyncError("creators path must stay inside project root") from exc
    config = load_config()
    table_id = config["tables"]["creators"]["table_id"]
    rows = list_records(config, table_id, ["博主名称", "B站MID", "主页链接", "是否持续跟踪"])
    feishu_bili = [{"mid": row.get("B站MID"), "name": row.get("博主名称"), "record_id": row.get("_record_id")} for row in rows]
    registry = CreatorRegistry(creator_path, ROOT / "douyin-creators.json")
    selected = registry.select(args.creator_id, feishu_bili)
    if any(item.platform != "B站" for item in selected):
        raise CreatorSyncError("creator sync accepts only B站 creators")
    plan = plan_creator_sync(selected, rows)
    created_ids: list[str] = []
    if not args.dry_run and plan["create"]:
        created_ids = _batch_create(config, plan["create"])
        rows = list_records(config, table_id, ["博主名称", "B站MID", "主页链接", "是否持续跟踪"])
        plan = plan_creator_sync(selected, rows)
        if plan["create"]:
            raise CreatorSyncError("创建后重新读取飞书仍有未解析 B站博主")
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    manifest_path = MANIFEST_ROOT / f"{stamp}-workbench-creator-sync.json"
    manifest = {
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "dry_run": args.dry_run,
        "selected_local_ids": args.creator_id,
        "mapping": plan["mapping"],
        "create": plan["create"],
        "reuse": plan["reuse"],
        "created_record_ids": created_ids,
        "status": "planned" if args.dry_run else "verified",
    }
    _write_manifest(manifest_path, manifest)
    print(json.dumps({"manifest": str(manifest_path.relative_to(ROOT)), "status": manifest["status"], "create_count": len(plan["create"]), "mapping_count": len(plan["mapping"])}, ensure_ascii=False))
    return manifest


if __name__ == "__main__":
    main()
