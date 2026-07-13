import inspect
import unittest

import watcher


class WatcherSpeedTest(unittest.TestCase):
    def test_default_local_drive_poll_is_fast_and_configurable(self):
        self.assertLessEqual(watcher.POLL_SECONDS, 5)
        source = inspect.getsource(watcher)
        self.assertIn("HVHN_WATCHER_POLL_SECONDS", source)
        self.assertIn("HVHN_STABLE_CHECKS", source)
        self.assertIn("HVHN_STABLE_GAP_SECONDS", source)
        self.assertIn("_has_local_pending_jobs", source)
        self.assertIn("await asyncio.sleep(1 if _has_local_pending_jobs() else POLL_SECONDS)", source)


if __name__ == "__main__":
    unittest.main()
