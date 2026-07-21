import unittest

from download_douyin_latest import extract_aweme_stream, fetch_video_metadata_with_retry


class DouyinStreamTests(unittest.TestCase):
    def test_selects_highest_bitrate_cdn_stream_for_matching_aweme(self):
        payload = {
            "aweme_detail": {
                "aweme_id": "123",
                "video": {
                    "bit_rate": [
                        {
                            "bit_rate": 600000,
                            "play_addr": {
                                "url_list": [
                                    "https://www.douyin.com/aweme/v1/play/?video_id=low",
                                    "https://cdn.example/low.mp4",
                                ]
                            },
                            "width": 720,
                            "height": 1280,
                        },
                        {
                            "bit_rate": 1200000,
                            "play_addr": {
                                "url_list": [
                                    "https://www.douyin.com/aweme/v1/play/?video_id=high",
                                    "https://cdn.example/high.mp4",
                                ]
                            },
                            "width": 1080,
                            "height": 1920,
                        },
                    ]
                },
            }
        }

        result = extract_aweme_stream(payload, "123")

        self.assertEqual(result["video_url"], "https://cdn.example/high.mp4")
        self.assertEqual(result["bit_rate"], 1200000)
        self.assertEqual(result["width"], 1080)
        self.assertEqual(result["height"], 1920)
        self.assertEqual(result["source_path"], "$.aweme_detail.video.bit_rate[1].play_addr.url_list[1]")

    def test_rejects_response_for_a_different_aweme(self):
        payload = {
            "aweme_detail": {
                "aweme_id": "999",
                "video": {
                    "play_addr": {"url_list": ["https://cdn.example/wrong.mp4"]}
                },
            }
        }

        self.assertIsNone(extract_aweme_stream(payload, "123"))

    def test_rejects_article_audio_placeholder_as_video_stream(self):
        payload = {
            "aweme_detail": {
                "aweme_id": "123",
                "aweme_type": 163,
                "article_info": {"article_id": "123"},
                "video": {
                    "duration": 0,
                    "play_addr": {"url_list": ["https://cdn.example/article-audio.mp4"]},
                },
            }
        }

        self.assertIsNone(extract_aweme_stream(payload, "123"))

    def test_reopens_video_until_official_detail_contains_a_stream(self):
        responses = [
            {"aweme_detail_capture": {"response_body": None}},
            {"aweme_detail_capture": {"response_body": {"aweme_detail": {"aweme_id": "123", "video": {}}}}},
            {
                "aweme_detail_capture": {
                    "response_body": {
                        "aweme_detail": {
                            "aweme_id": "123",
                            "video": {"play_addr": {"url_list": ["https://cdn.example/video.mp4"]}},
                        }
                    }
                }
            },
        ]
        calls = []

        def fetcher(video_url, aweme_id):
            calls.append((video_url, aweme_id))
            return responses[len(calls) - 1]

        result = fetch_video_metadata_with_retry(
            "https://www.douyin.com/video/123",
            "123",
            retry_delays=(0, 0),
            fetcher=fetcher,
        )

        self.assertEqual(len(calls), 3)
        self.assertEqual(
            extract_aweme_stream(result["aweme_detail_capture"]["response_body"], "123")["video_url"],
            "https://cdn.example/video.mp4",
        )


if __name__ == "__main__":
    unittest.main()
