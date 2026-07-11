from pathlib import Path
import unittest


class TrialDownloadLockTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.src = Path("phanphoi.gs").read_text(encoding="utf-8")

    def test_trial_lock_helper_uses_drive_api(self):
        self.assertIn("function _khoaTaiFileTraiNghiem", self.src)
        self.assertIn("copyRequiresWriterPermission: true", self.src)
        self.assertIn("LỖI khóa tải tài liệu trải nghiệm", self.src)

    def test_trial_lock_has_one_minute_trigger(self):
        self.assertIn("function khoaTaiTraiNghiemLienTuc", self.src)
        self.assertIn("ScriptApp.newTrigger('khoaTaiTraiNghiemLienTuc')", self.src)
        self.assertIn(".everyMinutes(1)", self.src)


if __name__ == "__main__":
    unittest.main()
