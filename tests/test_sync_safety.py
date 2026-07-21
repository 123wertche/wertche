import json
import tempfile
import unittest
from pathlib import Path

from sync_douyin_to_feishu import (
    VIDEO_FIELDS,
    lark_relative_file,
    load_creator_config,
    required_metric_error,
    resolve_creator_link_field,
    should_update_existing_video,
    update_video_metrics,
)
from download_bili_following_latest import command_env, redact_command_args


class SyncSafetyTests(unittest.TestCase):
    def test_creator_config_accepts_legacy_object_wrapper(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "douyin-creators.json"
            path.write_text(json.dumps({"creators": [{"key": "one", "url": "https://example.test"}]}), encoding="utf-8")

            self.assertEqual(load_creator_config(path)["one"]["url"], "https://example.test")

    def test_only_same_platform_video_id_can_update_existing_row(self):
        self.assertTrue(should_update_existing_video("same_platform_id"))
        self.assertFalse(should_update_existing_video("same_title"))
        self.assertFalse(should_update_existing_video("similar_title"))

    def test_blocks_sync_when_a_required_metric_is_absent(self):
        metrics = {"播放量": 0, "点赞数": 1, "评论数": 2, "转发数": 3, "收藏数": None}

        self.assertEqual(required_metric_error(metrics), "基础指标数据不可用：收藏数")

    def test_redacts_lark_base_token_in_failures(self):
        self.assertEqual(redact_command_args(["lark-cli", "--base-token", "secret", "--table-id", "tbl"]), ["lark-cli", "--base-token", "***", "--table-id", "tbl"])

    def test_project_commands_are_first_on_path(self):
        path = command_env()["PATH"].lower()
        self.assertIn(".venv\\lark\\node_modules\\.bin", path)
        self.assertIn(".venv\\scripts", path)

    def test_uses_existing_creator_link_field_name(self):
        self.assertEqual(resolve_creator_link_field({"博主": {"type": "link"}}), "博主")
        self.assertEqual(resolve_creator_link_field({"关联博主": {"type": "link"}}), "关联博主")

    def test_metadata_path_field_is_managed(self):
        self.assertEqual(VIDEO_FIELDS["元数据文件路径"]["type"], "text")

    def test_attachment_path_is_relative_to_project_root(self):
        relative = lark_relative_file("downloads/douyin/example/cover.jpg")

        self.assertEqual(relative.replace("\\", "/"), "downloads/douyin/example/cover.jpg")

    def test_same_id_update_refreshes_local_artifact_paths(self):
        patch = update_video_metrics(
            None,
            "record-id",
            {
                "title": "title",
                "video_url": "https://www.douyin.com/video/123",
                "video_path": "video.mp4",
                "metadata_path": "metadata.json",
                "description_path": "description.txt",
                "cover_path": "cover.jpg",
                "audio_path": "audio.wav",
                "speech_raw_path": "raw.txt",
                "speech_clean_path": "clean.txt",
                "metrics": {},
            },
            dry_run=True,
        )

        for expected in ("video.mp4", "metadata.json", "description.txt", "cover.jpg", "audio.wav", "raw.txt", "clean.txt"):
            self.assertIn(expected, patch.values())


if __name__ == "__main__":
    unittest.main()
