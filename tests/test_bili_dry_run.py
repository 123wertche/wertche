import sys
import unittest
from unittest.mock import patch

import download_bili_following_latest as bili


class BilibiliDryRunTests(unittest.TestCase):
    def test_dry_run_lists_latest_candidates_without_feishu_or_media_writes(self):
        creator = {"name": "测试博主", "mid": "1", "record_id": "rec_creator"}
        video = {"bvid": "BV1test", "url": "https://www.bilibili.com/video/BV1test"}
        with (
            patch.object(sys, "argv", ["download_bili_following_latest.py", "--dry-run", "--videos-per-creator", "1"]),
            patch.object(bili, "ensure_dirs"),
            patch.object(bili, "load_config", return_value={"base_url": "https://example.test"}),
            patch.object(bili, "precheck"),
            patch.object(bili, "ensure_video_fields") as ensure_fields,
            patch.object(bili, "load_creators", return_value=[creator]),
            patch.object(bili, "existing_bvids", return_value=set()),
            patch.object(bili, "fetch_latest_entries", return_value=([video], "")),
            patch.object(bili, "write_manifest") as write_manifest,
            patch.object(bili, "batch_create_video_records") as create_records,
            patch.object(bili, "batch_create_metric_snapshots") as create_snapshots,
            patch.object(bili, "create_task_log") as create_task_log,
        ):
            bili.main()
        ensure_fields.assert_not_called()
        create_records.assert_not_called()
        create_snapshots.assert_not_called()
        create_task_log.assert_not_called()
        self.assertTrue(write_manifest.called)


if __name__ == "__main__":
    unittest.main()
