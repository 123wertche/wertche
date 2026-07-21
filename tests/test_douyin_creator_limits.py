import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import download_douyin_latest as douyin
from download_douyin_latest import extract_aweme_post_cards, fetch_latest_cards, load_creators, select_latest_cards


class DouyinCreatorLimitTests(unittest.TestCase):
    def test_unverified_dom_video_cards_are_not_used_without_an_official_post_response(self):
        choose_creator_candidates = getattr(douyin, "choose_creator_candidates", None)
        self.assertIsNotNone(choose_creator_candidates)
        dom_cards = [{"aweme_id": "123", "source": "anchor", "is_pinned": False}]

        self.assertEqual(choose_creator_candidates([], dom_cards), [])

    def test_max_creators_limits_json_config(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            config = Path(tmpdir) / "creators.json"
            config.write_text(
                json.dumps(
                    [
                        {"name": "one", "url": "https://www.douyin.com/user/one"},
                        {"name": "two", "url": "https://www.douyin.com/user/two"},
                    ]
                ),
                encoding="utf-8",
            )
            args = SimpleNamespace(
                from_feishu=False,
                creator_url=None,
                creators=str(config),
                max_creators=1,
            )

            creators = load_creators(args)

        self.assertEqual([creator["name"] for creator in creators], ["one"])

    def test_official_post_list_filters_author_and_sorts_before_skipping_pin(self):
        payload = {
            "aweme_list": [
                {"aweme_id": "old", "create_time": 100, "is_top": 0, "desc": "old", "video": {"duration": 1000}, "author": {"sec_uid": "creator"}},
                {"aweme_id": "other", "create_time": 400, "is_top": 0, "desc": "wrong", "video": {"duration": 1000}, "author": {"sec_uid": "other"}},
                {"aweme_id": "pinned", "create_time": 300, "is_top": 1, "desc": "pin", "video": {"duration": 1000}, "author": {"sec_uid": "creator"}},
                {"aweme_id": "latest", "create_time": 200, "is_top": 0, "desc": "latest", "video": {"duration": 1000}, "author": {"sec_uid": "creator"}},
            ]
        }

        cards = extract_aweme_post_cards(payload, "creator")
        selected = select_latest_cards(cards, 1)

        self.assertEqual([card["aweme_id"] for card in cards], ["pinned", "latest", "old"])
        self.assertEqual(selected[0]["aweme_id"], "latest")
        self.assertEqual(selected[0]["selection_reason"], "first_non_pinned_after_skipping_pinned")

    def test_official_post_list_excludes_articles_and_zero_duration_media(self):
        payload = {
            "aweme_list": [
                {
                    "aweme_id": "article",
                    "aweme_type": 163,
                    "create_time": 300,
                    "desc": "long article",
                    "article_info": {"article_id": "article"},
                    "video": {"duration": 0},
                    "author": {"sec_uid": "creator"},
                },
                {
                    "aweme_id": "video",
                    "aweme_type": 0,
                    "create_time": 200,
                    "desc": "real video",
                    "video": {"duration": 12000},
                    "author": {"sec_uid": "creator"},
                },
            ]
        }

        cards = extract_aweme_post_cards(payload, "creator")

        self.assertEqual([card["aweme_id"] for card in cards], ["video"])

    def test_live_empty_page_uses_recent_official_candidate_cache_after_retries(self):
        creator = {"key": "creator", "url": "https://www.douyin.com/user/creator"}
        cached = {
            "platform": "douyin",
            "parsed": [{
                "creator": creator,
                "candidates": [{"aweme_id": "123", "video_url": "https://www.douyin.com/video/123", "is_pinned": False}],
                "selected": [{"aweme_id": "123", "video_url": "https://www.douyin.com/video/123", "is_pinned": False}],
                "aweme_post_capture": {"captured": True, "captured_at": "2026-07-20T05:41:14Z"},
            }],
        }
        empty = {"creator": creator, "candidates": [], "selected": []}
        with tempfile.TemporaryDirectory() as tmpdir:
            cache_path = Path(tmpdir) / "20260720-000000-douyin-latest-download.json"
            cache_path.write_text(json.dumps(cached), encoding="utf-8")
            with patch("download_douyin_latest.MANIFEST_ROOT", Path(tmpdir)), patch(
                "download_douyin_latest.fetch_latest_cards_once", return_value=empty
            ), patch("download_douyin_latest.time.sleep"):
                result = fetch_latest_cards(creator, 1, retry_delays=(0,))

        self.assertEqual([item["aweme_id"] for item in result["selected"]], ["123"])
        self.assertEqual(result["page_status"], "live_unavailable_using_recent_official_cache")
        self.assertTrue(result["cache_fallback"]["used"])

    def test_live_page_exceptions_also_use_recent_official_candidate_cache(self):
        creator = {"key": "creator", "url": "https://www.douyin.com/user/creator"}
        cached = {
            "platform": "douyin",
            "parsed": [{
                "creator": creator,
                "candidates": [{"aweme_id": "123", "video_url": "https://www.douyin.com/video/123", "is_pinned": False}],
                "selected": [{"aweme_id": "123", "video_url": "https://www.douyin.com/video/123", "is_pinned": False}],
                "aweme_post_capture": {"captured": True, "captured_at": "2026-07-20T05:41:14Z"},
            }],
        }
        with tempfile.TemporaryDirectory() as tmpdir:
            cache_path = Path(tmpdir) / "20260720-000000-douyin-latest-download.json"
            cache_path.write_text(json.dumps(cached), encoding="utf-8")
            with patch("download_douyin_latest.MANIFEST_ROOT", Path(tmpdir)), patch(
                "download_douyin_latest.fetch_latest_cards_once", side_effect=RuntimeError("document body missing")
            ), patch("download_douyin_latest.time.sleep"):
                result = fetch_latest_cards(creator, 1, retry_delays=(0,))

        self.assertEqual([item["aweme_id"] for item in result["selected"]], ["123"])
        self.assertEqual(result["page_status"], "live_unavailable_using_recent_official_cache")

    def test_recent_live_failure_avoids_repeating_the_full_retry_loop(self):
        creator = {"key": "creator", "url": "https://www.douyin.com/user/creator"}
        official = {
            "platform": "douyin",
            "parsed": [{
                "creator": creator,
                "candidates": [{"aweme_id": "123", "video_url": "https://www.douyin.com/video/123", "is_pinned": False}],
                "selected": [{"aweme_id": "123", "video_url": "https://www.douyin.com/video/123", "is_pinned": False}],
                "aweme_post_capture": {"captured": True, "captured_at": "2026-07-20T05:41:14Z"},
            }],
            "failures": [],
        }
        recent_failure = {
            "platform": "douyin", "parsed": [],
            "failures": [{"creator": creator, "error": "page unavailable"}],
        }
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / "01-douyin-latest-download.json").write_text(json.dumps(official), encoding="utf-8")
            (root / "02-douyin-latest-download.json").write_text(json.dumps(recent_failure), encoding="utf-8")
            with patch("download_douyin_latest.MANIFEST_ROOT", root), patch(
                "download_douyin_latest.fetch_latest_cards_once"
            ) as live_fetch:
                result = fetch_latest_cards(creator, 1, retry_delays=(0,))

        live_fetch.assert_not_called()
        self.assertEqual([item["aweme_id"] for item in result["selected"]], ["123"])
        self.assertEqual(result["cache_fallback"]["reason"], "recent_live_failure_circuit_breaker")


if __name__ == "__main__":
    unittest.main()
