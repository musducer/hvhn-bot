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

    def test_payment_menu_has_resend_and_webhook_test_tools(self):
        self.assertIn("🔁 Gửi lại link Discord cho đơn đang chọn", self.src)
        self.assertIn("guiLaiLinkDiscordChoDonDangChon", self.src)
        self.assertIn("🧪 Test webhook bằng mã đơn đang chọn", self.src)
        self.assertIn("testWebhookThanhToanChoDonDangChon", self.src)

    def test_payment_webhook_logs_and_uses_shared_mint_send_path(self):
        self.assertIn("function _pmtMintAndSendForRow", self.src)
        self.assertIn("Webhook thanh toán tới", self.src)
        self.assertIn("Webhook không khớp mã đơn", self.src)
        self.assertIn("data.creditAmount", self.src)
        self.assertIn("_pmtMintAndSendForRow(sheet, i + 2", self.src)

    def test_payment_settings_shows_full_sepay_url_with_token(self):
        self.assertIn("ScriptApp.getService().getUrl()", self.src)
        self.assertIn("URL DÁN VÀO SEPAY phải là", self.src)
        self.assertIn("?token=", self.src)


if __name__ == "__main__":
    unittest.main()
