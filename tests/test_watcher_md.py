import inspect, unittest, watcher


class WatcherMdTest(unittest.TestCase):
    def test_has_md_handler_and_folder(self):
        self.assertTrue(hasattr(watcher, "xu_ly_don_them_md"))
        self.assertTrue(hasattr(watcher, "INCOMING_BOT_MD"))

    def test_main_loop_calls_md_handler(self):
        self.assertIn("xu_ly_don_them_md", inspect.getsource(watcher.main_async))


if __name__ == "__main__":
    unittest.main()
