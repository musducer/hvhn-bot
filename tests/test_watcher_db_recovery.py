import unittest
from unittest.mock import patch

import watcher


class FakeTx:
    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False


class FakeConn:
    def __init__(self, fail=False):
        self.fail = fail

    async def execute(self, *args):
        if self.fail:
            raise TimeoutError("simulated db timeout")
        return "OK"

    async def fetch(self, *args):
        return []

    def transaction(self):
        return FakeTx()


class FakePool:
    async def release(self, conn):
        return None


class WatcherDbRecoveryTest(unittest.IsolatedAsyncioTestCase):
    async def test_fetch_jobs_survives_temporary_db_failure(self):
        async def failing_acquire(context):
            return FakePool(), FakeConn(fail=True)

        with patch.object(watcher, "_db_acquire", failing_acquire), patch.object(watcher, "_reset_db_pool") as reset:
            rows = await watcher._fetch_discord_jobs()
        self.assertEqual(rows, [])
        reset.assert_called()

    async def test_fetch_jobs_recovers_after_failure(self):
        calls = {"n": 0}

        async def flaky_acquire(context):
            calls["n"] += 1
            return FakePool(), FakeConn(fail=(calls["n"] == 1))

        with patch.object(watcher, "_db_acquire", flaky_acquire), patch.object(watcher, "_reset_db_pool"):
            first = await watcher._fetch_discord_jobs()
            second = await watcher._fetch_discord_jobs()
        self.assertEqual(first, [])
        self.assertEqual(second, [])
        self.assertEqual(calls["n"], 2)


if __name__ == "__main__":
    unittest.main()
