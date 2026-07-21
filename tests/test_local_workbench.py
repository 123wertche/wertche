import http.client
import json
import re
import tempfile
import threading
import unittest
from pathlib import Path

from local_workbench import create_server


class FakeProcess:
    def __init__(self):
        self.stdout = iter(["preflight complete\n"])

    def wait(self):
        return 0


class LocalWorkbenchHttpTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)
        (self.root / ".venv" / "Scripts").mkdir(parents=True)
        (self.root / ".venv" / "Scripts" / "python.exe").write_text("", encoding="utf-8")
        (self.root / "downloads" / "manifests").mkdir(parents=True)
        self.server = create_server(self.root, port=0, popen_factory=lambda *args, **kwargs: FakeProcess())
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=1)
        self.tempdir.cleanup()

    def request(self, method, path, payload=None):
        connection = http.client.HTTPConnection("127.0.0.1", self.server.server_port, timeout=2)
        body = json.dumps(payload).encode("utf-8") if payload is not None else None
        headers = {"Content-Type": "application/json"} if body else {}
        connection.request(method, path, body=body, headers=headers)
        response = connection.getresponse()
        raw = response.read()
        connection.close()
        return response.status, json.loads(raw.decode("utf-8")) if "application/json" in response.getheader("Content-Type", "") else raw

    def request_project_asset(self, path):
        project_root = Path(__file__).resolve().parents[1]
        server = create_server(project_root, port=0, popen_factory=lambda *args, **kwargs: FakeProcess())
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            connection = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=2)
            connection.request("GET", path)
            response = connection.getresponse()
            return response.status, response.read()
        finally:
            connection.close()
            server.shutdown()
            server.server_close()
            thread.join(timeout=1)

    def test_health_creators_and_unknown_action_api_contract(self):
        status, health = self.request("GET", "/api/health")
        self.assertEqual(status, 200)
        self.assertEqual(health["listen_host"], "127.0.0.1")
        status, creators = self.request("GET", "/api/creators")
        self.assertEqual(status, 200)
        self.assertIn("urls", creators)
        status, rejected = self.request("POST", "/api/tasks", {"action": "cmd", "params": {}})
        self.assertEqual(status, 404)
        self.assertEqual(rejected["error"], "unsupported action")

    def test_task_api_returns_id_and_incremental_logs(self):
        status, response = self.request("POST", "/api/tasks", {"action": "preflight", "params": {}})
        self.assertEqual(status, 202)
        task_id = response["task"]["id"]
        status, log = self.request("GET", f"/api/tasks/{task_id}/log?offset=0")
        self.assertEqual(status, 200)
        self.assertIn("next_offset", log)

    def test_unified_creator_api_previews_saves_and_filters_both_platforms(self):
        urls = [
            "https://www.douyin.com/user/MS4wLjABAAAAabc",
            "https://space.bilibili.com/12345",
        ]
        status, preview = self.request("POST", "/api/creators/preview", {"urls": urls})
        self.assertEqual(status, 200)
        self.assertEqual({item["platform"] for item in preview["creators"]}, {"抖音", "B站"})
        status, saved = self.request("PUT", "/api/creators", {"creators": preview["creators"]})
        self.assertEqual(status, 200)
        self.assertEqual(saved["count"], 2)
        status, bili = self.request("GET", "/api/creators?platform=B%E7%AB%99")
        self.assertEqual(status, 200)
        self.assertEqual([item["platform"] for item in bili["creators"]], ["B站"])

    def test_bili_real_download_without_dry_run_phrase_is_rejected(self):
        status, response = self.request("POST", "/api/tasks", {"action": "bili_download", "params": {"videos_per_creator": 1}})
        self.assertEqual(status, 202)
        self.assertEqual(response["task"]["status"], "rejected")

    def test_matching_bili_dry_run_phrase_allows_the_same_real_parameters(self):
        params = {"videos_per_creator": 1, "comment_limit": 50}
        status, dry = self.request("POST", "/api/tasks", {"action": "bili_download", "params": {**params, "dry_run": True}})
        self.assertEqual(status, 202)
        self.server.app.runner.join(dry["task"]["id"], timeout=1)
        log = self.server.app.tasks.log_after(dry["task"]["id"], 0)["text"]
        phrase = re.search(r"phrase: (\S+)", log).group(1)
        status, real = self.request("POST", "/api/tasks", {"action": "bili_download", "params": params, "confirmation_phrase": phrase})
        self.assertEqual(status, 202)
        self.assertNotEqual(real["task"]["status"], "rejected")

    def test_server_refuses_non_loopback_bind(self):
        with self.assertRaisesRegex(ValueError, "127.0.0.1"):
            create_server(self.root, host="0.0.0.0", port=0)

    def test_root_serves_workbench_and_no_xiaohongshu_markup(self):
        project_root = Path(__file__).resolve().parents[1]
        server = create_server(project_root, port=0, popen_factory=lambda *args, **kwargs: FakeProcess())
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            connection = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=2)
            connection.request("GET", "/")
            response = connection.getresponse()
            body = response.read()
            connection.close()
            self.assertEqual(response.status, 200)
            self.assertIn(b"Douyin", body)
            self.assertIn(b"Bilibili", body)
            self.assertNotIn(b"xiaohongshu", body.lower())
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=1)

    def test_root_uses_compact_two_column_workbench_structure(self):
        status, body = self.request_project_asset("/")
        html = body.decode("utf-8")
        self.assertEqual(status, 200)
        for marker in ('class="workspace-grid"', 'class="workspace-primary"', 'class="workspace-rail"', 'class="status-strip"'):
            self.assertIn(marker, html)
        for element_id in ("creator-list", "video-count", "device", "run-pipeline", "pipeline-log"):
            self.assertIn(f'id="{element_id}"', html)

    def test_compact_assets_include_responsive_and_accessibility_contracts(self):
        css_status, css_body = self.request_project_asset("/style.css")
        js_status, js_body = self.request_project_asset("/app.js")
        css = css_body.decode("utf-8")
        javascript = js_body.decode("utf-8")
        compact_css = css.replace(" ", "")
        self.assertEqual((css_status, js_status), (200, 200))
        self.assertIn("grid-template-columns:minmax(0,58fr)minmax(340px,42fr)", compact_css)
        self.assertIn("@media(max-width:880px)", compact_css)
        self.assertIn("prefers-reduced-motion", css)
        self.assertIn("aria-checked", javascript)

    def test_second_tab_attaches_to_the_running_pipeline(self):
        status, body = self.request_project_asset("/app.js")
        javascript = body.decode("utf-8")
        self.assertEqual(status, 200)
        self.assertIn('error.message.startsWith("pipeline already running: ")', javascript)
        self.assertIn('pipelineId = error.message.split(": ", 2)[1]', javascript)
        self.assertIn("await pollPipeline()", javascript)

    def test_stale_pipeline_id_recovers_instead_of_showing_not_found(self):
        status, body = self.request_project_asset("/app.js")
        javascript = body.decode("utf-8")
        self.assertEqual(status, 200)
        self.assertIn('error.message === "pipeline not found"', javascript)
        self.assertIn('await api("/api/pipelines")', javascript)
        self.assertIn("await attachActivePipeline()", javascript)

    def test_direct_file_open_redirects_to_local_workbench_service(self):
        project_root = Path(__file__).resolve().parents[1]
        html = (project_root / "workbench" / "index.html").read_text(encoding="utf-8")
        self.assertIn('window.location.protocol === "file:"', html)
        self.assertIn('window.location.replace("http://127.0.0.1:8765/")', html)


if __name__ == "__main__":
    unittest.main()
