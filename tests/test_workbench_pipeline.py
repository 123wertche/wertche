import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from workbench_core import ProjectPaths, WorkbenchError
from workbench_pipeline import PipelineManager, PipelineRecord, build_pipeline_steps


class PipelinePlanTests(unittest.TestCase):
    def test_two_platforms_default_to_two_and_auto_device(self):
        creators = [
            {"platform": "抖音", "homepage_url": "https://www.douyin.com/user/a", "platform_id": "a", "local_id": "da"},
            {"platform": "B站", "homepage_url": "https://space.bilibili.com/12", "platform_id": "12", "local_id": "bb"},
        ]
        dry, real = build_pipeline_steps(creators, {})
        self.assertEqual(dry[1][1]["videos_per_creator"], 2)
        self.assertEqual(dry[-1][1]["videos_per_creator"], 2)
        self.assertEqual(real[0][1]["device"], "auto")
        self.assertTrue(any(action == "bili_comments_sync" and not params.get("dry_run", False) for action, params in real))

    def test_rejects_second_pipeline_while_one_is_active(self):
        with tempfile.TemporaryDirectory() as directory:
            paths = ProjectPaths.from_root(Path(directory))
            creator = {"platform": "鎶栭煶", "homepage_url": "https://www.douyin.com/user/a", "platform_id": "a", "local_id": "da"}
            manager = PipelineManager(paths, lambda _ids: [creator], lifecycle=object())
            manager.records["active"] = PipelineRecord("active", ["da"], {}, status="running")

            with patch("workbench_pipeline.threading.Thread"):
                with self.assertRaisesRegex(WorkbenchError, "already running"):
                    manager.start(["da"], {})

    def test_real_pipeline_recovers_only_failed_douyin_creator_and_scopes_followup_steps(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "downloads" / "manifests").mkdir(parents=True)
            paths = ProjectPaths.from_root(root)
            creator_one = {"key": "one", "url": "https://www.douyin.com/user/one"}
            creator_two = {"key": "two", "url": "https://www.douyin.com/user/two"}
            manager = PipelineManager(paths, lambda _ids: [], lifecycle=object())
            record = PipelineRecord("pipeline", ["one", "two"], {}, status="execution_queued")
            calls = []

            def write(name, payload):
                (paths.manifests_root / name).write_text(json.dumps(payload), encoding="utf-8")

            def fake_step(_record, action, params):
                calls.append((action, dict(params)))
                if action == "douyin_download" and len([item for item in calls if item[0] == action]) == 1:
                    write("01-douyin-latest-download.json", {
                        "platform": "douyin", "creators": [creator_one, creator_two],
                        "successes": [{"ok": True, "aweme_id": "111", "creator": creator_one}],
                        "parsed": [], "failures": [{"creator": creator_two, "error": "empty page"}],
                    })
                    raise RuntimeError("douyin_download failed with exit code 1")
                if action == "douyin_download":
                    self.assertEqual(params["creator_urls"], [creator_two["url"]])
                    write("02-douyin-latest-download.json", {
                        "platform": "douyin", "creators": [{"key": "one", "url": creator_two["url"]}],
                        "successes": [{"ok": True, "aweme_id": "222", "creator": {"key": "one", "url": creator_two["url"]}}],
                        "parsed": [], "failures": [],
                    })

            manager._run_step = fake_step
            real = [
                ("douyin_download", {"creator_urls": [creator_one["url"], creator_two["url"]], "max_creators": 2, "videos_per_creator": 2}),
                ("douyin_sync", {"dry_run": True}),
                ("douyin_enrich", {"dry_run": True}),
                ("douyin_publish_docs", {"dry_run": True, "max_records": 4}),
            ]
            with patch("workbench_pipeline.build_pipeline_steps", return_value=([], real)), patch("workbench_pipeline.time.sleep"):
                manager._run_real(record, [])

            self.assertEqual(record.status, "succeeded")
            scoped = [params for action, params in calls if action != "douyin_download"]
            self.assertTrue(all(str(params.get("manifest", "")).endswith("-merged-douyin-latest-download.json") for params in scoped))

    def test_dry_pipeline_retries_only_failed_creator_and_reaches_confirmation(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "downloads" / "manifests").mkdir(parents=True)
            paths = ProjectPaths.from_root(root)
            creator_one = {"key": "one", "url": "https://www.douyin.com/user/one"}
            creator_two = {"key": "two", "url": "https://www.douyin.com/user/two"}

            class Lifecycle:
                def start_chrome(self):
                    return None

                def start_bridge(self):
                    return None

            manager = PipelineManager(paths, lambda _ids: [], lifecycle=Lifecycle())
            record = PipelineRecord("pipeline", ["one", "two"], {})
            calls = []

            def write(name, payload):
                (paths.manifests_root / name).write_text(json.dumps(payload), encoding="utf-8")

            def fake_step(_record, action, params):
                calls.append((action, dict(params)))
                if len(calls) == 1:
                    write("01-douyin-latest-download.json", {
                        "platform": "douyin", "dry_run": True,
                        "creators": [creator_one, creator_two], "successes": [],
                        "would_download": [{"aweme_id": "111", "creator": creator_one}],
                        "skipped_existing": [], "parsed": [],
                        "failures": [{"creator": creator_two, "error": "empty page"}],
                    })
                    raise RuntimeError("douyin_download failed with exit code 1")
                self.assertEqual(params["creator_urls"], [creator_two["url"]])
                write("02-douyin-latest-download.json", {
                    "platform": "douyin", "dry_run": True,
                    "creators": [creator_two], "successes": [],
                    "would_download": [{"aweme_id": "222", "creator": creator_two}],
                    "skipped_existing": [], "parsed": [], "failures": [],
                })

            manager._run_step = fake_step
            dry = [("douyin_download", {
                "creator_urls": [creator_one["url"], creator_two["url"]],
                "max_creators": 2, "videos_per_creator": 2, "dry_run": True,
            })]
            with patch("workbench_pipeline.build_pipeline_steps", return_value=(dry, [])), patch("workbench_pipeline.time.sleep"):
                manager._run_dry(record, [])

            self.assertEqual(record.status, "awaiting_confirmation")
            self.assertEqual(len(calls), 2)
            merged_path = next(paths.manifests_root.glob("*-merged-douyin-latest-download.json"))
            merged = json.loads(merged_path.read_text(encoding="utf-8"))
            self.assertTrue(merged["dry_run"])
            self.assertEqual([item["aweme_id"] for item in merged["would_download"]], ["111", "222"])
            self.assertEqual(merged["failures"], [])

    def test_douyin_sync_has_two_bounded_idempotent_retries(self):
        with tempfile.TemporaryDirectory() as directory:
            paths = ProjectPaths.from_root(Path(directory))
            manager = PipelineManager(paths, lambda _ids: [], lifecycle=object())
            record = PipelineRecord("pipeline", [], {})
            attempts = []

            def flaky(_record, action, _params):
                attempts.append(action)
                if len(attempts) < 3:
                    raise RuntimeError("douyin_sync failed with exit code 1")

            manager._run_step = flaky
            with patch("workbench_pipeline.time.sleep"):
                manager._run_resilient_step(record, "douyin_sync", {})

            self.assertEqual(attempts, ["douyin_sync", "douyin_sync", "douyin_sync"])


if __name__ == "__main__":
    unittest.main()
