"""Pure helpers for metrics captured from a first-load Douyin aweme/detail response."""

from __future__ import annotations

from typing import Any


BASE_METRIC_KEYS = {
    "播放量": ("play_count",),
    "点赞数": ("digg_count",),
    "评论数": ("comment_count",),
    "转发数": ("share_count",),
    "收藏数": ("collect_count",),
}
RETENTION_METRIC_KEYS = {
    "整体完播率": ("finish_rate", "completion_rate", "overall_completion_rate"),
    "2秒跳出率": ("skip_2s_rate", "two_second_skip_rate", "jump_2s_rate"),
    "5秒完播率": ("finish_5s_rate", "five_second_finish_rate", "completion_5s_rate"),
}


def _aweme_detail(payload: dict[str, Any], aweme_id: str) -> tuple[dict[str, Any], str]:
    detail = payload.get("aweme_detail")
    if isinstance(detail, dict) and str(detail.get("aweme_id") or aweme_id) == str(aweme_id):
        return detail, "$.aweme_detail"
    data = payload.get("data")
    if isinstance(data, dict):
        detail = data.get("aweme_detail")
        if isinstance(detail, dict) and str(detail.get("aweme_id") or aweme_id) == str(aweme_id):
            return detail, "$.data.aweme_detail"
    return {}, ""


def _find_numeric(mapping: dict[str, Any], keys: tuple[str, ...], prefix: str) -> tuple[float | int | None, str | None]:
    for key in keys:
        value = mapping.get(key)
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return value, f"{prefix}.{key}"
    return None, None


def extract_aweme_metrics(payload: dict[str, Any], aweme_id: str) -> dict[str, Any]:
    """Extract values only when the captured response explicitly exposes them."""
    detail, detail_path = _aweme_detail(payload, aweme_id)
    statistics = detail.get("statistics") if isinstance(detail.get("statistics"), dict) else {}
    values: dict[str, float | int | None] = {}
    source_paths: dict[str, str] = {}
    unavailable: list[str] = []
    for label, keys in BASE_METRIC_KEYS.items():
        value, path = _find_numeric(statistics, keys, f"{detail_path}.statistics")
        values[label] = value
        if path:
            source_paths[label] = path
    for label, keys in RETENTION_METRIC_KEYS.items():
        value, path = _find_numeric(statistics, keys, f"{detail_path}.statistics")
        values[label] = value
        if path:
            source_paths[label] = path
        else:
            unavailable.append(label)
    note = ""
    if unavailable:
        note = "、".join(unavailable) + "：数据不可用（官方 aweme/detail 响应未提供）"
    return {
        "values": values,
        "source_paths": source_paths,
        "unavailable": unavailable,
        "availability_note": note,
    }


def first_aweme_detail_response(responses: list[dict[str, Any]], aweme_id: str) -> dict[str, Any] | None:
    """Return the first captured official detail response for exactly one video."""
    for response in responses:
        url = str(response.get("url") or "")
        body = response.get("body")
        if "aweme/detail" not in url or not isinstance(body, dict):
            continue
        detail, _ = _aweme_detail(body, aweme_id)
        if detail:
            return response
    return None
