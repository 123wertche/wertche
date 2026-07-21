import unittest

from recover_douyin_download_manifest import build_recovered_manifest


class RecoverManifestTests(unittest.TestCase):
    def test_builds_one_success_from_verified_video_manifest(self):
        video_manifest = {
            "ok": True,
            "started_at": "start",
            "ended_at": "end",
            "creator": {"key": "creator", "url": "https://www.douyin.com/user/example"},
            "aweme_id": "123",
            "video_url": "https://www.douyin.com/video/123",
            "metadata_path": "metadata.json",
        }
        metadata = {
            "page_metadata": {"title": "标题 - 抖音"},
            "selected_card": {"aweme_id": "123", "is_pinned": False},
            "selection_reason": "first_visible_no_pin_marker",
        }

        recovered = build_recovered_manifest(video_manifest, metadata)

        self.assertFalse(recovered["dry_run"])
        self.assertEqual(len(recovered["successes"]), 1)
        self.assertEqual(recovered["successes"][0]["aweme_id"], "123")
        self.assertEqual(recovered["parsed"][0]["selected"][0]["aweme_id"], "123")


if __name__ == "__main__":
    unittest.main()
