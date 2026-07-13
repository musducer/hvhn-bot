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
        self.assertIn("function hvhnXuLyNhanh()", self.src)
        self.assertIn("ScriptApp.newTrigger('hvhnXuLyNhanh')", self.src)
        self.assertIn("skipDistributionWhenIdle: true", self.src)
        self.assertIn("retryMissingWhenIdle: true", self.src)
        self.assertIn("skipPostSync: true", self.src)

    def test_fast_lane_retries_missing_files_without_full_post_sync(self):
        self.assertIn("phanPhoi({ onlyMissing: true, skipPostSync: true", self.src)
        self.assertIn("options.onlyMissing", self.src)
        self.assertIn("statusText.startsWith('Không thấy')", self.src)
        self.assertIn("if (!options.skipPostSync)", self.src)
        self.assertIn("return { distributed: distributed, missing: missing, touchedRows: touchedRows }", self.src)

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

    def test_preorder_uses_one_reused_form_and_an_email_allowlist(self):
        self.assertIn("🎟️ Khách pre-order", self.src)
        self.assertIn("PREORDER_SOURCE_SPREADSHEET_ID_PROP", self.src)
        self.assertIn("PREORDER_SOURCE_GID_PROP", self.src)
        self.assertIn("PREORDER_DEFAULT_SOURCE_SPREADSHEET_ID = '1YB9tc7mHoLijcSJgUwSGiE1z-kQwTSPF03An92sgw68'", self.src)
        self.assertIn("PREORDER_DEFAULT_SOURCE_GID = '368858728'", self.src)
        self.assertIn("PREORDER_DEFAULT_EMAIL_HEADER = 'Gmail của bạn là gì?'", self.src)
        self.assertIn("function _preorderEmailsFromSourceSheet()", self.src)
        self.assertIn("SpreadsheetApp.openById(cfg.spreadsheetId)", self.src)
        self.assertIn("function caiDatEmailPreorder()", self.src)
        self.assertIn("function taoLaiFormPreorder()", self.src)
        self.assertIn("_openFormIfAlive(props.getProperty(PREORDER_FORM_ID_PROP))", self.src)
        self.assertIn("if (!form) form = _taoFormPreorder(props);", self.src)
        self.assertNotIn("PREORDER_ALLOWED_" + "EMAILS_PROP", self.src)

    def test_preorder_mints_idempotent_invite_and_is_not_client_data_tab(self):
        self.assertIn("function xuLyFormPreorder(e)", self.src)
        self.assertIn("function _preorderCode(email)", self.src)
        self.assertIn("const out = _pmtMintInvite(code, name, email);", self.src)
        self.assertIn("function guiLaiLinkDiscordChoPreorderDangChon()", self.src)
        self.assertIn("name === PMT_ORDER_TAB || name === PREORDER_TAB", self.src)

    def test_preorder_rejects_a_second_form_submit_for_the_same_email(self):
        handler = self.src[self.src.index("function xuLyFormPreorder(e)"):]
        self.assertIn("if (row) {", handler)
        self.assertIn("Từ chối Form pre-order (đã submit)", handler)
        self.assertIn("return;", handler)

    def test_experience_program_automation_removed(self):
        self.assertNotIn("Trai" + "Nghiem", self.src)
        self.assertNotIn("khoaTai" + "Trai" + "Nghiem", self.src)
        self.assertNotIn("_don_them_tai_lieu_" + "trai" + "_nghiem", self.src)


if __name__ == "__main__":
    unittest.main()
