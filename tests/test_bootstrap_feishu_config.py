import unittest

from bootstrap_feishu_config import build_config, wiki_node_argument


class BuildConfigTests(unittest.TestCase):
    def test_extracts_wiki_token_before_passing_url_to_windows_cmd(self):
        url = "https://my.feishu.cn/wiki/HifXwc4uDiaeD7kCvqocRxHCnlc?table=tbl&view=vew"

        self.assertEqual(wiki_node_argument(url), "HifXwc4uDiaeD7kCvqocRxHCnlc")

    def test_maps_required_tables_and_keeps_target_video_table(self):
        tables = [
            {"name": "博主表", "table_id": "tblCreators"},
            {"name": "视频表", "table_id": "tblakZnkghpokyGT"},
            {"name": "视频指标快照", "table_id": "tblMetrics"},
            {"name": "爬取任务日志", "table_id": "tblLogs"},
            {"name": "视频评论", "table_id": "tblComments"},
        ]

        config = build_config("secret-token", tables, profile="safe-profile")

        self.assertEqual(config["base_token"], "secret-token")
        self.assertEqual(config["profile"], "safe-profile")
        self.assertEqual(config["tables"]["videos"]["table_id"], "tblakZnkghpokyGT")
        self.assertEqual(config["tables"]["creators"]["table_id"], "tblCreators")

    def test_refuses_a_different_video_table_id(self):
        tables = [
            {"name": "博主表", "table_id": "tblCreators"},
            {"name": "视频表", "table_id": "tblWrong"},
            {"name": "视频指标快照", "table_id": "tblMetrics"},
            {"name": "爬取任务日志", "table_id": "tblLogs"},
            {"name": "视频评论", "table_id": "tblComments"},
        ]

        with self.assertRaisesRegex(RuntimeError, "target video table"):
            build_config("secret-token", tables, profile="safe-profile")


if __name__ == "__main__":
    unittest.main()
