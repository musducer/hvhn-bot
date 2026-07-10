import os
import unittest
import hvhn_batch


class TrialRenderTest(unittest.TestCase):
    def test_render_trial_uses_fixed_recipient(self):
        captured = {}

        def fake_convert(inp, outp, *, recipient_name, recipient_email, warning_text):
            captured["name"] = recipient_name
            captured["email"] = recipient_email
            captured["out"] = outp

        orig = hvhn_batch.convert_to_secure_image_pdf
        hvhn_batch.convert_to_secure_image_pdf = fake_convert
        try:
            fn = hvhn_batch.render_trial("/tmp/Chi Pheo.pdf", "/tmp/shared")
        finally:
            hvhn_batch.convert_to_secure_image_pdf = orig

        self.assertEqual(captured["name"], "Nguyễn Văn A")
        self.assertEqual(captured["email"], "nguyenvana@gmail.com")
        self.assertEqual(fn, "Nguyễn Văn A__Chi Pheo.pdf")
        self.assertTrue(captured["out"].endswith("Nguyễn Văn A__Chi Pheo.pdf"))


import inspect
import watcher


class WatcherTrialTest(unittest.TestCase):
    def test_watcher_has_trial_handler_and_loop(self):
        self.assertTrue(hasattr(watcher, "xu_ly_don_trai_nghiem"))
        self.assertTrue(hasattr(watcher, "INCOMING_TRIAL"))
        self.assertIn("xu_ly_don_trai_nghiem", inspect.getsource(watcher.main_async))


if __name__ == "__main__":
    unittest.main()
