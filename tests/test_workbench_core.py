import json
import io
import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path

from workbench_core import (
    ActionSpec,
    ArtifactIndexer,
    BrowserLifecycle,
    CreatorStore,
    DryRunProofStore,
    HealthInspector,
    ProcessRunner,
    ProjectPaths,
    TaskRegistry,
    WorkbenchError,
    build_action,
)


class WorkbenchCoreTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)
        (self.root / ".venv" / "Scripts").mkdir(parents=True)
        (self.root / ".venv" / "Scripts" / "python.exe").write_text("", encoding="utf-8")
        (self.root / "downloads" / "manifests").mkdir(parents=True)
        self.paths = ProjectPaths.from_root(self.root)
        self.url = "https://www.douyin.com/user/MS4wLjABAAAAexample"

    def tearDown(self):
        self.tempdir.cleanup()

    def test_build_douyin_download_uses_argument_list_and_validated_homepages(self):
        spec = build_action(
            "douyin_download",
            {"creator_urls": [self.url], "videos_per_creator": 1, "dry_run": True},
            self.paths,
        )
        self.assertEqual(spec.argv[:2], [str(self.paths.python), "download_douyin_latest.py"])
        self.assertIn("--creator-url", spec.argv)
        self.assertIn("--from-feishu", spec.argv)
        self.assertIn("--dry-run", spec.argv)
        self.assertNotIn("shell", spec.argv)
        self.assertIsNone(spec.write_kind)

    def test_build_action_rejects_unknown_action_and_external_manifest(self):
        with self.assertRaisesRegex(WorkbenchError, "unsupported action"):
            build_action("powershell", {"command": "Remove-Item C:\\"}, self.paths)
        with self.assertRaisesRegex(WorkbenchError, "inside downloads/manifests"):
            build_action("douyin_sync", {"manifest": "C:/outside.json", "dry_run": True}, self.paths)

    def test_manifest_scope_is_forwarded_to_enrich_and_document_publish(self):
        manifest = self.paths.manifests_root / "run-douyin-latest-download.json"
        manifest.write_text("{}", encoding="utf-8")

        enrich = build_action("douyin_enrich", {"manifest": str(manifest), "dry_run": True}, self.paths)
        publish = build_action("douyin_publish_docs", {"manifest": str(manifest), "dry_run": True}, self.paths)

        self.assertIn("--manifest", enrich.argv)
        self.assertIn("--manifest", publish.argv)

    def test_video_table_export_has_json_extension(self):
        spec = build_action("export_video_table", {}, self.paths)

        self.assertTrue(spec.argv[spec.argv.index("--output") + 1].endswith(".json"))
        self.assertIn("--xlsx-output", spec.argv)
        self.assertTrue(spec.argv[spec.argv.index("--xlsx-output") + 1].endswith(".xlsx"))

    def test_bili_download_requires_a_dry_run_before_its_feishu_write(self):
        dry_run = build_action("bili_download", {"creator_mids": ["123", "456"], "dry_run": True}, self.paths)
        real_run = build_action("bili_download", {"creator_mids": ["123", "456"]}, self.paths)
        self.assertIn("--dry-run", dry_run.argv)
        self.assertEqual(dry_run.argv.count("--creator-mid"), 2)
        self.assertIn("2", dry_run.argv)
        self.assertIsNone(dry_run.write_kind)
        self.assertEqual(real_run.write_kind, "feishu")

    def test_bili_creator_sync_uses_local_ids_and_is_a_confirmed_write(self):
        dry = build_action("bili_creator_sync", {"creator_ids": ["abc123"], "dry_run": True}, self.paths)
        real = build_action("bili_creator_sync", {"creator_ids": ["abc123"]}, self.paths)
        self.assertIn("--creator-id", dry.argv)
        self.assertIn("--dry-run", dry.argv)
        self.assertIsNone(dry.write_kind)
        self.assertEqual(real.write_kind, "feishu")

    def test_creator_store_deduplicates_and_writes_atomically(self):
        store = CreatorStore(self.paths.creators)
        preview = store.preview([self.url, self.url + "?from_tab_name=main"])
        self.assertEqual(preview["normalized_urls"], [self.url])
        saved = store.save(preview["normalized_urls"])
        self.assertEqual(saved["count"], 1)
        payload = json.loads(self.paths.creators.read_text(encoding="utf-8"))
        self.assertEqual(payload["creators"][0]["url"], self.url)

    def test_feishu_write_requires_matching_recent_dry_run_and_confirmation_phrase(self):
        proofs = DryRunProofStore()
        spec = ActionSpec("douyin_sync", ["python", "sync_douyin_to_feishu.py"], "feishu", [])
        proof = proofs.issue_from_successful_dry_run("douyin_sync", {"manifest": None}, now=100)
        self.assertTrue(proofs.authorize(spec, {"manifest": None}, proof.phrase, now=101))
        self.assertFalse(proofs.authorize(spec, {"manifest": "other.json"}, proof.phrase, now=101))
        self.assertFalse(proofs.authorize(spec, {"manifest": None}, proof.phrase, now=1901))

    def test_task_registry_keeps_incremental_log_offset_and_terminal_state(self):
        registry = TaskRegistry()
        task = registry.create("preflight", ["python", "preflight_douyin.py"], [])
        registry.append_log(task.id, "line one\n")
        registry.append_log(task.id, "line two\n")
        chunk = registry.log_after(task.id, offset=len("line one\n"))
        self.assertEqual(chunk["text"], "line two\n")
        registry.finish(task.id, 0)
        self.assertEqual(registry.get(task.id).status, "succeeded")


