import types
import unittest

from dashboard import ADMINISTRATOR, MANAGE_GUILD
from dashboard.auth import can_manage_guild, has_manage_permission, managed_guilds


def request(guilds, user=None, bot=None):
    req = types.SimpleNamespace()
    req.session = {"guilds": guilds, "user": user}
    req.app = types.SimpleNamespace(state=types.SimpleNamespace(bot=bot))
    return req


class DashboardAccessTests(unittest.IsolatedAsyncioTestCase):
    def test_permission_is_administrator_or_owner_only(self):
        self.assertTrue(has_manage_permission(ADMINISTRATOR))
        self.assertTrue(has_manage_permission(ADMINISTRATOR | MANAGE_GUILD))
        self.assertTrue(has_manage_permission(0, owner=True))
        self.assertTrue(has_manage_permission(MANAGE_GUILD, owner=True))
        self.assertFalse(has_manage_permission(MANAGE_GUILD))
        self.assertFalse(has_manage_permission(0))
        self.assertFalse(has_manage_permission(1 << 13))  # Manage Messages
        self.assertFalse(has_manage_permission("not-a-number"))

    def test_managed_guilds_filters_to_admin_or_owner(self):
        guilds = [
            {"id": "1", "name": "Admin", "permissions": ADMINISTRATOR, "owner": False},
            {"id": "2", "name": "Manage only", "permissions": MANAGE_GUILD, "owner": False},
            {"id": "3", "name": "Owner no bits", "permissions": 0, "owner": True},
            {"id": "4", "name": "Mod", "permissions": 1 << 13, "owner": False},
        ]
        req = request(guilds, user={"id": "99"})
        seen = {g["id"] for g in managed_guilds(req)}
        self.assertEqual(seen, {"1", "3"})
        self.assertTrue(can_manage_guild(req, 1))
        self.assertFalse(can_manage_guild(req, 2))
        self.assertTrue(can_manage_guild(req, 3))
        self.assertFalse(can_manage_guild(req, 4))

    def test_live_member_overrides_stale_session(self):
        guilds = [{"id": "1", "name": "Stale", "permissions": ADMINISTRATOR, "owner": False}]
        user = {"id": "99"}
        member = types.SimpleNamespace(guild_permissions=types.SimpleNamespace(administrator=False))
        guild = types.SimpleNamespace(owner_id=1, get_member=lambda i: member if int(i) == 99 else None)
        bot = types.SimpleNamespace(get_guild=lambda i: guild if int(i) == 1 else None)
        req = request(guilds, user=user, bot=bot)
        self.assertEqual(managed_guilds(req), [])
        self.assertFalse(can_manage_guild(req, 1))

        member.guild_permissions.administrator = True
        self.assertEqual(len(managed_guilds(req)), 1)
        self.assertTrue(can_manage_guild(req, 1))

    def test_live_owner_is_allowed_without_admin_bit(self):
        guilds = [{"id": "1", "name": "Owned"}]  # legacy session, no stored flags
        user = {"id": "77"}
        guild = types.SimpleNamespace(owner_id=77, get_member=lambda i: None)
        bot = types.SimpleNamespace(get_guild=lambda i: guild if int(i) == 1 else None)
        req = request(guilds, user=user, bot=bot)
        self.assertTrue(can_manage_guild(req, 1))

    def test_legacy_session_without_flags_is_denied_unless_live_admin(self):
        guilds = [{"id": "1", "name": "Old manage-server session"}]
        req = request(guilds, user={"id": "99"})
        self.assertFalse(can_manage_guild(req, 1))

        member = types.SimpleNamespace(guild_permissions=types.SimpleNamespace(administrator=True))
        guild = types.SimpleNamespace(owner_id=1, get_member=lambda i: member)
        bot = types.SimpleNamespace(get_guild=lambda i: guild)
        req = request(guilds, user={"id": "99"}, bot=bot)
        self.assertTrue(can_manage_guild(req, 1))


if __name__ == "__main__":
    unittest.main()
