import asyncio
import inspect
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

import watcher


class WatcherMdTest(unittest.TestCase):
    def test_has_md_handler_and_folder(self):
        self.assertTrue(hasattr(watcher, "xu_ly_don_them_md"))
        self.assertTrue(hasattr(watcher, "INCOMING_BOT_MD"))

    def test_main_loop_calls_md_handler(self):
        self.assertIn("xu_ly_don_them_md", inspect.getsource(watcher.main_async))

    def test_parse_client_payload(self):
        self.assertEqual(watcher._parse_client_payload("Linh\tkarilinhv@gmail.com"), ("Linh", "karilinhv@gmail.com"))
        self.assertEqual(watcher._parse_client_payload("Linh,KarilinhV@Gmail.com"), ("Linh", "karilinhv@gmail.com"))

    def test_stable_rejects_a_file_that_changes_at_every_sample(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "syncing.pdf"
            path.write_bytes(b"x")
            with patch.object(watcher.os.path, "getsize", side_effect=[1, 2, 3]), \
                    patch.object(watcher.time, "sleep"):
                self.assertFalse(watcher._stable(path, checks=3, gap=0))

    def test_stable_accepts_two_equal_samples(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "ready.pdf"
            path.write_bytes(b"ready")
            with patch.object(watcher.os.path, "getsize", side_effect=[5, 5]), \
                    patch.object(watcher.time, "sleep"):
                self.assertTrue(watcher._stable(path, checks=2, gap=0))

    def test_existing_email_reuses_canonical_client_name(self):
        captured = {}

        def fake_render(_docs, recipients):
            captured["recipient"] = recipients[0]
            return []

        with patch.object(watcher, "find_client", return_value={"name": "Tên đã lưu", "email": "a@example.com"}), \
                patch.object(watcher, "list_docs", return_value=[]), \
                patch.object(watcher, "render_batch", side_effect=fake_render), \
                patch.object(watcher, "write_new_rows_csv"):
            watcher._process_add_client_payload("Tên gõ khác\ta@example.com")

        self.assertEqual(captured["recipient"]["name"], "Tên đã lưu")

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

    def test_discord_renewal_carries_its_database_job_id(self):
        with patch.object(watcher, "_write_atomic") as write_atomic:
            watcher._materialize_discord_job({
                "id": 41,
                "job_type": "renew_client",
                "text_payload": "an@example.com\t30\td",
            })
        payload = write_atomic.call_args.args[1].decode("utf-8")
        self.assertEqual(payload, "an@example.com\t30\td\tjob:41")

    def test_discord_document_deletion_rejects_path_segments_before_materializing(self):
        with patch.object(watcher, "_write_atomic") as write_atomic:
            with self.assertRaisesRegex(ValueError, "không hợp lệ"):
                watcher._materialize_discord_job({
                    "id": 43,
                    "job_type": "remove_document",
                    "text_payload": r"..\private",
                })
        write_atomic.assert_not_called()

    def test_invalid_discord_pdf_is_rejected_without_leaving_a_file(self):
        with tempfile.TemporaryDirectory() as temp_dir, \
                patch.object(watcher, "INCOMING_DOCS", temp_dir):
            with self.assertRaisesRegex(ValueError, "PDF không đọc được"):
                watcher._materialize_discord_job({
                    "id": 42,
                    "job_type": "add_document",
                    "file_name": "broken.pdf",
                    "file_data": b"%PDF-not-really-a-pdf",
                })
            self.assertEqual(list(Path(temp_dir).iterdir()), [])

    def test_discord_pdf_replay_reuses_the_job_target(self):
        with tempfile.TemporaryDirectory() as temp_dir, \
                patch.object(watcher, "INCOMING_DOCS", temp_dir), \
                patch.object(watcher, "_validate_local_pdf"):
            job = {
                "id": 44,
                "job_type": "add_document",
                "file_name": "lesson.pdf",
                "file_data": b"%PDF-replay-test",
            }
            first = watcher._materialize_discord_job(job)
            second = watcher._materialize_discord_job(job)

        self.assertEqual(first, second)
        self.assertEqual(Path(first).name, "discord_44__lesson.pdf")

    def test_document_store_reuses_replay_but_never_overwrites_different_pdf(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            incoming = Path(temp_dir) / "incoming"
            store = Path(temp_dir) / "docs"
            incoming.mkdir()
            first = incoming / "first.pdf"
            replay = incoming / "replay.pdf"
            different = incoming / "different.pdf"
            first.write_bytes(b"%PDF-first")
            replay.write_bytes(b"%PDF-first")
            different.write_bytes(b"%PDF-second")

            original = Path(watcher._copy_pdf_to_store(first, store, "lesson.pdf"))
            replayed = Path(watcher._copy_pdf_to_store(replay, store, "lesson.pdf"))
            renamed_replay = Path(watcher._copy_pdf_to_store(replay, store, "renamed.pdf"))
            second = Path(watcher._copy_pdf_to_store(different, store, "lesson.pdf"))

            self.assertEqual(original, replayed)
            self.assertEqual(original, renamed_replay)
            self.assertNotEqual(original, second)
            self.assertEqual(original.read_bytes(), b"%PDF-first")
            self.assertEqual(second.read_bytes(), b"%PDF-second")
            self.assertEqual(list(store.glob("*.part")), [])

    def test_discord_job_ack_retries_without_repeating_the_side_effect(self):
        async def scenario():
            mark = AsyncMock(side_effect=[False, False, True])
            with patch.object(watcher, "_mark_discord_job", mark), \
                    patch.object(watcher.asyncio, "sleep", new=AsyncMock()):
                result = await watcher._ack_discord_job(7, "done", clear_file=True)
            self.assertTrue(result)
            self.assertEqual(mark.await_count, 3)

        asyncio.run(scenario())


if __name__ == "__main__":
    unittest.main()
