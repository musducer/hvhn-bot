# -*- coding: utf-8 -*-
import os
import unittest
from datetime import datetime, timezone, timedelta

os.environ.setdefault("GROQ_API_KEYS", "x")

from cogs.ai import AI


class FakePerms:
    def __init__(self, manage_guild=False, administrator=False):
        self.manage_guild = manage_guild
        self.administrator = administrator


class FakeUser:
    def __init__(self, uid, manage_guild=False, administrator=False):
        self.id = uid
        self.guild_permissions = FakePerms(manage_guild, administrator)


class FakeInteraction:
    def __init__(self, user):
        self.user = user


class FakeConn:
    def __init__(self, db):
        self.db = db

    def transaction(self):
        class _T:
            async def __aenter__(self_):
                return None

            async def __aexit__(self_, *a):
                return False
        return _T()

    async def fetch(self, sql, *args):
        uid = args[0]
        return [
            {"scope": s, "window_start": v["window_start"], "count": v["count"]}
            for (u, s), v in self.db.counters.items() if u == uid
        ]

    async def execute(self, sql, *args):
        up = sql.strip().upper()
        if up.startswith("INSERT"):
            uid, scope, ws = args[0], args[1], args[2]
            self.db.counters[(uid, scope)] = {"window_start": ws, "count": 1}
        elif "count=count+1" in sql.replace(" ", ""):
            uid, scope = args[0], args[1]
            self.db.counters[(uid, scope)]["count"] += 1


class FakeAcquire:
    def __init__(self, db):
        self.db = db

    async def __aenter__(self):
        return FakeConn(self.db)

    async def __aexit__(self, *a):
        return False


class FakeDB:
    def __init__(self, limits=None):
        self.limits = dict(limits or {})
        self.counters = {}

    def acquire(self):
        return FakeAcquire(self)

    async def fetch(self, sql, *args):
        if "ai_usage_limits" in sql:
            return [{"key": k, "value": v} for k, v in self.limits.items()]
        uid = args[0]
        return [
            {"scope": s, "window_start": v["window_start"], "count": v["count"]}
            for (u, s), v in self.counters.items() if u == uid
        ]

    async def execute(self, sql, *args):
        if "ai_usage_limits" in sql:
            self.limits[args[0]] = int(args[1])
        elif sql.strip().upper().startswith("DELETE"):
            uid = args[0]
            for k in [k for k in self.counters if k[0] == uid]:
                del self.counters[k]


class FakeBot:
    def __init__(self, db):
        self.db = db


