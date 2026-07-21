import json
import tempfile
import unittest
from pathlib import Path

from download_bili_following_latest import resolve_selected_creators


class BiliCreatorSelectionTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.creator_file = Path(self.tempdir.name) / "workbench-creators.json"
        self.creator_file.write_text(json.dumps({
            "version": 1,
            "creators": [{
                "local_id": "b3",
                "platform": "B站",
                "platform_id": "3",
                "homepage_url": "https://space.bilibili.com/3",
                "display_name": "本地博主",
                "enabled": True,
                "source": "local",
                "feishu_record_id": None,
            }],
        }), encoding="utf-8")

    def tearDown(self):
        self.tempdir.cleanup()

    def test_selected_mids_filter_feishu_rows(self):
        rows = [
            {"name": "一", "mid": "1", "record_id": "rec1"},
            {"name": "二", "mid": "2", "record_id": "rec2"},
        ]
        selected = resolve_selected_creators({}, ["2"], None, True, rows=rows)
        self.assertEqual([item["mid"] for item in selected], ["2"])

    def test_dry_run_accepts_local_missing_creator_but_real_run_rejects_it(self):
        dry = resolve_selected_creators({}, ["3"], self.creator_file, True, rows=[], root=self.creator_file.parent)
        self.assertTrue(dry[0]["missing_feishu_creator"])
        with self.assertRaisesRegex(RuntimeError, "缺少飞书博主记录"):
            resolve_selected_creators({}, ["3"], self.creator_file, False, rows=[], root=self.creator_file.parent)


if __name__ == "__main__":
    unittest.main()
