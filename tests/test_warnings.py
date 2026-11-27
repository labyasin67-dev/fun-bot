import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from database import Database
from dashboard.routes import _fmt_ts_melbourne


class WarningTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Database(str(Path(self.tmp.name) / "t.db"))
        await self.db.setup()

    async def asyncTearDown(self):
        await self.db.close()
        self.tmp.cleanup()

    async def test_add_list_and_remove_by_id_or_latest(self):
        first = await self.db.add_warning(1, 11, 99, "first")
        second = await self.db.add_warning(1, 11, 99, "second")
        other = await self.db.add_warning(1, 22, 99, "other user")
        rows = await self.db.get_warnings(1, 11)
        self.assertEqual([int(r["id"]) for r in rows], [first, second])
        self.assertTrue(await self.db.delete_warning(
            1, 11, first, removed_by=77, removed_by_name="mod", user_name="alice", removal_reason="mistake",
        ))
        self.assertFalse(await self.db.delete_warning(
            1, 11, first, removed_by=77, removed_by_name="mod", user_name="alice",
        ))
        self.assertFalse(await self.db.delete_warning(
            1, 11, other, removed_by=77,  # different user
        ))
        latest = await self.db.delete_latest_warning(
            1, 11, removed_by=77, removed_by_name="mod", user_name="alice", removal_reason="latest gone",
        )
        self.assertEqual(int(latest["id"]), second)
        self.assertEqual(await self.db.get_warnings(1, 11), [])
        self.assertIsNone(await self.db.delete_latest_warning(1, 11, removed_by=77))
        leftover = await self.db.get_warnings(1, 22)
        self.assertEqual(len(leftover), 1)
        self.assertEqual(int(leftover[0]["id"]), other)

        removals = await self.db.list_warning_removals(1)
        self.assertEqual([int(r["warning_id"]) for r in removals], [second, first])
        first_row = next(r for r in removals if int(r["warning_id"]) == first)
        self.assertEqual(int(first_row["user_id"]), 11)
        self.assertEqual(first_row["user_name"], "alice")
        self.assertEqual(first_row["original_reason"], "first")
        self.assertEqual(int(first_row["removed_by"]), 77)
        self.assertEqual(first_row["removed_by_name"], "mod")
        self.assertEqual(first_row["removal_reason"], "mistake")
        self.assertTrue(first_row["removed_at"])
        self.assertEqual(await self.db.list_warning_removals(2), [])

    async def test_clear_warnings_records_each_removal(self):
        a = await self.db.add_warning(5, 11, 99, "one")
        b = await self.db.add_warning(5, 11, 99, "two")
        await self.db.add_warning(5, 22, 99, "other")
        removed = await self.db.clear_warnings(
            5, 11, removed_by=5, removed_by_name="admin", user_name="bob", removal_reason="wiped",
        )
        self.assertEqual(removed, 2)
        self.assertEqual(await self.db.get_warnings(5, 11), [])
        self.assertEqual(len(await self.db.get_warnings(5, 22)), 1)
        removals = await self.db.list_warning_removals(5)
        ids = {int(r["warning_id"]) for r in removals}
        self.assertEqual(ids, {a, b})
        self.assertTrue(all(r["removal_reason"] == "wiped" for r in removals))
        self.assertTrue(all(int(r["removed_by"]) == 5 for r in removals))

    async def test_melbourne_timestamp_format(self):
        # 2026-11-26 20:15:00 UTC == 2026-11-27 07:15 AEDT
        ts = datetime(2026, 11, 27, 7, 15, tzinfo=ZoneInfo("Australia/Melbourne")).timestamp()
        label = _fmt_ts_melbourne(ts)
        self.assertEqual(label, "2026-11-27 07:15 AEDT")


if __name__ == "__main__":
    unittest.main()
