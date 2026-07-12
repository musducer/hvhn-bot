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
        self.assertIn("Webhook PayOS bị từ chối", self.src)
        self.assertIn("Webhook PayOS không khớp orderCode", self.src)
        self.assertIn("data.orderCode", self.src)
        self.assertIn("_pmtMintAndSendForRow(sheet, i + 2", self.src)

    def test_payment_uses_payos_qr_with_fixed_amount_and_signed_webhook(self):
        self.assertIn("const PMT_FIXED_AMOUNT = 60000", self.src)
        self.assertIn("function _pmtCreatePayosLink", self.src)
        self.assertIn("/v2/payment-requests", self.src)
        self.assertIn("function _pmtVerifyWebhook", self.src)
        self.assertIn("Utilities.computeHmacSha256Signature", self.src)
        self.assertIn("String(rows[i][10] || '') !== expectedOrderCode", self.src)
        self.assertIn("Number(data.amount || 0) !== gia", self.src)

    def test_payment_email_has_qr_and_safe_checkout_fallback(self):
        self.assertIn("function _pmtSendPaymentEmail", self.src)
        self.assertIn("Mã QR thanh toán của bạn", self.src)
        self.assertIn("Mở trang thanh toán an toàn", self.src)
        self.assertIn("function ketNoiWebhookPayOS", self.src)
        self.assertIn("/confirm-webhook", self.src)


if __name__ == "__main__":
    unittest.main()
