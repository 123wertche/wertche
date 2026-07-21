import unittest

from sync_workbench_creators_to_feishu import CreatorSyncError, plan_creator_sync
from workbench_creators import CreatorIdentity


class CreatorSyncTests(unittest.TestCase):
    def setUp(self):
        self.selected = [CreatorIdentity(
            local_id="b1",
            platform="B站",
            platform_id="123",
            homepage_url="https://space.bilibili.com/123",
            display_name="博主",
            enabled=True,
            source="local",
        )]

    def test_plans_missing_mid_and_reuses_existing_record(self):
        missing = plan_creator_sync(self.selected, [])
        self.assertEqual(missing["create"][0]["mid"], "123")
        existing = plan_creator_sync(self.selected, [{"_record_id": "rec1", "B站MID": "123"}])
        self.assertEqual(existing["mapping"], {"b1": "rec1"})
        self.assertEqual(existing["create"], [])

    def test_rejects_ambiguous_duplicate_mid_rows(self):
        with self.assertRaisesRegex(CreatorSyncError, "重复"):
            plan_creator_sync(self.selected, [
                {"_record_id": "rec1", "B站MID": "123"},
                {"_record_id": "rec2", "B站MID": "123"},
            ])


if __name__ == "__main__":
    unittest.main()
