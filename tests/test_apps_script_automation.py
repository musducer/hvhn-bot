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
        self.assertIn("ScriptApp.newTrigger('xuLyDonPreorderTuDong')", self.src)
        self.assertIn("skipDistributionWhenIdle: true", self.src)
        self.assertIn("retryMissingWhenIdle: true", self.src)
        self.assertIn("skipPostSync: true", self.src)

    def test_simple_sheet_triggers_never_call_drive_and_repair_removes_legacy_edit_triggers(self):
        on_edit = self.src[self.src.index("function onEdit(e)"):self.src.index("function ensureDashboard")]
        on_open = self.src[self.src.index("function onOpen()"):self.src.index("function onEdit(e)")]
        installer = self.src[self.src.index("function caiDatTuDongHoa()"):self.src.index("function _kiemTraQuyenDrive()")]
        self.assertIn("capNhatDashboard({ skipDrive: true })", on_edit)
        self.assertNotIn("DriveApp.", on_edit)
        self.assertNotIn("DriveApp.", on_open)
        self.assertIn("function suaLoiQuyenDriveVaTrigger()", self.src)
        self.assertIn("onEdit: true", self.src)
        self.assertIn("legacyHandlers[handler]", installer)

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

    def test_forms_have_email_validation_and_single_submit_triggers(self):
        self.assertIn("function _emailTextValidation()", self.src)
        self.assertIn("requireTextIsEmail()", self.src)
        self.assertIn("function _ensureSingleFormTrigger(handler, form)", self.src)
        self.assertIn("trigger.getTriggerSourceId() === form.getId()", self.src)
        self.assertIn("_ensureSingleFormTrigger('xuLyFormDatMua', form)", self.src)
        self.assertIn("_ensureSingleFormTrigger('xuLyFormPreorder', form)", self.src)
        self.assertIn("function _isValidPersonName(name)", self.src)
        self.assertIn("!_isValidPersonName(name) || !_isValidEmail(email)", self.src)

    def test_expiry_and_document_deletion_cover_duplicate_legacy_folders(self):
        expiry = self.src[self.src.index("function kiemTraHetHan()"):self.src.index("function giaHanMotDong")]
        remove_doc = self.src[self.src.index("function _xoaMotTaiLieu"):self.src.index("function xoaTaiLieuDaTich")]
        self.assertIn("while (folders.hasNext())", expiry)
        self.assertIn("while (folders.hasNext())", remove_doc)

    def test_client_name_email_identity_is_enforced_before_distribution(self):
        merge = self.src[
            self.src.index("function mergeRowsIntoClientTabs"):
            self.src.index("function tuDongXuLyFileMoi")
        ]
        distribution = self.src[
            self.src.index("function phanPhoi(options)"):
            self.src.index("function capNhatDashboard")
        ]
        self.assertIn("TỪ CHỐI trùng tên khách khác email", merge)
        self.assertIn("identityMismatch", distribution)
        self.assertIn("Lỗi định danh", distribution)
        self.assertIn("_removeAccess(folder, cleanEmail)", distribution)

    def test_invalid_reserved_clients_are_rejected_and_viewer_access_is_verified(self):
        merge = self.src[
            self.src.index("function mergeRowsIntoClientTabs"):
            self.src.index("function tuDongXuLyFileMoi")
        ]
        share = self.src[
            self.src.index("function _ensureOnlyViewer"):
            self.src.index("function _removeAccess")
        ]
        self.assertIn("_isValidClientTabName(clientName)", merge)
        self.assertIn("_isValidEmail(clientEmail)", merge)
        self.assertIn("isSystemTab(clean)", self.src)
        self.assertIn("Drive không xác nhận quyền Viewer", share)
        self.assertIn("Không thể hạ quyền Editor", share)
        self.assertNotIn("catch", share)

    def test_migration_and_revocation_fail_closed(self):
        migration = self.src[
            self.src.index("function tachTheoKhach"):
            self.src.index("function mergeRowsIntoClientTabs")
        ]
        revoke = self.src[
            self.src.index("function _removeAccess"):
            self.src.index("// ============ THEN TRÊN WEB")
        ]
        expiry = self.src[
            self.src.index("function kiemTraHetHan"):
            self.src.index("function giaHanMotDong")
        ]
        self.assertIn("_isValidClientTabName(name)", migration)
        self.assertIn("groupEmails[name] !== email", migration)
        self.assertIn("Drive chưa xác nhận gỡ hết quyền", revoke)
        self.assertNotIn("catch", revoke)
        self.assertIn("if (!_goQuyenThenTrenWebNeuKhongConHan", expiry)

    def test_preorder_candidate_is_validated_before_properties_are_changed(self):
        handler = self.src[self.src.index("function caiDatEmailPreorder()"):self.src.index("function _taoFormPreorder")]
        self.assertLess(handler.index("_preorderEmailsFromConfig(candidate)"), handler.index("props.setProperty"))

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

    def test_payment_rows_and_webhooks_are_serialized(self):
        form_handler = self.src[
            self.src.index("function xuLyFormDatMua(e)"):self.src.index("function _pmtMintInvite")
        ]
        webhook_handler = self.src[
            self.src.index("function doPost(e)"):self.src.index("function doGet(e)")
        ]
        manual_resend = self.src[
            self.src.index("function guiLaiLinkDiscordChoDonDangChon()"):
            self.src.index("function _pmtVerifyWebhook")
        ]
        self.assertIn("LockService.getScriptLock()", form_handler)
        self.assertIn("lock.waitLock(30000)", form_handler)
        self.assertIn("LockService.getScriptLock()", webhook_handler)
        self.assertIn("if (locked) lock.releaseLock()", webhook_handler)
        self.assertIn("LockService.getScriptLock()", manual_resend)
        self.assertIn("if (locked) lock.releaseLock()", manual_resend)
        self.assertIn("currentStatus !== 'da_xu_ly'", form_handler)
        self.assertIn("loi_gui_email_qr", form_handler)

    def test_discord_renewals_have_a_bounded_idempotency_history(self):
        handler = self.src[
            self.src.index("function xuLyLenhGiaHanDiscordTuDong()"):
            self.src.index("function decorateRegistry")
        ]
        self.assertIn("_discordRenewSeen(jobId)", handler)
        self.assertIn("_discordRenewMark(jobId)", handler)
        self.assertIn("history.slice(-300)", self.src)

    def test_dashboard_clears_all_old_rows(self):
        self.assertNotIn("A4:Z999", self.src)
        self.assertIn("dash.getMaxRows() - 3", self.src)

    def test_payment_uses_payos_qr_with_fixed_amount_and_signed_webhook(self):
        self.assertIn("const PMT_DEFAULT_AMOUNT = 99999", self.src)
        self.assertIn("function datGiaGoiHocLieu()", self.src)
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

    def test_customer_emails_hide_provider_names_and_attach_onboarding_materials(self):
        qr_email = self.src[
            self.src.index("function _pmtSendPaymentEmail"):
            self.src.index("// onFormSubmit: tạo QR/link PayOS riêng")
        ]
        paid_email = self.src[
            self.src.index("function _pmtSendInviteEmail"):
            self.src.index("function _pmtMintAndSendForRow")
        ]
        preorder_email = self.src[
            self.src.index("function _preorderSendInviteEmail"):
            self.src.index("function _preorderFindRowByEmail")
        ]
        for customer_email in (qr_email, paid_email, preorder_email):
            self.assertNotIn("PayOS", customer_email)
            self.assertNotIn("api-merchant", customer_email)
        self.assertIn("const CUSTOMER_GUIDE_URL", self.src)
        self.assertIn("function caiDatTaiLieuHuongDanKhach()", self.src)
        self.assertIn("CUSTOMER_NOTICE_IMAGE_FILE_ID_PROP", self.src)
        self.assertIn("function _customerOnboardingMaterials()", self.src)
        self.assertIn("message.attachments = attachments", self.src)
        self.assertIn("_customerOnboardingPlainText(materials)", paid_email)
        self.assertIn("_customerOnboardingHtml(materials)", paid_email)
        self.assertIn("_sendCustomerAccessEmail", paid_email)
        self.assertIn("_customerOnboardingPlainText(materials)", preorder_email)
        self.assertIn("_customerOnboardingHtml(materials)", preorder_email)
        self.assertIn("_sendCustomerAccessEmail", preorder_email)

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

    def test_preorder_queues_idempotent_invites_and_is_not_client_data_tab(self):
        self.assertIn("function xuLyFormPreorder(e)", self.src)
        self.assertIn("function xuLyDonPreorderTuDong()", self.src)
        self.assertIn("function _preorderCode(email)", self.src)
        worker = self.src[
            self.src.index("function xuLyDonPreorderTuDong()"):
            self.src.index("function xuLyFormPreorder(e)")
        ]
        form_handler = self.src[
            self.src.index("function xuLyFormPreorder(e)"):
            self.src.index("function guiLaiLinkDiscordChoPreorderDangChon()")
        ]
        self.assertIn("const out = _pmtMintInvite(code, name, email);", worker)
        self.assertIn("'cho_tao_invite'", form_handler)
        self.assertNotIn("_pmtMintInvite", form_handler)
        self.assertIn("loi_tao_invite", worker)
        self.assertIn("loi_gui_email", worker)
        self.assertIn("PREORDER_STALE_MINUTES = 2", self.src)
        self.assertIn("note.replace(/^worker_bat_dau\\s+/, '') || rows[i][0]", worker)
        self.assertIn("function kiemTraEmailPreorder()", self.src)
        self.assertIn("function guiLaiLinkDiscordChoPreorderDangChon()", self.src)
        resend = self.src[self.src.index("function guiLaiLinkDiscordChoPreorderDangChon()") :]
        self.assertIn("'cho_tao_invite'", resend)
        self.assertNotIn("_pmtMintInvite", resend)
        system_tabs = self.src[self.src.index("function isSystemTab"):self.src.index("function _isValidClientTabName")]
        self.assertIn("PMT_ORDER_TAB, PREORDER_TAB", system_tabs)

    def test_preorder_rejects_a_second_form_submit_for_the_same_email(self):
        handler = self.src[self.src.index("function xuLyFormPreorder(e)"):]
        self.assertIn("if (row) {", handler)
        self.assertIn("Từ chối Form pre-order (đã submit)", handler)
        self.assertIn("return;", handler)

    def test_then_web_viewer_access_follows_customer_lifecycle(self):
        self.assertIn("const THEN_TREN_WEB_FILE_ID = '1I_L8b8U0y7mBx6IW_MGIOAo1lgV8eXr4'", self.src)
        self.assertIn("function capQuyenThenTrenWebChoKhachConHan(conHan)", self.src)
        self.assertIn("capQuyenThenTrenWebChoKhachConHan(conHan);", self.src)
        self.assertIn("function _goQuyenThenTrenWebNeuKhongConHan(email, excludedName)", self.src)
        self.assertIn("_goQuyenThenTrenWebNeuKhongConHan(email, name)", self.src)

    def test_experience_program_automation_removed(self):
        self.assertNotIn("Trai" + "Nghiem", self.src)
        self.assertNotIn("khoaTai" + "Trai" + "Nghiem", self.src)
        self.assertNotIn("_don_them_tai_lieu_" + "trai" + "_nghiem", self.src)


if __name__ == "__main__":
    unittest.main()
