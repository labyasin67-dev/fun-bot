import tempfile
import unittest
from pathlib import Path

from database import Database


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
        self.assertTrue(await self.db.delete_warning(1, 11, first))
        self.assertFalse(await self.db.delete_warning(1, 11, first))
        self.assertFalse(await self.db.delete_warning(1, 11, other))  # different user
        latest = await self.db.delete_latest_warning(1, 11)
        self.assertEqual(int(latest["id"]), second)
        self.assertEqual(await self.db.get_warnings(1, 11), [])
        self.assertIsNone(await self.db.delete_latest_warning(1, 11))
        # other user's warning is untouched
        leftover = await self.db.get_warnings(1, 22)
        self.assertEqual(len(leftover), 1)
        self.assertEqual(int(leftover[0]["id"]), other)


if __name__ == "__main__":
    unittest.main()
