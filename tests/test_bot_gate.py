import unittest
from bot import can_use_bot, DAN_LANG_ROLE


class _Perms:
    def __init__(self, administrator): self.administrator = administrator


class _Role:
    def __init__(self, name): self.name = name


class _User:
    def __init__(self, administrator=False, roles=()):
        self.guild_permissions = _Perms(administrator)
        self.roles = list(roles)


class BotGateTest(unittest.TestCase):
    def test_admin_allowed_without_role(self):
        self.assertTrue(can_use_bot(_User(administrator=True)))

    def test_role_allowed_without_admin(self):
        self.assertTrue(can_use_bot(_User(roles=[_Role(DAN_LANG_ROLE)])))

    def test_neither_denied(self):
        self.assertFalse(can_use_bot(_User(roles=[_Role("Thành viên")])))

    def test_dm_user_without_guild_perms_denied(self):
        class _Bare:  # giống discord.User trong DM: khong co guild_permissions/roles
            pass
        self.assertFalse(can_use_bot(_Bare()))


if __name__ == "__main__":
    unittest.main()
