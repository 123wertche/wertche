import unittest

from douyin_metrics import extract_aweme_metrics, first_aweme_detail_response
from download_douyin_latest import select_latest_cards


class DouyinMetricsTests(unittest.TestCase):
    def test_extracts_official_statistics_with_json_paths(self):
        payload = {
            "aweme_detail": {
                "aweme_id": "123",
                "statistics": {
                    "play_count": 0,
                    "digg_count": 12,
                    "comment_count": 3,
                    "share_count": 4,
                    "collect_count": 5,
                    "finish_rate": 0.82,
                    "skip_2s_rate": 0.11,
                    "finish_5s_rate": 0.73,
                },
            }
        }

        result = extract_aweme_metrics(payload, "123")

        self.assertEqual(result["values"]["播放量"], 0)
        self.assertEqual(result["values"]["点赞数"], 12)
        self.assertEqual(result["values"]["整体完播率"], 0.82)
        self.assertEqual(result["source_paths"]["收藏数"], "$.aweme_detail.statistics.collect_count")
        self.assertEqual(result["unavailable"], [])

    def test_marks_only_missing_retention_metrics_unavailable(self):
        payload = {
            "aweme_detail": {
                "aweme_id": "123",
                "statistics": {
                    "play_count": 1,
                    "digg_count": 2,
                    "comment_count": 3,
                    "share_count": 4,
                    "collect_count": 5,
                },
            }
        }

        result = extract_aweme_metrics(payload, "123")

        self.assertEqual(result["unavailable"], ["整体完播率", "2秒跳出率", "5秒完播率"])
        self.assertIsNone(result["values"]["整体完播率"])
        self.assertEqual(result["availability_note"], "整体完播率、2秒跳出率、5秒完播率：数据不可用（官方 aweme/detail 响应未提供）")

    def test_selects_first_response_for_matching_video_only(self):
        responses = [
            {"url": "https://www.douyin.com/aweme/v1/web/aweme/detail/?aweme_id=999", "body": {"aweme_detail": {"aweme_id": "999"}}},
            {"url": "https://www.douyin.com/aweme/v1/web/aweme/detail/?aweme_id=123", "body": {"aweme_detail": {"aweme_id": "123", "statistics": {}}}},
            {"url": "https://www.douyin.com/aweme/v1/web/aweme/detail/?aweme_id=123", "body": {"aweme_detail": {"aweme_id": "123", "statistics": {"play_count": 9}}}},
        ]

        selected = first_aweme_detail_response(responses, "123")

        self.assertEqual(selected["body"]["aweme_detail"]["statistics"], {})

    def test_never_falls_back_to_a_pinned_video(self):
        cards = [{"aweme_id": "1", "is_pinned": True}]

        self.assertEqual(select_latest_cards(cards, 1), [])


if __name__ == "__main__":
    unittest.main()
