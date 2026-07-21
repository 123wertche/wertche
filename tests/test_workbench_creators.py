import json
import tempfile
import unittest
from pathlib import Path

from workbench_creators import CreatorError, CreatorRegistry, parse_creator_homepage


DOUYIN_URL = "https://www.douyin.com/user/MS4wLjABAAAAabc"
BILI_URL = "https://space.bilibili.com/12345"


class CreatorRegistryTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)
        self.legacy = self.root / "douyin-creators.json"
        self.local = self.root / "workbench-creators.json"
        self.registry = CreatorRegistry(self.local, self.legacy)

    def tearDown(self):
        self.tempdir.cleanup()

    def test_preview_recognizes_both_platforms_and_deduplicates_query_variants(self):
        result = self.registry.preview([
            DOUYIN_URL + "?from_tab_name=main",
            BILI_URL + "/",
            BILI_URL,
        ])
        self.assertEqual(
            [(item["platform"], item["platform_id"]) for item in result["creators"]],
            [("抖音", "MS4wLjABAAAAabc"), ("B站", "12345")],
        )

    def test_rejects_non_homepage_or_unidentifiable_url(self):
        with self.assertRaisesRegex(CreatorError, "无法识别"):
            parse_creator_homepage("https://www.bilibili.com/video/BV1test")

    def test_load_merges_legacy_local_and_feishu_bili_by_platform_identity(self):
        self.legacy.write_text(json.dumps({"creators": [{"url": DOUYIN_URL}]}), encoding="utf-8")
        preview = self.registry.preview([BILI_URL])
        self.registry.save(preview["creators"])
        merged = self.registry.load(feishu_bili=[{"mid": "12345", "name": "B博主", "record_id": "rec1"}])
        self.assertEqual(len(merged), 2)
        bili = next(item for item in merged if item.platform == "B站")
        self.assertEqual(bili.feishu_record_id, "rec1")
        self.assertEqual(bili.display_name, "B博主")

    def test_save_is_atomic_and_selection_rejects_missing_or_disabled_creator(self):
        preview = self.registry.preview([DOUYIN_URL, BILI_URL])
        saved = self.registry.save(preview["creators"])
        self.assertEqual(len(saved), 2)
        payload = json.loads(self.local.read_text(encoding="utf-8"))
        self.assertEqual(payload["version"], 1)
        self.assertFalse(self.local.with_suffix(".json.tmp").exists())
        selected = self.registry.select([saved[0].local_id])
        self.assertEqual(selected[0].local_id, saved[0].local_id)
        with self.assertRaisesRegex(CreatorError, "不存在或已停用"):
            self.registry.select(["missing"])


if __name__ == "__main__":
    unittest.main()
