from pathlib import Path
import unittest


class AppsScriptAutomationTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.src = Path("phanphoi.gs").read_text(encoding="utf-8")

    def test_main_menu_exposes_automation_install(self):
        self.assertIn("⚙️ Cài/kiểm tra tự động hoá", self.src)
        self.assertIn("damBaoTuDongHoa", self.src)
        self.assertIn("Kiểm tra trigger tự động", self.src)
        self.assertIn("kiemTraTuDongHoa", self.src)

    def test_automation_trigger_installer_is_idempotent(self):
        self.assertIn("function damBaoTuDongHoa()", self.src)
        self.assertIn("function _coTrigger(handler)", self.src)
        self.assertIn("ScriptApp.newTrigger('hvhnTuDongHoa')", self.src)
        self.assertIn(".everyMinutes(5)", self.src)

    def test_form_setup_also_installs_automation(self):
        idx_form = self.src.index("function caiDatForm()")
        idx_call = self.src.index("caiDatTuDongHoa();", idx_form)
        self.assertGreater(idx_call, idx_form)


if __name__ == "__main__":
    unittest.main()
