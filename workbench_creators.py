"""Unified local creator identities for the workbench UI and pipelines."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, replace
from pathlib import Path
from urllib.parse import urlsplit


class CreatorError(ValueError):
    pass


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

    def public(self) -> dict[str, object]:
        return asdict(self)


def creator_local_id(platform: str, platform_id: str) -> str:
    return hashlib.sha256(f"{platform}:{platform_id}".encode("utf-8")).hexdigest()[:16]


def parse_creator_homepage(value: object) -> tuple[str, str, str]:
    if not isinstance(value, str) or not value.strip():
        raise CreatorError("博主主页链接不能为空")
    split = urlsplit(value.strip())
    host = split.netloc.lower()
    parts = [part for part in split.path.split("/") if part]
    if split.scheme != "https":
        raise CreatorError("博主主页链接无法识别；必须使用 HTTPS 主页")
    if host == "www.douyin.com" and len(parts) == 2 and parts[0] == "user" and parts[1]:
        platform_id = parts[1]
        return "抖音", platform_id, f"https://www.douyin.com/user/{platform_id}"
    if host == "space.bilibili.com" and len(parts) == 1 and parts[0].isdigit():
        mid = parts[0]
        return "B站", mid, f"https://space.bilibili.com/{mid}"
    raise CreatorError("博主主页链接无法识别；仅支持抖音 user 主页和 B站 space 主页")


class CreatorRegistry:
    def __init__(self, local_path: Path, legacy_douyin_path: Path | None = None):
        self.local_path = local_path
        self.legacy_douyin_path = legacy_douyin_path or local_path.with_name("douyin-creators.json")

    @staticmethod
    def _identity(platform: str, platform_id: str, homepage: str, *, display_name: str = "", enabled: bool = True, source: str = "local", record_id: str | None = None) -> CreatorIdentity:
        fallback = f"{platform} {platform_id}"
        return CreatorIdentity(
            local_id=creator_local_id(platform, platform_id),
            platform=platform,
            platform_id=platform_id,
            homepage_url=homepage,
            display_name=display_name.strip() or fallback,
            enabled=enabled,
            source=source,
            feishu_record_id=record_id,
        )

    def preview(self, urls: object) -> dict[str, object]:
        if not isinstance(urls, list):
            raise CreatorError("urls 必须是数组")
        creators: list[CreatorIdentity] = []
        seen: set[tuple[str, str]] = set()
        for value in urls:
            platform, platform_id, homepage = parse_creator_homepage(value)
            key = (platform, platform_id)
            if key in seen:
                continue
            seen.add(key)
            creators.append(self._identity(platform, platform_id, homepage))
        if len(creators) > 100:
            raise CreatorError("一次最多添加 100 个博主")
        return {"count": len(creators), "creators": [item.public() for item in creators]}

    def _read_local(self) -> list[CreatorIdentity]:
        if not self.local_path.is_file():
            return []
        try:
            payload = json.loads(self.local_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise CreatorError("workbench-creators.json 不是有效 JSON") from exc
        if not isinstance(payload, dict) or payload.get("version") != 1 or not isinstance(payload.get("creators"), list):
            raise CreatorError("workbench-creators.json 结构无效")
        result: list[CreatorIdentity] = []
        for raw in payload["creators"]:
            if not isinstance(raw, dict):
                raise CreatorError("博主记录必须是对象")
            platform, platform_id, homepage = parse_creator_homepage(raw.get("homepage_url"))
            if raw.get("platform") not in (None, platform) or raw.get("platform_id") not in (None, platform_id):
                raise CreatorError("博主平台身份与主页不一致")
            result.append(self._identity(
                platform,
                platform_id,
                homepage,
                display_name=str(raw.get("display_name") or ""),
                enabled=raw.get("enabled", True) is True,
                source="local",
                record_id=str(raw.get("feishu_record_id")) if raw.get("feishu_record_id") else None,
            ))
        return result

    def _read_legacy_douyin(self) -> list[CreatorIdentity]:
        if not self.legacy_douyin_path.is_file():
            return []
        try:
            payload = json.loads(self.legacy_douyin_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise CreatorError("douyin-creators.json 不是有效 JSON") from exc
        rows = payload.get("creators", []) if isinstance(payload, dict) else []
        result: list[CreatorIdentity] = []
        for raw in rows:
            url = raw.get("url") if isinstance(raw, dict) else raw
            platform, platform_id, homepage = parse_creator_homepage(url)
            if platform != "抖音":
                continue
            name = str(raw.get("name") or "") if isinstance(raw, dict) else ""
            result.append(self._identity(platform, platform_id, homepage, display_name=name, source="legacy"))
        return result

    def load(self, feishu_bili: list[dict[str, object]] | None = None) -> list[CreatorIdentity]:
        merged: dict[tuple[str, str], CreatorIdentity] = {}
        for item in [*self._read_legacy_douyin(), *self._read_local()]:
            merged[(item.platform, item.platform_id)] = item
        for row in feishu_bili or []:
            mid = str(row.get("mid") or row.get("B站MID") or "").strip()
            if not mid.isdigit():
                continue
            key = ("B站", mid)
            name = str(row.get("name") or row.get("博主名称") or "").strip()
            record_id = str(row.get("record_id") or row.get("_record_id") or "").strip() or None
            existing = merged.get(key)
            if existing:
                display_name = name if existing.display_name == f"B站 {mid}" and name else existing.display_name
                merged[key] = replace(existing, display_name=display_name, feishu_record_id=record_id or existing.feishu_record_id)
            else:
                merged[key] = self._identity("B站", mid, f"https://space.bilibili.com/{mid}", display_name=name, source="feishu", record_id=record_id)
        return sorted(merged.values(), key=lambda item: (item.platform, item.display_name, item.platform_id))

    def _normalize_payload(self, creators: object) -> list[CreatorIdentity]:
        if not isinstance(creators, list):
            raise CreatorError("creators 必须是数组")
        normalized: list[CreatorIdentity] = []
        seen: set[tuple[str, str]] = set()
        for raw in creators:
            if not isinstance(raw, dict):
                raise CreatorError("博主记录必须是对象")
            platform, platform_id, homepage = parse_creator_homepage(raw.get("homepage_url"))
            key = (platform, platform_id)
            if key in seen:
                continue
            seen.add(key)
            normalized.append(self._identity(
                platform,
                platform_id,
                homepage,
                display_name=str(raw.get("display_name") or ""),
                enabled=raw.get("enabled", True) is True,
                source="local",
                record_id=str(raw.get("feishu_record_id")) if raw.get("feishu_record_id") else None,
            ))
        return normalized

    def save(self, creators: object) -> list[CreatorIdentity]:
        normalized = self._normalize_payload(creators)
        self.local_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.local_path.with_suffix(".json.tmp")
        payload = {"version": 1, "creators": [item.public() for item in normalized]}
        temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        temporary.replace(self.local_path)
        return normalized

    def select(self, local_ids: object, feishu_bili: list[dict[str, object]] | None = None) -> list[CreatorIdentity]:
        if not isinstance(local_ids, list) or any(not isinstance(item, str) for item in local_ids):
            raise CreatorError("selected creator IDs 必须是字符串数组")
        wanted = set(local_ids)
        selected = [item for item in self.load(feishu_bili) if item.local_id in wanted and item.enabled]
        if len(selected) != len(wanted):
            raise CreatorError("所选博主不存在或已停用")
        return selected
