import json
import tempfile
import unittest
from pathlib import Path

from enrich_douyin_feishu import (
    filter_patch_for_fields,
    load_manifest_aweme_ids,
    parse_args,
    validate_manifest_output,
    update_creator_from_video,
)


class EnrichFieldSafetyTests(unittest.TestCase):
    def test_manifest_scope_includes_successful_and_existing_video_ids(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            manifest_path = Path(temp_dir) / "download.json"
            manifest_path.write_text(
                json.dumps(
                    {
                        "successes": [{"aweme_id": "111"}],
                        "skipped_existing": [{"aweme_id": "222"}],
                    }
                ),
                encoding="utf-8",
            )

            self.assertEqual(load_manifest_aweme_ids(manifest_path), {"111", "222"})

    def test_filters_patch_to_fields_that_exist_in_target_table(self):
        patch = {"内容摘要": "摘要", "高赞评论摘要": "不可用", "评论抓取状态": "跳过"}

        filtered = filter_patch_for_fields(patch, {"内容摘要": {}, "评论抓取状态": {}})

        self.assertEqual(filtered, {"内容摘要": "摘要", "评论抓取状态": "跳过"})

    def test_skips_optional_creator_stats_when_fields_do_not_exist(self):
        metadata = {"page_metadata": {"body_excerpt": "粉丝 3340 获赞 1.2万"}}
        video = {"博主": [{"id": "recCreator"}]}

        result = update_creator_from_video(
            {},
            video,
            metadata,
            {"recCreator": {}},
            {"最近采集时间": {}},
            dry_run=True,
        )

        self.assertIsNone(result)

    def test_accepts_download_manifest_as_an_explicit_input_scope(self):
        args = parse_args(["--manifest", "downloads/manifests/input.json"])

        self.assertEqual(args.manifest, "downloads/manifests/input.json")
        self.assertIsNone(args.manifest_output)

    def test_refuses_to_overwrite_a_download_manifest(self):
        with self.assertRaisesRegex(ValueError, "download manifest"):
            validate_manifest_output("downloads/manifests/20260716-douyin-latest-download.json")


if __name__ == "__main__":
    unittest.main()
