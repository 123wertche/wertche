import json
import unittest
from urllib.parse import quote

from download_douyin_latest import (
    annotate_ssr_metric_result,
    apply_verified_creator_identity,
    explicit_modal_selection,
    extract_ssr_video_detail,
    fetch_video_metadata_with_official_fallback,
    ssr_detail_to_aweme_payload,
)


class DouyinSsrFallbackTests(unittest.TestCase):
    def setUp(self):
        self.detail = {
            "awemeId": "123",
            "awemeType": 0,
            "desc": "A verified title",
            "createTime": 100,
            "authorInfo": {"secUid": "creator-sec-uid", "nickname": "Creator"},
            "stats": {
                "playCount": 0,
                "diggCount": 12,
                "commentCount": 3,
                "shareCount": 4,
                "collectCount": 5,
            },
            "video": {
                "duration": 1000,
                "width": 1080,
                "height": 1920,
                "playAddr": {"urlList": ["https://media.example/video.mp4"]},
                "coverUrlList": ["https://img.example/cover.jpg"],
                "bitRateList": [
                    {
                        "bitRate": 123456,
                        "playAddr": {"urlList": ["https://media.example/high.mp4"]},
                    }
                ],
            },
            "tag": {"isTop": False},
        }

    def encoded_page_state(self):
        root = {"app": {"videoDetail": self.detail}}
        return quote(json.dumps(root, ensure_ascii=False), safe="")

    def test_extracts_only_the_requested_video_and_creator(self):
        result = extract_ssr_video_detail(
            self.encoded_page_state(), "123", expected_sec_uid="creator-sec-uid"
        )

        self.assertEqual(result["awemeId"], "123")
        self.assertEqual(result["authorInfo"]["secUid"], "creator-sec-uid")
        self.assertIsNone(extract_ssr_video_detail(self.encoded_page_state(), "999"))
        self.assertIsNone(
            extract_ssr_video_detail(
                self.encoded_page_state(), "123", expected_sec_uid="another-creator"
            )
        )

    def test_normalizes_ssr_detail_without_inventing_retention_metrics(self):
        payload = ssr_detail_to_aweme_payload(self.detail)
        detail = payload["aweme_detail"]

        self.assertEqual(detail["aweme_id"], "123")
        self.assertEqual(detail["statistics"]["play_count"], 0)
        self.assertEqual(detail["statistics"]["collect_count"], 5)
        self.assertNotIn("finish_rate", detail["statistics"])
        self.assertEqual(
            detail["video"]["bit_rate"][0]["play_addr"]["url_list"],
            ["https://media.example/high.mp4"],
        )
        self.assertEqual(
            detail["video"]["cover"]["url_list"],
            ["https://img.example/cover.jpg"],
        )

    def test_explicit_modal_url_is_scoped_to_its_profile_and_video(self):
        url = (
            "https://www.douyin.com/user/creator-sec-uid"
            "?modal_id=7654922676779093282"
        )

        creator, selected = explicit_modal_selection(url)

        self.assertEqual(creator["sec_uid"], "creator-sec-uid")
        self.assertEqual(selected["aweme_id"], "7654922676779093282")
        self.assertEqual(selected["video_url"], url)
        with self.assertRaises(ValueError):
            explicit_modal_selection("https://www.douyin.com/user/creator-sec-uid")

    def test_normalizes_live_ssr_play_address_array_shape(self):
        detail = dict(self.detail)
        detail["video"] = dict(self.detail["video"])
        detail["video"]["playAddr"] = [{"src": "https://media.example/main.mp4"}]
        detail["video"]["bitRateList"] = [
            {
                "bitRate": 654321,
                "playAddr": [{"src": "https://media.example/live-high.mp4"}],
            }
        ]

        payload = ssr_detail_to_aweme_payload(detail)

        self.assertEqual(
            payload["aweme_detail"]["video"]["bit_rate"][0]["play_addr"]["url_list"],
            ["https://media.example/live-high.mp4"],
        )

    def test_ssr_note_identifies_missing_retention_and_official_zero_play_count(self):
        payload = ssr_detail_to_aweme_payload(self.detail)
        metric_result = {
            "values": {},
            "source_paths": {},
            "unavailable": ["overall completion rate"],
            "availability_note": "old source note",
        }

        result = annotate_ssr_metric_result(metric_result, payload)

        self.assertIn("SSR", result["availability_note"])
        self.assertIn("0", result["availability_note"])
        self.assertIn("official", result["availability_note"].lower())

    def test_standard_video_metadata_uses_ssr_only_after_detail_failure(self):
        calls = []

        def detail_fetcher(video_url, aweme_id):
            calls.append(("detail", video_url, aweme_id))
            raise RuntimeError("aweme/detail unavailable")

        def ssr_fetcher(video_url, aweme_id, sec_uid):
            calls.append(("ssr", video_url, aweme_id, sec_uid))
            return {"official_source": "douyin_ssr_page_state"}

        result = fetch_video_metadata_with_official_fallback(
            "https://www.douyin.com/video/123",
            "123",
            {
                "url": "https://www.douyin.com/user/creator-sec-uid?from_tab_name=main",
                "sec_uid": "creator-sec-uid",
            },
            detail_fetcher=detail_fetcher,
            ssr_fetcher=ssr_fetcher,
        )

        self.assertEqual(result["official_source"], "douyin_ssr_page_state")
        self.assertEqual(calls[0][0], "detail")
        self.assertEqual(
            calls[1],
            (
                "ssr",
                "https://www.douyin.com/user/creator-sec-uid?modal_id=123",
                "123",
                "creator-sec-uid",
            ),
        )

    def test_verified_ssr_nickname_replaces_only_the_placeholder_name(self):
        payload = ssr_detail_to_aweme_payload(self.detail)
        page_meta = {"aweme_detail_capture": {"response_body": payload}}
        creator = {
            "name": "Douyin creator",
            "sec_uid": "creator-sec-uid",
        }

        result = apply_verified_creator_identity(creator, page_meta)

        self.assertEqual(result["name"], "Creator")
        self.assertEqual(creator["name"], "Creator")


if __name__ == "__main__":
    unittest.main()