class FakeProcess:
    def __init__(self, output="checked Python\n", exit_code=0):
        self.stdout = io.StringIO(output)
        self._exit_code = exit_code

    def wait(self):
        return self._exit_code

    def poll(self):
        return None


class ProcessRunnerTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)
        (self.root / ".venv" / "Scripts").mkdir(parents=True)
        (self.root / ".venv" / "Scripts" / "python.exe").write_text("", encoding="utf-8")
        self.paths = ProjectPaths.from_root(self.root)
        self.registry = TaskRegistry()
        self.calls = []

        def popen(*args, **kwargs):
            self.calls.append({"args": args, **kwargs})
            return FakeProcess()

        self.runner = ProcessRunner(self.paths, self.registry, popen_factory=popen)

    def tearDown(self):
        self.tempdir.cleanup()

    def test_process_runner_records_streamed_output_exit_code_and_safe_cwd(self):
        task = self.runner.start(ActionSpec("preflight", ["python", "preflight_douyin.py"], None, []), {})
        self.runner.join(task.id, timeout=1)
        finished = self.registry.get(task.id)
        self.assertEqual(finished.status, "succeeded")
        self.assertEqual(finished.exit_code, 0)
        self.assertIn("checked Python", finished.log)
        self.assertEqual(self.calls[0]["cwd"], str(self.paths.root))
        self.assertFalse(self.calls[0]["shell"])

    def test_health_masks_feishu_config_and_reports_tool_state(self):
        (self.root / "feishu-base-config.json").write_text('{"app_secret":"not-for-output"}', encoding="utf-8")

        def command_runner(command, **kwargs):
            return type("Result", (), {"returncode": 0, "stdout": "version 1\n", "stderr": ""})()

        state = HealthInspector(self.paths, command_runner=command_runner).snapshot()
        self.assertEqual(state["feishu_config"], "configured")
        self.assertNotIn("app_secret", json.dumps(state))
        self.assertEqual(state["python"]["status"], "ok")
        self.assertIn("hint", state["checks"]["node"])

    def test_health_uses_project_runtime_path_for_tool_checks(self):
        runtime_bin = self.root / "home" / ".cache" / "codex-runtimes" / "codex-primary-runtime" / "dependencies" / "node" / "bin"
        runtime_bin.mkdir(parents=True)
        (runtime_bin / "node.exe").write_text("", encoding="utf-8")
        calls = []

        def command_runner(command, **kwargs):
            calls.append((command, kwargs["env"]["PATH"], kwargs["encoding"], kwargs["errors"]))
            return type("Result", (), {"returncode": 0, "stdout": "ok\n", "stderr": ""})()

        with patch("workbench_core.Path.home", return_value=self.root / "home"):
            HealthInspector(self.paths, command_runner=command_runner).snapshot()
        self.assertTrue(any(str(runtime_bin) in path for _, path, _, _ in calls))
        self.assertTrue(all(encoding == "utf-8" and errors == "replace" for _, _, encoding, errors in calls))
        node_command = next(command for command, _, _, _ in calls if command[0].lower().endswith("node.exe"))
        self.assertEqual(Path(node_command[0]), runtime_bin / "node.exe")

    def test_browser_status_reports_only_project_ports(self):
        lifecycle = BrowserLifecycle(self.paths, popen_factory=lambda *args, **kwargs: FakeProcess())
        state = lifecycle.status()
        self.assertEqual(state["cdp_port"], 9333)
        self.assertEqual(state["bridge_port"], 3457)
        self.assertFalse(state["chrome"]["running"])
        self.assertFalse(state["bridge"]["running"])

    def test_browser_finds_per_user_chrome_installation(self):
        local_app_data = self.root / "AppData" / "Local"
        chrome = local_app_data / "Google" / "Chrome" / "Application" / "chrome.exe"
        chrome.parent.mkdir(parents=True)
        chrome.write_text("", encoding="utf-8")
        lifecycle = BrowserLifecycle(self.paths, popen_factory=lambda *args, **kwargs: FakeProcess())

        with patch.dict("workbench_core.os.environ", {"LOCALAPPDATA": str(local_app_data)}, clear=True):
            self.assertEqual(lifecycle._chrome_executable(), chrome)

    def test_bridge_receives_project_chrome_cdp_settings(self):
        bridge = self.root / ".agents" / "skills" / "douyin-comments" / "scripts" / "douyin_cdp_bridge.mjs"
        bridge.parent.mkdir(parents=True)
        bridge.write_text("", encoding="utf-8")
        calls = []

        def popen(*args, **kwargs):
            calls.append({"args": args, **kwargs})
            return FakeProcess()

        lifecycle = BrowserLifecycle(self.paths, popen_factory=popen)
        with patch("workbench_core.shutil.which", return_value="node.exe"):
            lifecycle.start_bridge()

        self.assertEqual(calls[0]["env"]["DOUYIN_CDP_PORT"], "9333")
        self.assertEqual(calls[0]["env"]["DOUYIN_CHROME_USER_DATA_DIR"], str(self.root / "runtime" / "chrome-profile"))

    def test_browser_start_does_not_deadlock_while_reporting_status(self):
        lifecycle = BrowserLifecycle(self.paths, popen_factory=lambda *args, **kwargs: FakeProcess())
        lifecycle._chrome_executable = lambda: self.root / "chrome.exe"
        lifecycle.start_chrome()
        state = lifecycle.start_chrome()
        self.assertTrue(state["chrome"]["running"])


class ArtifactIndexerTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)
        (self.root / ".venv" / "Scripts").mkdir(parents=True)
        (self.root / "downloads" / "manifests").mkdir(parents=True)
        (self.root / "outputs").mkdir()
        self.paths = ProjectPaths.from_root(self.root)

    def tearDown(self):
        self.tempdir.cleanup()

    def test_artifact_indexer_returns_project_relative_latest_manifest_and_files_only(self):
        (self.paths.manifests_root / "douyin-latest-download-20260716.json").write_text("{}", encoding="utf-8")
        (self.root / "outputs" / "video [123].mp4").write_bytes(b"x")
        payload = ArtifactIndexer(self.paths).latest()
        self.assertEqual(payload["latest_manifests"][0], "downloads/manifests/douyin-latest-download-20260716.json")
        self.assertIn("outputs/video [123].mp4", payload["recent_files"])
        self.assertTrue(all(not Path(item).is_absolute() for item in payload["recent_files"]))


if __name__ == "__main__":
    unittest.main()
