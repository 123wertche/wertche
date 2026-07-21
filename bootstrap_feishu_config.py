"""Create the project-local Feishu config without logging the Base token."""

import argparse
import json
from pathlib import Path
from urllib.parse import urlsplit

import download_bili_following_latest as bili


ROOT = Path(__file__).resolve().parent
CONFIG_PATH = ROOT / "feishu-base-config.json"
DEFAULT_WIKI_URL = "https://my.feishu.cn/wiki/HifXwc4uDiaeD7kCvqocRxHCnlc?table=tblakZnkghpokyGT&view=vewIltNX4z"
TARGET_VIDEO_TABLE_ID = "tblakZnkghpokyGT"
TABLE_NAMES = {
    "creators": "博主表",
    "videos": "视频表",
    "video_metric_snapshots": "视频指标快照",
    "crawl_task_logs": "爬取任务日志",
    "video_comments": "视频评论",
}


def wiki_node_argument(value):
    parsed = urlsplit(str(value))
    if parsed.scheme and parsed.netloc:
        parts = [part for part in parsed.path.split("/") if part]
        if len(parts) >= 2 and parts[-2] == "wiki":
            return parts[-1]
    return str(value)


def _find_value(value, key):
    if isinstance(value, dict):
        if value.get(key):
            return value[key]
        for child in value.values():
            found = _find_value(child, key)
            if found:
                return found
    elif isinstance(value, list):
        for child in value:
            found = _find_value(child, key)
            if found:
                return found
    return None


def _table_items(payload):
    data = payload.get("data", payload)
    for key in ("items", "tables"):
        if isinstance(data.get(key), list):
            return data[key]
    return []


def build_config(base_token, tables, *, profile, base_url=DEFAULT_WIKI_URL):
    by_name = {str(item.get("name") or ""): item for item in tables}
    missing = [name for name in TABLE_NAMES.values() if name not in by_name]
    if missing:
        raise RuntimeError(f"required Feishu tables missing: {', '.join(missing)}")

    mapped = {}
    for key, name in TABLE_NAMES.items():
        item = by_name[name]
        table_id = item.get("table_id") or item.get("id")
        if not table_id:
            raise RuntimeError(f"table id unavailable for {name}")
        mapped[key] = {"name": name, "table_id": table_id}

    if mapped["videos"]["table_id"] != TARGET_VIDEO_TABLE_ID:
        raise RuntimeError(
            f"target video table mismatch: expected {TARGET_VIDEO_TABLE_ID}, "
            f"got {mapped['videos']['table_id']}"
        )

    return {
        "base_name": "博主更新数据分析系统",
        "base_token": base_token,
        "base_url": base_url,
        "profile": profile,
        "tables": {"default": mapped["videos"], **mapped},
    }


def resolve_config(wiki_url, profile):
    cli = str(ROOT / ".venv" / "lark" / "node_modules" / ".bin" / "lark-cli.cmd")
    wiki_result = bili.run_command(
        [
            cli,
            "--profile",
            profile,
            "wiki",
            "+node-get",
            "--as",
            "user",
            "--node-token",
            wiki_node_argument(wiki_url),
            "--format",
            "json",
        ],
        timeout=60,
    )
    wiki = bili.safe_json_from_stdout(wiki_result.stdout)
    base_token = _find_value(wiki, "obj_token")
    if not base_token:
        raise RuntimeError("wiki response did not contain a Base token")

    table_result = bili.run_command(
        [
            cli,
            "--profile",
            profile,
            "base",
            "+table-list",
            "--as",
            "user",
            "--base-token",
            base_token,
            "--limit",
            "100",
            "--format",
            "json",
        ],
        timeout=60,
    )
    table_payload = bili.safe_json_from_stdout(table_result.stdout)
    return build_config(base_token, _table_items(table_payload), profile=profile, base_url=wiki_url)


def write_config(config, path=CONFIG_PATH):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(config, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--wiki-url", default=DEFAULT_WIKI_URL)
    parser.add_argument("--profile", default="cli_aad2f8eda00a1bc3")
    args = parser.parse_args()

    config = resolve_config(args.wiki_url, args.profile)
    write_config(config)
    print(
        json.dumps(
            {
                "config": str(CONFIG_PATH),
                "profile": config["profile"],
                "video_table": config["tables"]["videos"],
                "mapped_tables": sorted(config["tables"].keys()),
                "base_token_logged": False,
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
