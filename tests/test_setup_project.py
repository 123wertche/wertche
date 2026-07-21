import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
REQUIREMENTS = ROOT / "requirements.txt"
LARK_PACKAGE = ROOT / "tools" / "lark" / "package.json"
SETUP = ROOT / "setup_project.ps1"
LAUNCHER = ROOT / "初始化项目.cmd"
README = ROOT / "README.md"


class SetupProjectTests(unittest.TestCase):
    def test_dependency_manifests_pin_runtime_dependencies(self):
        requirements = REQUIREMENTS.read_text(encoding="utf-8")
        self.assertIn("openai-whisper==", requirements)
        self.assertIn("yt-dlp==", requirements)
        package = json.loads(LARK_PACKAGE.read_text(encoding="utf-8"))
        self.assertEqual(package["dependencies"]["@larksuite/cli"], "1.0.70")

    def test_setup_script_uses_project_local_paths_and_safe_switches(self):
        script = SETUP.read_text(encoding="utf-8")
        self.assertIn("[switch]$CheckOnly", script)
        self.assertIn("[switch]$SkipDownload", script)
        self.assertIn("tools\\node", script)
        self.assertIn("preflight_douyin.py", script)
        self.assertNotIn("setx PATH", script)
        self.assertIn("setup_project.ps1", LAUNCHER.read_text(encoding="utf-8"))

    def test_setup_extracts_node_archive_with_a_glob_expanding_copy(self):
        script = SETUP.read_text(encoding="utf-8")
        self.assertIn("Copy-Item -Path (Join-Path $expanded.FullName '*')", script)

    def test_setup_normalizes_bootstrap_python_to_an_argument_array(self):
        script = SETUP.read_text(encoding="utf-8")
        self.assertIn("$bootstrap = @(Find-BootstrapPython)", script)

    def test_setup_validates_a_bootstrap_python_before_using_it(self):
        script = SETUP.read_text(encoding="utf-8")
        self.assertIn("function Test-BootstrapPython", script)
        self.assertIn("import sys, venv", script)
        self.assertIn("Test-BootstrapPython -File $python.Source", script)

    def test_setup_does_not_reverse_slice_a_single_bootstrap_command(self):
        script = SETUP.read_text(encoding="utf-8")
        self.assertIn("if ($bootstrap.Count -gt 1)", script)
        self.assertIn("$bootstrap[1..($bootstrap.Count - 1)]", script)

    def test_readme_documents_secure_first_run_and_manual_auth_boundaries(self):
        text = README.read_text(encoding="utf-8")
        self.assertIn("初始化项目.cmd", text)
        self.assertIn("feishu-base-config.json", text)
        self.assertIn("不会上传", text)


if __name__ == "__main__":
    unittest.main()
