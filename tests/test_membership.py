# -*- coding: utf-8 -*-
import os
import unittest
from datetime import datetime, timezone, timedelta

os.environ.setdefault("GROQ_API_KEYS", "x")

from cogs.membership import compute_new_expiry, is_expired, kick_due, Membership


NOW = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)


class ExpiryMathTest(unittest.TestCase):
    def test_new_customer_expiry_from_now(self):
        self.assertEqual(compute_new_expiry(NOW, None, 30), NOW + timedelta(days=30))

    def test_still_valid_extends_cumulatively(self):
        current = NOW + timedelta(days=5)  # còn hạn
        self.assertEqual(compute_new_expiry(NOW, current, 30), current + timedelta(days=30))

    def test_already_expired_extends_from_now(self):
        current = NOW - timedelta(days=2)  # đã hết
        self.assertEqual(compute_new_expiry(NOW, current, 30), NOW + timedelta(days=30))

    def test_is_expired(self):
        self.assertTrue(is_expired(NOW - timedelta(seconds=1), NOW))
        self.assertFalse(is_expired(NOW + timedelta(seconds=1), NOW))
        self.assertFalse(is_expired(None, NOW))

    def test_kick_due_only_after_grace(self):
        exp = NOW - timedelta(days=1)  # hết hạn 1 ngày trước
        self.assertFalse(kick_due(exp, NOW, 3))                    # còn trong ân hạn 3 ngày
        self.assertTrue(kick_due(NOW - timedelta(days=4), NOW, 3))  # quá ân hạn
        self.assertFalse(kick_due(None, NOW, 3))


class FakeDB:
    def __init__(self):
        self.rows = []
        self._id = 0

    async def fetchrow(self, sql, *args):
        if "FROM hvhn_members WHERE discord_id=" in sql:
            did = args[0]
            cand = [r for r in self.rows if r["discord_id"] == did and r["status"] in ("active", "expired")]
            cand.sort(key=lambda r: r["id"], reverse=True)
            return cand[0] if cand else None
        return None

    async def fetchval(self, sql, *args):
        if sql.strip().upper().startswith("INSERT INTO HVHN_MEMBERS"):
            self._id += 1
            self.rows.append({
                "id": self._id, "discord_id": args[0], "name": args[1], "email": args[2],
                "duration_days": args[3], "granted_at": args[4], "expires_at": args[5],
                "status": "active", "notified_expiry": False, "created_by": args[6],
            })
            return self._id
        return None

    async def execute(self, sql, *args):
        if "UPDATE hvhn_members SET name=COALESCE" in sql:
            rid = args[0]
            for r in self.rows:
                if r["id"] == rid:
                    if args[1] is not None:
                        r["name"] = args[1]
                    if args[2] is not None:
                        r["email"] = args[2]
                    r["duration_days"] = args[3]
                    if r.get("granted_at") is None:
                        r["granted_at"] = args[4]
                    r["expires_at"] = args[5]
                    r["status"] = "active"
                    r["notified_expiry"] = False


class FakeBot:
    def __init__(self, db):
        self.db = db


class RegisterTest(unittest.IsolatedAsyncioTestCase):
    def _cog(self):
        m = Membership.__new__(Membership)  # tránh __init__ (khỏi start loop)
        m.bot = FakeBot(FakeDB())
        return m

    async def test_register_new_customer(self):
        m = self._cog()
        rid, expires = await m._register(111, "An", "an@x.com", 15, 999)
        self.assertEqual(len(m.bot.db.rows), 1)
        row = m.bot.db.rows[0]
        self.assertEqual(row["discord_id"], 111)
        self.assertEqual(row["status"], "active")
        self.assertAlmostEqual((expires - row["granted_at"]).days, 15)

    async def test_reregister_extends_cumulatively(self):
        m = self._cog()
        _, exp1 = await m._register(111, "An", "an@x.com", 10, 999)
        _, exp2 = await m._register(111, None, None, 5, 999)
        self.assertEqual(len(m.bot.db.rows), 1)             # cùng khách, không tạo dòng mới
        self.assertEqual(exp2, exp1 + timedelta(days=5))     # cộng dồn
        self.assertEqual(m.bot.db.rows[0]["email"], "an@x.com")  # giữ email cũ khi truyền None

    async def test_tick_no_guild_is_safe(self):
        m = Membership.__new__(Membership)
        m.bot = FakeBot(FakeDB())
        # không có guild -> trả (0,0), không lỗi
        self.assertEqual(await m._run_expiry_tick(), (0, 0))


if __name__ == "__main__":
    unittest.main()
