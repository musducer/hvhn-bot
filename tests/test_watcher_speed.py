import inspect
import unittest

import watcher


class WatcherSpeedTest(unittest.TestCase):
    def test_default_local_drive_poll_is_fast_and_configurable(self):
        self.assertLessEqual(watcher.POLL_SECONDS, 10)
        source = inspect.getsource(watcher)
        self.assertIn("HVHN_WATCHER_POLL_SECONDS", source)


if __name__ == "__main__":
    unittest.main()
