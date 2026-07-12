# -*- coding: utf-8 -*-
import os
import unittest
from datetime import datetime, timezone, timedelta

os.environ.setdefault("GROQ_API_KEYS", "x")

from cogs.membership import (
    compute_new_expiry,
    is_expired,
    kick_due,
    valid_email,
    match_used_invite,
    Membership,
)


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


class InviteMatchTest(unittest.TestCase):
    def test_detects_invite_use_increment(self):
        before = {"abc": 0, "old": 2}
        after = [{"code": "abc", "uses": 1}, {"code": "old", "uses": 2}]
        self.assertEqual(match_used_invite(before, after), "abc")

    def test_detects_single_use_invite_disappearing(self):
        before = {"abc": 0}
        after = []
        self.assertEqual(match_used_invite(before, after), "abc")

    def test_ambiguous_changes_return_none(self):
        before = {"a": 0, "b": 0}
        after = [{"code": "a", "uses": 1}, {"code": "b", "uses": 1}]
        self.assertIsNone(match_used_invite(before, after))

    def test_email_validation(self):
        self.assertTrue(valid_email("A@Example.com"))
        self.assertFalse(valid_email("not-an-email"))


class FakeDB:
    def __init__(self):
        self.rows = []
        self.jobs = []
        self._id = 0
        self._job_id = 0

    async def fetchrow(self, sql, *args):
        if "WHERE discord_id=$1 AND status IN ('joined','active')" in sql:
            did = args[0]
            cand = [r for r in self.rows if r["discord_id"] == did and r["status"] in ("joined", "active")]
            cand.sort(key=lambda r: r["id"], reverse=True)
            return cand[0] if cand else None
        if "FROM hvhn_members WHERE discord_id=" in sql:
            did = args[0]
            cand = [r for r in self.rows if r["discord_id"] == did and r["status"] in ("active", "expired")]
            cand.sort(key=lambda r: r["id"], reverse=True)
            return cand[0] if cand else None
        if "UPDATE hvhn_members SET discord_id=$2, status='joined'" in sql:
            code, did = args
            cand = [r for r in self.rows if r.get("invite_code") == code and r["status"] == "pending"]
            cand.sort(key=lambda r: r["id"], reverse=True)
            if not cand:
                return None
            row = cand[0]
            row["discord_id"] = did
            row["status"] = "joined"
            return {"id": row["id"], "duration_days": row["duration_days"]}
        return None

    async def fetchval(self, sql, *args):
        if sql.strip().upper().startswith("INSERT INTO HVHN_DOC_JOBS"):
            self._job_id += 1
            self.jobs.append({"id": self._job_id, "job_type": args[0], "text_payload": args[1], "requested_by": args[2]})
            return self._job_id
        if "INSERT INTO hvhn_members(invite_code,duration_days,status,created_by)" in sql:
            self._id += 1
            self.rows.append({
                "id": self._id, "discord_id": None, "name": None, "email": None,
                "invite_code": args[0], "duration_days": args[1], "granted_at": None,
                "expires_at": None, "status": "pending", "notified_expiry": False,
                "created_by": args[2], "created_at": datetime.now(timezone.utc),
            })
            return self._id
        if "INSERT INTO hvhn_members(discord_id,name,email,duration_days" in sql:
            self._id += 1
            self.rows.append({
                "id": self._id, "discord_id": args[0], "name": args[1], "email": args[2],
                "invite_code": None, "duration_days": args[3], "granted_at": args[4], "expires_at": args[5],
                "status": "active", "notified_expiry": False, "created_by": args[6],
                "created_at": datetime.now(timezone.utc),
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
        if "UPDATE hvhn_members SET name=$2, email=$3, granted_at=$4, expires_at=$5" in sql:
            rid = args[0]
            for r in self.rows:
                if r["id"] == rid:
                    r["name"] = args[1]
                    r["email"] = args[2]
                    r["granted_at"] = args[3]
                    r["expires_at"] = args[4]
                    r["status"] = "active"
                    r["notified_expiry"] = False
        if "UPDATE hvhn_members SET name=$2, email=$3, expires_at=$4" in sql:
            rid = args[0]
            for r in self.rows:
                if r["id"] == rid:
                    r["name"] = args[1]
                    r["email"] = args[2]
                    r["expires_at"] = args[3]
                    r["status"] = "active"
                    r["notified_expiry"] = False


class FakeBot:
    def __init__(self, db):
        self.db = db


class FakeMember:
    def __init__(self, did=111):
        self.id = did
        self.roles = []
        self.guild = object()


class RegisterTest(unittest.IsolatedAsyncioTestCase):
    def _cog(self):
        m = Membership.__new__(Membership)  # tránh __init__ (khỏi start loop)
        m.bot = FakeBot(FakeDB())
        async def _noop_grant(member):
            return None
        m._grant_roles = _noop_grant
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

    async def test_pending_joined_activate_enqueues_add_client(self):
        m = self._cog()
        rid = await m._create_pending_invite("abc", 7, 999)
        joined = await m._mark_invite_joined("abc", 111)
        self.assertEqual(joined["id"], rid)
        expires, note, corrected = await m._activate_customer(FakeMember(111), "An", "an@example.com", 111)
        row = m.bot.db.rows[0]
        self.assertFalse(corrected)
        self.assertEqual(row["status"], "active")
        self.assertEqual(row["name"], "An")
        self.assertEqual(row["email"], "an@example.com")
        self.assertIsNotNone(row["granted_at"])
        self.assertEqual(expires, row["expires_at"])
        self.assertEqual(m.bot.db.jobs[0]["job_type"], "add_client")
        self.assertEqual(m.bot.db.jobs[0]["text_payload"], "An\tan@example.com")

    async def test_active_customer_can_correct_email(self):
        m = self._cog()
        await m._create_pending_invite("abc", 7, 999)
        await m._mark_invite_joined("abc", 111)
        await m._activate_customer(FakeMember(111), "An", "wrong@example.com", 111)
        expires, note, corrected = await m._activate_customer(FakeMember(111), "An", "right@example.com", 111)
        self.assertTrue(corrected)
        self.assertEqual(m.bot.db.rows[0]["email"], "right@example.com")
        self.assertEqual([j["job_type"] for j in m.bot.db.jobs], ["add_client", "remove_client", "add_client"])
        self.assertEqual(m.bot.db.jobs[1]["text_payload"], "wrong@example.com")
        self.assertEqual(m.bot.db.jobs[2]["text_payload"], "An\tright@example.com")


if __name__ == "__main__":
    unittest.main()
