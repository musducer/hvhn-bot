import inspect
import unittest

import watcher


class WatcherSpeedTest(unittest.TestCase):
    def test_default_local_drive_poll_is_fast_and_configurable(self):
        self.assertLessEqual(watcher.POLL_SECONDS, 5)
        self.assertGreaterEqual(watcher.DISCORD_JOB_IDLE_POLL_SECONDS, 21600)
        self.assertLess(watcher._last_discord_job_poll, 0)
        self.assertEqual(watcher.DB_POOL_MIN_SIZE, 0)
        source = inspect.getsource(watcher)
        self.assertIn("HVHN_WATCHER_POLL_SECONDS", source)
        self.assertIn("HVHN_WATCHER_DB_IDLE_POLL_SECONDS", source)
        self.assertIn("HVHN_DB_POOL_IDLE_SECONDS", source)
        self.assertIn("HVHN_STABLE_CHECKS", source)
        self.assertIn("HVHN_STABLE_GAP_SECONDS", source)
        self.assertIn("_has_local_pending_jobs", source)
        self.assertIn("_xu_ly_don_discord_khi_den_luot", source)
        self.assertIn("await asyncio.sleep(1 if (_has_local_pending_jobs() or processed_discord) else POLL_SECONDS)", source)


if __name__ == "__main__":
    unittest.main()
