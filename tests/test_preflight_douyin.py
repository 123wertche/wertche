import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import preflight_douyin as preflight
from preflight_douyin import run_utf8_command


class Utf8CommandTests(unittest.TestCase):
    def test_decodes_utf8_cli_output_independent_of_windows_code_page(self):
        completed = run_utf8_command([sys.executable, "-c", "print('授权成功')"], timeout=10)
        self.assertEqual(completed.returncode, 0)
        self.assertIn("授权成功", completed.stdout)

    def test_preflight_marks_missing_tool_with_hint_without_config_contents(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "feishu-base-config.json").write_text('{"profile":"x","secret":"private-value"}', encoding="utf-8")
            with patch.object(preflight, "available", return_value=None):
                result = preflight.build_result(root=root)
        self.assertEqual(result["checks"]["ffmpeg"]["status"], "missing")
        self.assertIn("ffmpeg", result["checks"]["ffmpeg"]["hint"])
        self.assertNotIn("private-value", json.dumps(result))


if __name__ == "__main__":
    unittest.main()
