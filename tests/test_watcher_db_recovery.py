import unittest
from unittest.mock import patch

import watcher


class FakeTx:
    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False


class FakeConn:
    def __init__(self, fail=False, rows=None):
        self.fail = fail
        self.rows = list(rows or [])
        self.execute_calls = []

    async def execute(self, *args):
        self.execute_calls.append(args)
        if self.fail:
            raise TimeoutError("simulated db timeout")
        return "OK"

    async def fetch(self, *args):
        return self.rows

    def transaction(self):
        return FakeTx()


class FakeAcquire:
    def __init__(self, pool, conn):
        self.pool = pool
        self.conn = conn

    async def __aenter__(self):
        self.pool.active += 1
        return self.conn

    async def __aexit__(self, exc_type, exc, tb):
        self.pool.active -= 1
        self.pool.released += 1
        return False


class FakePool:
    def __init__(self, fail=False, rows=None):
        self.fail = fail
        self.rows = rows
        self.active = 0
        self.released = 0
        self.last_conn = None

    def acquire(self):
        self.last_conn = FakeConn(fail=self.fail, rows=self.rows)
        return FakeAcquire(self, self.last_conn)

    def get_size(self):
        return 1

    def get_idle_size(self):
        return 1 - self.active


class WatcherDbRecoveryTest(unittest.IsolatedAsyncioTestCase):
    async def test_fetch_jobs_survives_temporary_db_failure(self):
        pool = FakePool(fail=True)

        async def failing_pool(context):
            return pool

        with patch.object(watcher, "DATABASE_URL", "postgresql://test"), \
                patch.object(watcher, "_get_db_pool", failing_pool), \
                patch.object(watcher, "_reset_db_pool") as reset:
            rows = await watcher._fetch_discord_jobs()
        self.assertEqual(rows, [])
        self.assertEqual(pool.active, 0)
        self.assertEqual(pool.released, 1)
        reset.assert_called()

    async def test_fetch_jobs_recovers_after_failure(self):
        calls = {"n": 0}
        pools = []

        async def flaky_pool(context):
            calls["n"] += 1
            pool = FakePool(fail=(calls["n"] == 1))
            pools.append(pool)
            return pool

        with patch.object(watcher, "DATABASE_URL", "postgresql://test"), \
                patch.object(watcher, "_get_db_pool", flaky_pool), \
                patch.object(watcher, "_reset_db_pool"):
            first = await watcher._fetch_discord_jobs()
            second = await watcher._fetch_discord_jobs()
        self.assertEqual(first, [])
        self.assertEqual(second, [])
        self.assertEqual(calls["n"], 2)
        self.assertTrue(all(pool.active == 0 for pool in pools))
        self.assertTrue(all(pool.released == 1 for pool in pools))

    async def test_processing_lease_starts_when_job_is_claimed(self):
        job = {"id": 7, "job_type": "add_client", "text_payload": "An\ta@example.com",
               "file_name": None, "file_data": None}
        pool = FakePool(rows=[job])

        async def fake_pool(_context):
            return pool

        with patch.object(watcher, "DATABASE_URL", "postgresql://test"), \
                patch.object(watcher, "_get_db_pool", fake_pool):
            rows = await watcher._fetch_discord_jobs()

        self.assertEqual(rows[0]["id"], 7)
        sql = "\n".join(str(call[0]) for call in pool.last_conn.execute_calls)
        self.assertIn("COALESCE(processing_started_at, created_at)", sql)
        self.assertIn("processing_started_at = now()", sql)
        self.assertIn("ADD COLUMN IF NOT EXISTS processing_started_at", sql)


if __name__ == "__main__":
    unittest.main()
