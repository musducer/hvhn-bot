import inspect, unittest, watcher
from unittest.mock import patch


class WatcherMdTest(unittest.TestCase):
    def test_has_md_handler_and_folder(self):
        self.assertTrue(hasattr(watcher, "xu_ly_don_them_md"))
        self.assertTrue(hasattr(watcher, "INCOMING_BOT_MD"))

    def test_main_loop_calls_md_handler(self):
        self.assertIn("xu_ly_don_them_md", inspect.getsource(watcher.main_async))

    def test_parse_client_payload(self):
        self.assertEqual(watcher._parse_client_payload("Linh\tkarilinhv@gmail.com"), ("Linh", "karilinhv@gmail.com"))
        self.assertEqual(watcher._parse_client_payload("Linh,KarilinhV@Gmail.com"), ("Linh", "karilinhv@gmail.com"))

    def test_discord_add_client_job_processes_directly_not_queue_file(self):
        with patch.object(watcher, "_process_add_client_payload", return_value=[] ) as process, \
                patch.object(watcher, "_write_atomic") as write_atomic:
            result = watcher._materialize_discord_job({
                "id": 22,
                "job_type": "add_client",
                "text_payload": "Linh\tkarilinhv@gmail.com",
            })
        self.assertIsNone(result)
        process.assert_called_once_with("Linh\tkarilinhv@gmail.com", source="discord_job#22")
        write_atomic.assert_not_called()


if __name__ == "__main__":
    unittest.main()
