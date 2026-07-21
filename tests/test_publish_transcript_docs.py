import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from publish_transcript_docs_to_feishu import (
    DEFAULT_PARENT_POSITION,
    load_manifest_video_ids,
    manifest_base_metadata,
    select_rows,
)


class ParentLocationTests(unittest.TestCase):
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

            self.assertEqual(load_manifest_video_ids(manifest_path), {"111", "222"})

    def test_manifest_video_ids_limit_document_selection(self):
        args = SimpleNamespace(record_id=None, platform="抖音", max_records=8, all=False)
        rows = [
            {"_record_id": "wanted", "平台": "抖音", "平台视频ID": "111"},
            {"_record_id": "old", "平台": "抖音", "平台视频ID": "999"},
        ]

        selected = select_rows(rows, args, {"111"})

        self.assertEqual([item["_record_id"] for item in selected], ["wanted"])

    def test_defaults_to_current_users_library(self):
        self.assertEqual(DEFAULT_PARENT_POSITION, "my_library")

    def test_manifest_never_contains_base_token(self):
        metadata = manifest_base_metadata({"base_name": "base", "base_token": "secret", "tables": {"videos": {"table_id": "tbl"}}})

        self.assertNotIn("base_token", metadata)
        self.assertTrue(metadata["base_token_configured"])


if __name__ == "__main__":
    unittest.main()
