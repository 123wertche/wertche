import unittest

from merge_douyin_download_manifests import merge_download_manifests


class MergeDouyinManifestTests(unittest.TestCase):
    def test_merges_partial_retry_by_creator_url_and_deduplicates_video_ids(self):
        creator_one = {"key": "douyin_creator_1", "url": "https://www.douyin.com/user/one"}
        creator_four = {"key": "douyin_creator_4", "url": "https://www.douyin.com/user/four"}
        partial = {
            "platform": "douyin",
            "creators": [creator_one, creator_four],
            "successes": [
                {"ok": True, "aweme_id": "111", "creator": dict(creator_one)},
            ],
            "parsed": [
                {"creator": dict(creator_one), "selected": [{"aweme_id": "111"}]},
                {"creator": dict(creator_four), "selected": []},
            ],
            "failures": [{"creator": dict(creator_four), "error": "temporary empty page"}],
        }
        retry_alias = {"key": "douyin_creator_1", "url": creator_four["url"]}
        retry = {
            "platform": "douyin",
            "creators": [retry_alias],
            "successes": [
                {"ok": True, "aweme_id": "444", "creator": dict(retry_alias)},
                {"ok": True, "aweme_id": "444", "creator": dict(retry_alias)},
            ],
            "parsed": [
                {"creator": dict(retry_alias), "selected": [{"aweme_id": "444"}]},
            ],
            "failures": [],
        }

        merged = merge_download_manifests([partial, retry], source_names=["partial.json", "retry.json"])

        self.assertEqual([item["aweme_id"] for item in merged["successes"]], ["111", "444"])
        recovered = next(item for item in merged["successes"] if item["aweme_id"] == "444")
        self.assertEqual(recovered["creator"]["key"], "douyin_creator_4")
        self.assertEqual(merged["failures"], [])
        self.assertEqual(merged["summary"]["downloaded"], 2)
        self.assertEqual(merged["source_manifests"], ["partial.json", "retry.json"])

    def test_excludes_explicitly_invalid_non_video_ids(self):
        creator = {"key": "creator", "url": "https://www.douyin.com/user/one"}
        manifest = {
            "creators": [creator],
            "successes": [
                {"ok": True, "aweme_id": "article", "creator": creator},
                {"ok": True, "aweme_id": "video", "creator": creator},
            ],
            "parsed": [],
            "failures": [],
        }

        merged = merge_download_manifests([manifest], excluded_ids={"article"})

        self.assertEqual([item["aweme_id"] for item in merged["successes"]], ["video"])
        self.assertEqual(merged["summary"]["downloaded"], 1)


if __name__ == "__main__":
    unittest.main()
