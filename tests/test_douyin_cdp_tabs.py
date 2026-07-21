import unittest
from unittest.mock import patch

import download_douyin_latest as douyin


class DouyinCdpTabTests(unittest.TestCase):
    def test_reused_creator_tab_is_not_reloaded_before_reading_visible_cards(self):
        navigation_steps = getattr(douyin, "creator_navigation_steps", None)
        self.assertIsNotNone(navigation_steps)
        steps = navigation_steps("https://www.douyin.com/user/creator-id", reused=True)

        self.assertFalse(any("goto" in step for step in steps))

    def test_creator_scroll_tolerates_a_body_that_is_still_loading(self):
        expression = getattr(douyin, "creator_scroll_expression", None)
        self.assertIsNotNone(expression)
        self.assertIn("document.body?.scrollHeight", expression())

    def test_creator_capture_prefers_an_existing_matching_tab(self):
        creator_tab_step = getattr(douyin, "creator_tab_step", None)
        self.assertIsNotNone(creator_tab_step)
        url = "https://www.douyin.com/user/creator-id"
        self.assertEqual(creator_tab_step(url), {"attachTab": {"url": url}})

    def test_attach_tab_step_reuses_an_existing_creator_tab(self):
        response = {"targetId": "creator", "sessionId": "session", "reused": True}
        with patch.object(douyin, "ensure_cdp_bridge"), patch.object(
            douyin, "http_json", return_value=response
        ) as request:
            try:
                result = douyin.cdp_run(
                    [{"attachTab": {"url": "https://www.douyin.com/user/creator-id"}}],
                    timeout=30,
                )
            except Exception as exc:
                self.fail(f"attachTab should be supported: {exc}")

        request.assert_called_once_with(
            f"{douyin.CDP_BRIDGE_URL}/attach",
            {"url": "https://www.douyin.com/user/creator-id"},
            timeout=30,
        )
        self.assertEqual(result["steps"][0]["action"], "attachTab")
        self.assertEqual(result["steps"][0]["output"], response)

    def test_reused_creator_tab_is_detached_without_closing_the_users_tab(self):
        douyin.BRIDGE_TABS["reused"] = {
            "targetId": "creator",
            "sessionId": "session",
            "owned": False,
        }
        with patch.object(douyin, "ensure_cdp_bridge"), patch.object(
            douyin, "http_json", return_value={"ok": True}
        ) as request:
            douyin.close_cdp_tab("reused")

        request.assert_called_once_with(
            f"{douyin.CDP_BRIDGE_URL}/detach",
            {"targetId": "creator", "sessionId": "session"},
            timeout=15,
        )


if __name__ == "__main__":
    unittest.main()