class AiQuotaTest(unittest.IsolatedAsyncioTestCase):
    def _ai(self, limits=None, db=True):
        ai = AI.__new__(AI)
        ai.bot = FakeBot(FakeDB(limits) if db else None)
        return ai

    async def _use(self, ai, it):
        """Mot luot THANH CONG: check roi consume neu duoc phep (mo phong _then_answer)."""
        allowed, blocking = await ai._check_ai_quota(it)
        if allowed:
            await ai._consume_ai_quota(it)
        return allowed, blocking

    async def test_daily_cap_blocks_eighth_use(self):
        ai = self._ai()
        it = FakeInteraction(FakeUser(1))
        for i in range(7):
            allowed, _ = await self._use(ai, it)
            self.assertTrue(allowed, f"use {i + 1} should pass")
        allowed, blocking = await self._use(ai, it)
        self.assertFalse(allowed)
        self.assertTrue(any(b["label"] == "24 giờ" for b in blocking))

    async def test_weekly_cap_blocks_thirty_first_use(self):
        ai = self._ai(limits={"daily_max": 0})  # tat gioi han ngay -> chi con tuan
        it = FakeInteraction(FakeUser(2))
        for i in range(30):
            allowed, _ = await self._use(ai, it)
            self.assertTrue(allowed, f"use {i + 1} should pass")
        allowed, blocking = await self._use(ai, it)
        self.assertFalse(allowed)
        self.assertTrue(any(b["label"] == "7 ngày" for b in blocking))

    async def test_daily_window_resets_but_weekly_persists(self):
        ai = self._ai(limits={"weekly_max": 1000})  # tuan khong chan de xet rieng ngay
        it = FakeInteraction(FakeUser(3))
        for _ in range(7):
            self.assertTrue((await self._use(ai, it))[0])
        self.assertFalse((await self._use(ai, it))[0])  # 8th blocked
        # Gia lap cua so NGAY het han (day window_start ve qua khu > 24h)
        ai.bot.db.counters[(3, "daily")]["window_start"] = datetime.now(timezone.utc) - timedelta(hours=25)
        allowed, _ = await self._use(ai, it)
        self.assertTrue(allowed)  # ngay reset -> cho phep lai
        self.assertEqual(ai.bot.db.counters[(3, "daily")]["count"], 1)  # cua so ngay moi
        self.assertEqual(ai.bot.db.counters[(3, "weekly")]["count"], 8)  # tuan van tich luy

    async def test_both_tiers_must_pass_weekly_blocks_even_if_daily_fresh(self):
        # Tuan = 5, ngay = 100 -> sau 5 luot, ngay con nhung tuan het -> chan.
        ai = self._ai(limits={"daily_max": 100, "weekly_max": 5})
        it = FakeInteraction(FakeUser(4))
        for _ in range(5):
            self.assertTrue((await self._use(ai, it))[0])
        allowed, blocking = await self._use(ai, it)
        self.assertFalse(allowed)
        self.assertTrue(any(b["label"] == "7 ngày" for b in blocking))

    async def test_staff_is_exempt(self):
        ai = self._ai()
        it = FakeInteraction(FakeUser(5, manage_guild=True))
        for _ in range(50):
            allowed, _ = await self._use(ai, it)
            self.assertTrue(allowed)
        self.assertEqual(ai.bot.db.counters, {})  # khong ghi counter cho staff

    async def test_fail_open_when_db_missing(self):
        ai = self._ai(db=False)
        it = FakeInteraction(FakeUser(6))
        allowed, blocking = await ai._check_ai_quota(it)
        self.assertTrue(allowed)
        self.assertEqual(blocking, [])
        await ai._consume_ai_quota(it)  # khong duoc no khi db None

    async def test_check_alone_never_consumes(self):
        # Diem moi: check KHONG tru luot; chi consume moi tru. Goi check nhieu lan -> khong ghi counter.
        ai = self._ai()
        it = FakeInteraction(FakeUser(9))
        for _ in range(20):
            allowed, _ = await ai._check_ai_quota(it)
            self.assertTrue(allowed)
        self.assertEqual(ai.bot.db.counters, {})  # chua consume lan nao -> chua tru

    async def test_failed_answers_do_not_count_only_successes(self):
        # 3 lan "that bai" (chi check, khong consume) + 7 lan thanh cong -> lan thu 8 thanh cong moi bi chan.
        ai = self._ai()
        it = FakeInteraction(FakeUser(10))
        for _ in range(3):
            await ai._check_ai_quota(it)  # that bai: khong consume
        for i in range(7):
            self.assertTrue((await self._use(ai, it))[0], f"success {i + 1}")
        self.assertFalse((await self._use(ai, it))[0])  # het 7 luot thanh cong

    async def test_denied_request_does_not_consume(self):
        ai = self._ai()
        it = FakeInteraction(FakeUser(7))
        for _ in range(7):
            await self._use(ai, it)
        before = ai.bot.db.counters[(7, "daily")]["count"]
        await self._use(ai, it)  # blocked -> khong consume
        after = ai.bot.db.counters[(7, "daily")]["count"]
        self.assertEqual(before, after)

    async def test_admin_raising_limit_unblocks_same_window(self):
        ai = self._ai()
        it = FakeInteraction(FakeUser(8))
        for _ in range(7):
            await self._use(ai, it)
        self.assertFalse((await self._use(ai, it))[0])
        await ai._set_limit_key("daily_max", 10)  # admin nang gioi han
        allowed, _ = await self._use(ai, it)
        self.assertTrue(allowed)  # cung cua so, gio duoc dung tiep

    def test_retrieval_guard_is_not_counted_as_a_successful_answer(self):
        self.assertTrue(AI._insufficient_answer(AI._retrieval_guard_message()))


if __name__ == "__main__":
    unittest.main()
