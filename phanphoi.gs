// Dán vào: Google Sheet > Extensions > Apps Script
// Trước khi chạy: Services (+) > thêm "Drive API" (Advanced Google service)
// Mỗi tab khách có header: TenNguoiNhan | Email | TenFile | TrangThai

const SOURCE_FOLDER_ID = '15Ipn2p7b3_J-_pszxSh05vSMET2rf9Dl';
const DEST_ROOT_FOLDER_ID = '1Afa6oP-vRcpjA1ooSpjXJDRdhiZbCQhB';

const DASHBOARD_NAME = 'Dashboard';
const STAGING_NAME = 'Nhập mới';
const REGISTRY_NAME = 'Khách hàng';   // tab quản lý gói/hạn dùng
const DOCS_NAME = 'Tài liệu';         // tab danh sách tài liệu
const LOG_NAME = 'Nhật ký';           // tab lịch sử thao tác
const SEARCH_CELL = 'B1';

const SUB_DAYS = 30;   // 1 gói = 30 ngày (chỉ để suy ra SUB_HOURS mặc định)
const SUB_HOURS = SUB_DAYS * 24; // gói mặc định tính theo GIỜ = 720h
const WARN_DAYS = 3;   // cảnh báo "sắp hết" khi còn <= 3 ngày
const WARN_HOURS = WARN_DAYS * 24; // ngưỡng cảnh báo tính theo GIỜ = 72h
const RENEW_COL = 7;   // cột G ở tab Khách hàng: ô tick "Gia hạn"
const DEL_COL = 8;     // cột H ở tab Khách hàng: ô tick "Xóa khách"
const HOURS_COL = 9;   // cột I ở tab Khách hàng: số giờ gia hạn (trống = SUB_HOURS)

const HVHN_PARENT_FOLDER_ID_EARLY = '10RjJY_DVmI8Ys-tV1k_HzMLIIFCvbRWs';

// Ứng dụng Then trên web là một file Drive riêng. Khách chỉ nhận quyền Viewer
// bằng đúng email đã kích hoạt; quyền này đi cùng vòng đời học liệu bên dưới.
const THEN_TREN_WEB_FILE_ID = '1I_L8b8U0y7mBx6IW_MGIOAo1lgV8eXr4';

// C1: allowlist người quản lý được phép gửi Form (thêm khách/tài liệu). ĐỂ TRỐNG = TẮT
// (nhận mọi đơn như cũ, tương thích ngược). BẬT: điền email quản lý vào đây + trong TỪNG Form
// bật "Settings → Responses → Collect email addresses". Đơn từ email lạ sẽ bị bỏ qua + ghi log.
const MANAGER_EMAILS = []; // vd: ['chu@gmail.com', 'quanly2@gmail.com']

// B1: cảnh báo registry có 2+ khách CÙNG TÊN nhưng KHÁC EMAIL. mergeRowsIntoClientTabs
// và phanPhoi còn có cổng cứng: từ chối dòng xung đột và thu quyền email sai khỏi folder.
let _canhBaoTrungTenLast = '';
function canhBaoTrungTenKhach() {
  try {
    const reg = ensureRegistry();
    const last = reg.getLastRow();
    if (last < 2) return;
    const vals = reg.getRange(2, 1, last - 1, 2).getValues(); // Tên, Email
    const byName = {};
    vals.forEach(r => {
      const name = String(r[0] || '').trim().toLowerCase();
      const email = String(r[1] || '').trim().toLowerCase();
      if (!name || !email) return;
      (byName[name] = byName[name] || {})[email] = true;
    });
    const dup = Object.keys(byName).filter(n => Object.keys(byName[n]).length > 1);
    const sig = dup.sort().join('|');
    if (dup.length && sig !== _canhBaoTrungTenLast) {
      _canhBaoTrungTenLast = sig; // tránh spam log mỗi 5'
      ghiLog('CẢNH BÁO trùng tên khách (khác email)', dup.join(', ') + ' — đặt tên phân biệt để tránh dùng chung folder');
    }
  } catch (e) {}
}

function _formAllowed(e) {
  if (!MANAGER_EMAILS.length) return true; // tính năng tắt
  var email = '';
  try {
    email = String((e && e.response && e.response.getRespondentEmail && e.response.getRespondentEmail()) || '').toLowerCase();
  } catch (err) {}
  var allow = MANAGER_EMAILS.map(function (x) { return String(x).toLowerCase().trim(); });
  var ok = email && allow.indexOf(email) >= 0;
  if (!ok) { try { ghiLog('Từ chối đơn Form (ngoài allowlist)', email || '(chưa bật thu thập email)'); } catch (e2) {} }
  return ok;
}

const XOA_KHACH_NAME = '_don_xoa_khach';
const XOA_TAILIEU_NAME = '_don_xoa_tai_lieu';
const SHEET_XOA_KHACH_NAME = '_don_sheet_xoa_khach';
const SHEET_XOA_TAILIEU_NAME = '_don_sheet_xoa_tai_lieu';
const SHEET_GIAHAN_KHACH_NAME = '_don_sheet_giahan_khach';
const DISCORD_RENEW_HISTORY_PROP = 'DISCORD_RENEW_JOB_HISTORY';
const SHEET_STATUS_NAME = '_sheet_status';
const SHEET_STATUS_FILE = 'sheet_status.json';
const BOT_ONLY_DOC_PREFIXES = ['discord'];
// Mọi thao tác tự động chạm Drive phải chạy bằng đúng tài khoản đã được xác minh.
// Tránh trigger do một tài khoản khác tạo gây "Access denied: DriveApp" rồi dừng cả luồng.
const AUTOMATION_OWNER_PROP = 'HVHN_AUTOMATION_OWNER_EMAIL';
const AUTOMATION_OWNER_SKIP_LOG_PROP = 'HVHN_AUTOMATION_OWNER_SKIP_LOG_AT';

// Tab không phải dữ liệu khách -> luôn bỏ qua khi quét
function isSystemTab(name) {
  const key = String(name || '').trim().toLowerCase();
  return [DASHBOARD_NAME, STAGING_NAME, REGISTRY_NAME, DOCS_NAME, LOG_NAME,
    PMT_ORDER_TAB, PREORDER_TAB].some(tab => String(tab).toLowerCase() === key);
}

function _isValidClientTabName(name) {
  const clean = String(name || '').trim();
  return !!clean && clean.length <= 80 && !isSystemTab(clean)
    && !/[:\\\/\?\*\[\]]/.test(clean) && !/^'|'$/.test(clean)
    && !/^[=+\-@]/.test(clean);
}

// Ghi 1 dòng nhật ký: thời gian | hành động | chi tiết. Không làm hỏng flow nếu lỗi.
function ghiLog(action, detail) {
  try {
    const ss = SpreadsheetApp.getActiveSpreadsheet();
    let log = ss.getSheetByName(LOG_NAME);
    if (!log) {
      log = ss.insertSheet(LOG_NAME);
      log.getRange(1, 1, 1, 3).setValues([['Thời gian', 'Hành động', 'Chi tiết']]);
      log.getRange(1, 1, 1, 3).setBackground('#5f6368').setFontColor('#fff').setFontWeight('bold');
      log.setFrozenRows(1);
      log.setColumnWidth(1, 150); log.setColumnWidth(2, 160); log.setColumnWidth(3, 400);
    }
    log.insertRowAfter(1);
    log.getRange(2, 1, 1, 3).setValues([[new Date(), action, detail]]);
    log.getRange(2, 1).setNumberFormat('dd/mm/yyyy HH:mm:ss');
  } catch (e) {}
}

// ============ MENU + KHỞI TẠO TỰ ĐỘNG ============

function onOpen() {
  ensureDashboard();
  ensureStaging();
  ensureRegistry();
  const ui = SpreadsheetApp.getUi();
  ui.createMenu('HVHN')
    .addItem('🚀 Chạy tất cả NGAY (phân phối + gia hạn + hết hạn + dashboard)', 'hvhnTuDongHoa')
    .addItem('⚙️ Cài/kiểm tra tự động hoá', 'damBaoTuDongHoa')
    .addItem('🛠️ Sửa quyền Drive + trigger', 'suaLoiQuyenDriveVaTrigger')
    .addItem('📝 Nhập mới thủ công (tab "Nhập mới") + Phân phối', 'themMoiVaPhanPhoi')
    .addItem('🔁 Phân phối lại (quét toàn bộ)', 'phanPhoi')
    .addItem('♻️ Gia hạn ngay các khách đã tick', 'xuLyGiaHan')
    .addSeparator()
    .addItem('📄 Cập nhật danh sách Tài liệu', 'capNhatTaiLieu')
    .addItem('🗑️ Xóa TÀI LIỆU đã tích', 'xoaTaiLieuDaTich')
    .addItem('🗑️ Xóa KHÁCH đã tích (cột H)', 'xoaKhachDaTich')
    .addItem('🗑️ Xóa TẤT CẢ khách', 'xoaTatCaKhach')
    .addItem('Cấp quyền xem folder cho khách', 'capQuyenFolderKhachHang')
    .addSeparator()
    .addItem('📱 Tạo lại RIÊNG Form thêm khách', 'taoLaiFormKhach')
    .addItem('📱 Tạo lại RIÊNG Form nạp .md cho bot', 'taoLaiFormMd')
    .addItem('Dọn file trùng trên Drive', 'donFileTrung')
    .addItem('Trang trí lại tất cả', 'trangTriTatCa')
    .addSubMenu(ui.createMenu('⚙️ Cài đặt ban đầu (chạy 1 lần)')
      .addItem('Tách theo khách', 'tachTheoKhach')
      .addItem('Cài tự động hoá toàn bộ', 'caiDatTuDongHoa')
      .addItem('Kiểm tra trigger tự động', 'kiemTraTuDongHoa')
      .addItem('Tạo Google Form cho điện thoại', 'caiDatForm'))
    .addSubMenu(ui.createMenu('💳 Thanh toán tự động')
      .addItem('⚙️ Cài đặt PayOS QR (bot + khóa PayOS)', 'caiDatThanhToanTuDong')
      .addItem('💰 Đổi giá gói học liệu', 'datGiaGoiHocLieu')
      .addItem('📎 Cài ảnh lưu ý gửi khách', 'caiDatTaiLieuHuongDanKhach')
      .addItem('👀 Xem cài đặt hiện tại', 'xemCaiDatThanhToan')
      .addItem('📱 Tạo/lấy lại Form đặt mua (gửi khách)', 'taoLaiFormDatMua')
      .addItem('🔗 Kết nối/kiểm tra webhook PayOS', 'ketNoiWebhookPayOS')
      .addSeparator()
      .addItem('🔁 Gửi lại link Discord cho đơn đang chọn', 'guiLaiLinkDiscordChoDonDangChon')
      .addItem('🧪 Test webhook bằng mã đơn đang chọn', 'testWebhookThanhToanChoDonDangChon'))
    .addSubMenu(ui.createMenu('🎟️ Khách pre-order')
      .addItem('1. Kết nối sheet responses cũ', 'caiDatEmailPreorder')
      .addItem('2. Tạo/lấy lại Form pre-order', 'taoLaiFormPreorder')
      .addItem('🔎 Kiểm tra email pre-order', 'kiemTraEmailPreorder')
      .addItem('🔁 Gửi lại link Discord cho khách đang chọn', 'guiLaiLinkDiscordChoPreorderDangChon'))
    .addToUi();
}

// Simple trigger: chỉ dùng SpreadsheetApp. DriveApp bị Google chặn ở onEdit/onOpen,
// nên mọi việc Drive chạy ở trigger thời gian đã được cấp quyền hoặc qua menu.
function onEdit(e) {
  const sheet = e.range.getSheet();
  const name = sheet.getName();
  if (name === DASHBOARD_NAME && e.range.getA1Notation() === SEARCH_CELL) {
    capNhatDashboard({ skipDrive: true });
  } else if (name === REGISTRY_NAME && e.range.getColumn() === RENEW_COL
             && e.range.getRow() > 1 && e.value === 'TRUE') {
    // KHONG gia han ngay khi tick nua (truoc day chay lien -> nguoi dung chua kip dien
    // cot "So gio" da bi cong 720h mac dinh). Tick chi DANH DAU; xu ly boi menu ♻️
    // hoac trigger hvhnTuDongHoa (toi da 5 phut). Chi nhac huong dan:
    sheet.getParent().toast(
      'Đã đánh dấu gia hạn. Điền "Số giờ gia hạn" (cột I) nếu muốn số giờ tùy ý (trống = 720h = 30 ngày). ' +
      'Hệ thống xử lý trong tối đa 5 phút, hoặc chạy menu HVHN > ♻️ Gia hạn ngay.',
      'HVHN', 8
    );
  } else if (name === REGISTRY_NAME && e.range.getColumn() === DEL_COL
             && e.range.getRow() > 1 && e.value === 'TRUE') {
    sheet.getParent().toast(
      'Đã đánh dấu xóa khách. Hệ thống sẽ xử lý bằng trigger đã cấp quyền trong tối đa 5 phút.',
      'HVHN', 8
    );
  }
}

function ensureDashboard() {
  const ss = SpreadsheetApp.getActiveSpreadsheet();
  let dash = ss.getSheetByName(DASHBOARD_NAME);
  if (!dash) {
    dash = ss.insertSheet(DASHBOARD_NAME, 0);
    capNhatDashboard({ skipDrive: true });
  }
  if (ss.getSheets()[0].getName() !== DASHBOARD_NAME) {
    ss.setActiveSheet(dash);
    ss.moveActiveSheet(1);
  }
}

function ensureStaging() {
  const ss = SpreadsheetApp.getActiveSpreadsheet();
  let staging = ss.getSheetByName(STAGING_NAME);
  if (!staging) {
    staging = ss.insertSheet(STAGING_NAME, 1);
    staging.getRange(1, 1, 1, 4).setValues([['TenNguoiNhan', 'Email', 'TenFile', 'TrangThai']]);
    decorateSheet(staging);
  }
}

// ============ TÁCH TAB GỘP BAN ĐẦU ============

// Chạy 1 lần để tách tab gộp (cột A=TenNguoiNhan) thành 1 tab riêng/khách.
// Sau khi chạy xong, tự xoá tab gộp gốc đi (chuột phải tab > Delete).
function tachTheoKhach() {
  const ss = SpreadsheetApp.getActiveSpreadsheet();
  const master = ss.getSheets().find(s => !isSystemTab(s.getName()));
  if (!master) return;
  const data = master.getDataRange().getValues();
  const header = data[0];
  const groups = {};
  const groupEmails = {};

  for (let i = 1; i < data.length; i++) {
    const name = String(data[i][0] || '').trim();
    const email = String(data[i][1] || '').trim().toLowerCase();
    if (!name) continue;
    if (!_isValidClientTabName(name) || !_isValidEmail(email)) {
      ghiLog('TỪ CHỐI dòng tách tab không hợp lệ', name + ' - ' + email);
      continue;
    }
    if (groupEmails[name] && groupEmails[name] !== email) {
      ghiLog('TỪ CHỐI trùng tên khi tách tab', name + ': ' + email + ' != ' + groupEmails[name]);
      continue;
    }
    groupEmails[name] = email;
    if (!groups[name]) groups[name] = [header];
    const cleanRow = data[i].slice();
    cleanRow[0] = name;
    cleanRow[1] = email;
    groups[name].push(cleanRow);
  }

  Object.keys(groups).forEach(name => {
    let sheet = ss.getSheetByName(name);
    if (!sheet) sheet = ss.insertSheet(name);
    sheet.clearContents();
    sheet.getRange(1, 1, groups[name].length, header.length).setValues(groups[name]);
    decorateSheet(sheet);
  });

  capNhatDashboard();
}

// ============ THÊM MỚI (tài liệu mới HOẶC khách mới) ============

// Dùng chung: gộp mảng dữ liệu [[TenNguoiNhan, Email, TenFile], ...] (có/không header đều được)
// vào đúng tab khách tương ứng, tự tạo tab nếu khách mới, tự bỏ qua dòng trùng file đã có.
// Trả về số dòng thực sự đã thêm.
function mergeRowsIntoClientTabs(ss, rows) {
  let added = 0;
  rows.forEach(row => {
    const [name, email, fileName] = row;
    if (!name || !email || !fileName || name === 'TenNguoiNhan') return; // bỏ qua header/dòng rỗng
    const clientName = String(name).trim();
    const clientEmail = String(email).trim().toLowerCase();
    if (!_isValidClientTabName(clientName) || !_isValidEmail(clientEmail)) {
      ghiLog('TỪ CHỐI dòng khách không hợp lệ', clientName + ' - ' + clientEmail);
      return;
    }

    let sheet = ss.getSheetByName(clientName);
    if (!sheet) {
      sheet = ss.insertSheet(clientName);
      sheet.getRange(1, 1, 1, 4).setValues([['TenNguoiNhan', 'Email', 'TenFile', 'TrangThai']]);
    } else if (sheet.getLastRow() > 1) {
      const storedEmails = sheet.getRange(2, 2, sheet.getLastRow() - 1, 1).getValues()
        .flat().map(v => String(v || '').trim().toLowerCase()).filter(Boolean);
      const canonicalEmail = storedEmails[0] || '';
      if (canonicalEmail && canonicalEmail !== clientEmail) {
        ghiLog('TỪ CHỐI trùng tên khách khác email', clientName + ': ' + clientEmail + ' != ' + canonicalEmail);
        return;
      }
    }

    const lastRow = sheet.getLastRow();
    const existing = lastRow > 1
      ? sheet.getRange(2, 3, lastRow - 1, 1).getValues().flat()
      : [];
    if (existing.includes(fileName)) return; // đã có rồi, khỏi thêm trùng

    sheet.getRange(sheet.getLastRow() + 1, 1, 1, 3).setValues([[clientName, clientEmail, fileName]]);
    added++;
  });
  return added;
}

// TỰ ĐỘNG HOÀN TOÀN: quét folder Source trên Drive tìm mọi file tên "new_rows.csv"
// (Claude hoặc app khác có thể tự tạo file này lên Drive không cần đụng vào Sheet),
// đọc nội dung, gộp vào đúng tab khách, xoá file đã xử lý, rồi phân phối + cập nhật Dashboard.
// Gắn hàm này vào 1 Trigger chạy theo giờ (Triggers > Add Trigger > Time-driven) để tự chạy định kỳ,
// khỏi cần mở Sheet lên bấm gì cả.
function tuDongXuLyFileMoi(options) {
  if (_skipDriveAutomationForUntrustedExecutor('tuDongXuLyFileMoi')) return { skipped: true };
  options = options || {};
  const ss = SpreadsheetApp.getActiveSpreadsheet();
  const sourceFolder = DriveApp.getFolderById(SOURCE_FOLDER_ID);
  // Quét mọi file tên bắt đầu bằng "new_rows" và đuôi .csv (watcher ghi new_rows_<timestamp>.csv)
  const all = sourceFolder.getFiles();
  let mergedAny = false;
  let totalAdded = 0;

  while (all.hasNext()) {
    const file = all.next();
    if (!/^new_rows.*\.csv$/i.test(file.getName())) continue;
    const csvText = file.getBlob().getDataAsString('UTF-8');
    const rows = Utilities.parseCsv(csvText);
    totalAdded += mergeRowsIntoClientTabs(ss, rows);
    file.setTrashed(true); // xử lý xong thì dọn, khỏi lặp lại lần sau
    mergedAny = true;
  }

  if (mergedAny) Logger.log(`Đã gộp ${totalAdded} dòng mới từ new_rows*.csv`);
  // Trigger tổng 5 phút vẫn LUÔN chạy phanPhoi đầy đủ để tự chữa lành + sync dashboard.
  // Làn nhanh 1 phút: nếu có CSV mới thì phân phối ngay nhưng bỏ phần sync nặng;
  // nếu rảnh thì chỉ thử lại các dòng "Không thấy file" (thường do CSV lên Drive trước PDF).
  let distribution = null;
  if (mergedAny || !options.skipDistributionWhenIdle) {
    distribution = phanPhoi({ skipPostSync: !!options.skipPostSync });
  } else if (options.retryMissingWhenIdle) {
    distribution = phanPhoi({ onlyMissing: true, skipPostSync: true, skipDecorate: true });
  }
  return { mergedAny: mergedAny, totalAdded: totalAdded, distribution: distribution };
}

// LÀN NHANH 1 PHÚT: chỉ kéo new_rows*.csv mới từ watcher rồi phân phối ngay.
// Không chạy gia hạn/dọn dẹp/dashboard toàn hệ thống; những việc đó vẫn ở trigger 5 phút.
function hvhnXuLyNhanh() {
  if (_skipDriveAutomationForUntrustedExecutor('hvhnXuLyNhanh')) return;
  const lock = LockService.getScriptLock();
  if (!lock.tryLock(1000)) return;
  try {
    tuDongXuLyFileMoi({ skipDistributionWhenIdle: true, retryMissingWhenIdle: true, skipPostSync: true });
  } catch (e) {
    ghiLog('LỖI làn nhanh', e.message || String(e));
    throw e;
  } finally {
    lock.releaseLock();
  }
}

// TRIGGER 5 PHÚT: gom toàn bộ việc cần tự động hoá vào 1 hàm duy nhất.
// Chạy vô hại nhiều lần: dòng đã Xong bỏ qua, tick đã xử lý thì tự mất/xoá dòng.
function hvhnTuDongHoa() {
  if (_skipDriveAutomationForUntrustedExecutor('hvhnTuDongHoa')) return;
  const lock = LockService.getScriptLock();
  if (!lock.tryLock(1000)) return;
  try {
    tuDongXuLyFileMoi();      // kéo new_rows*.csv + phân phối + sync khách/dashboard
    xuLyGiaHanTuDong();       // tick Gia hạn -> tự gia hạn, nếu cần thì phân phối lại
    xuLyLenhGiaHanDiscordTuDong(); // lệnh gia hạn từ Discord
    kiemTraHetHan();          // quá hạn -> tự gỡ quyền/xoá file
    xuLyLenhDiscordTuDong();  // lệnh xoá từ Discord -> xoá Sheet/Drive thật
    donTaiLieuBotOnlyKhoKhachTuDong(); // tài liệu bot-only lỡ lọt kho khách -> gỡ khỏi Sheet/Drive
    // Xóa khách chạy bằng worker riêng để một trigger sai tài khoản không làm hỏng cả vòng tổng.
    xoaTaiLieuDaTichTuDong(); // tick Xóa tài liệu -> tự xoá, không cần bấm menu
    capNhatTaiLieu();         // tab Tài liệu luôn mới
    canhBaoTrungTenKhach();   // B1: cảnh báo khách trùng tên (khác email) -> tránh dùng chung folder
    capNhatDashboard();       // dashboard luôn mới
  } catch (e) {
    ghiLog('LỖI tự động hoá', e.message || String(e));
    throw e;
  } finally {
    lock.releaseLock();
  }
}

// Chạy 1 lần sau khi dán code: tạo đủ trigger tự động, xoá trigger cũ trùng để tránh chạy lặp.
function _triggerHandlers() {
  return {
    hvhnTuDongHoa: true,
    hvhnXuLyNhanh: true,
    tuDongXuLyFileMoi: true,
    kiemTraHetHan: true,
    xuLyDonPreorderTuDong: true,
    xuLyDonPreorderNhanh: true,
    xuLyXoaKhachDaTichAnToan: true,
  };
}

// Các trigger edit cũ từng gọi thẳng vào luồng xóa/gia hạn có thể đụng DriveApp
// trong ngữ cảnh chưa được cấp quyền. Chỉ trigger thời gian bên trên được phép làm việc Drive.
function _legacyDriveTriggerHandlers() {
  return {
    onEdit: true,
    xoaKhachDaTichTuDong: true,
    xoaTaiLieuDaTichTuDong: true,
    xuLyGiaHanTuDong: true,
  };
}

function _demTriggerTheoHandler() {
  const counts = {};
  ScriptApp.getProjectTriggers().forEach(t => {
    const h = t.getHandlerFunction();
    counts[h] = (counts[h] || 0) + 1;
  });
  return counts;
}

function _coTrigger(handler) {
  const counts = _demTriggerTheoHandler();
  return (counts[handler] || 0) > 0;
}

function _demTriggerLegacyDrive() {
  const legacy = _legacyDriveTriggerHandlers();
  return ScriptApp.getProjectTriggers().filter(t => legacy[t.getHandlerFunction()]).length;
}

function _automationExecutionEmail() {
  try { return String(Session.getEffectiveUser().getEmail() || '').trim().toLowerCase(); }
  catch (e) { return ''; }
}

// Một trigger cũ do tài khoản khác tạo không thể bị xóa từ tài khoản hiện tại.
// Khi phát hiện, nó phải dừng trước khi gọi DriveApp thay vì ném lỗi quyền ra Sheet.
function _skipDriveAutomationForUntrustedExecutor(handler) {
  const props = PropertiesService.getScriptProperties();
  const owner = String(props.getProperty(AUTOMATION_OWNER_PROP) || '').trim().toLowerCase();
  if (!owner) return false; // tương thích khi hệ thống chưa được nâng cấp lần đầu
  const current = _automationExecutionEmail();
  if (current && current === owner) return false;

  const now = Date.now();
  const last = Number(props.getProperty(AUTOMATION_OWNER_SKIP_LOG_PROP) || 0);
  if (now - last > 6 * 60 * 60 * 1000) {
    props.setProperty(AUTOMATION_OWNER_SKIP_LOG_PROP, String(now));
    ghiLog('Bỏ qua trigger Drive sai tài khoản', handler + ' chạy bởi ' + (current || '(không xác định)') + '; cần tài khoản ' + owner);
  }
  return true;
}

function _claimDriveAutomationOwner() {
  const owner = _automationExecutionEmail();
  if (!owner) throw new Error('Không xác định được tài khoản chạy automation.');
  const failures = _kiemTraQuyenDrive();
  if (failures.length) throw new Error(failures.join('\n'));
  const props = PropertiesService.getScriptProperties();
  props.setProperty(AUTOMATION_OWNER_PROP, owner);
  props.deleteProperty(AUTOMATION_OWNER_SKIP_LOG_PROP);
  return owner;
}

function kiemTraTuDongHoa() {
  const counts = _demTriggerTheoHandler();
  const ok = (counts.hvhnTuDongHoa || 0) > 0;
  const msg = [
    ok ? '✅ Trigger tự động chính đang có.' : '⚠️ CHƯA có trigger tự động chính hvhnTuDongHoa.',
    '',
    'Số trigger hiện tại:',
    '- hvhnTuDongHoa: ' + (counts.hvhnTuDongHoa || 0),
    '- hvhnXuLyNhanh: ' + (counts.hvhnXuLyNhanh || 0),
    '- kiemTraHetHan: ' + (counts.kiemTraHetHan || 0),
    '- xuLyDonPreorderTuDong: ' + (counts.xuLyDonPreorderTuDong || 0),
    '- xuLyXoaKhachDaTichAnToan: ' + (counts.xuLyXoaKhachDaTichAnToan || 0),
    '- Trigger edit cũ cần dọn: ' + _demTriggerLegacyDrive(),
    '- Tài khoản Drive automation: ' + (PropertiesService.getScriptProperties().getProperty(AUTOMATION_OWNER_PROP) || '(chưa xác minh)'),
    '',
    ok
      ? 'Nếu dữ liệu vẫn không tự lên, mở Apps Script > Executions để xem lỗi trigger gần nhất.'
      : 'Bấm HVHN > ⚙️ Cài/kiểm tra tự động hoá để cài trigger 5 phút.'
  ].join('\n');
  SpreadsheetApp.getUi().alert(msg);
}

function damBaoTuDongHoa() {
  if (!_coTrigger('hvhnTuDongHoa') || !_coTrigger('hvhnXuLyNhanh')
      || !_coTrigger('kiemTraHetHan') || !_coTrigger('xuLyDonPreorderTuDong')
      || !_coTrigger('xuLyXoaKhachDaTichAnToan')
      || _demTriggerLegacyDrive()) {
    caiDatTuDongHoa();
    return;
  }
  SpreadsheetApp.getActiveSpreadsheet().toast('Trigger đã có: làn nhanh mỗi 1 phút + tự động hoá tổng mỗi 5 phút.');
}

function _caiDatTuDongHoaCore(owner) {
  const ss = SpreadsheetApp.getActiveSpreadsheet();
  const keepHandlers = _triggerHandlers();
  const legacyHandlers = _legacyDriveTriggerHandlers();
  let removedLegacy = 0;
  ScriptApp.getProjectTriggers().forEach(t => {
    const handler = t.getHandlerFunction();
    if (keepHandlers[handler] || legacyHandlers[handler]) {
      if (legacyHandlers[handler]) removedLegacy++;
      ScriptApp.deleteTrigger(t);
    }
  });

  ScriptApp.newTrigger('hvhnTuDongHoa')
    .timeBased()
    .everyMinutes(5)
    .create();

  ScriptApp.newTrigger('hvhnXuLyNhanh')
    .timeBased()
    .everyMinutes(1)
    .create();

  ScriptApp.newTrigger('kiemTraHetHan')
    .timeBased()
    .atHour(1)
    .everyDays(1)
    .create();

  ScriptApp.newTrigger('xuLyDonPreorderTuDong')
    .timeBased()
    .everyMinutes(1)
    .create();

  ScriptApp.newTrigger('xuLyXoaKhachDaTichAnToan')
    .timeBased()
    .everyMinutes(1)
    .create();

  ensureDashboard();
  ensureStaging();
  ensureRegistry();
  capNhatTaiLieu();
  capNhatDashboard();
  ghiLog('Cài tự động hoá', 'chủ Drive=' + owner + '; làn nhanh new_rows, pre-order và xóa khách mỗi 1 phút; hvhnTuDongHoa mỗi 5 phút; kiemTraHetHan hằng ngày 1h; đã dọn ' + removedLegacy + ' trigger cũ');
  ss.toast('Đã cài tự động hoá. File mới, pre-order và xóa khách chờ xử lý mỗi 1 phút.');
  return { owner: owner, removedLegacy: removedLegacy };
}

function caiDatTuDongHoa() {
  return _caiDatTuDongHoaCore(_claimDriveAutomationOwner());
}

function _kiemTraQuyenDrive() {
  const targets = [
    ['Folder Source', SOURCE_FOLDER_ID, true],
    ['Folder phân phối khách', DEST_ROOT_FOLDER_ID, true],
    ['Folder cha HVHN', HVHN_PARENT_FOLDER_ID_EARLY, true],
    ['Then trên web', THEN_TREN_WEB_FILE_ID, false],
  ];
  const failures = [];
  targets.forEach(target => {
    try {
      const item = target[2] ? DriveApp.getFolderById(target[1]) : DriveApp.getFileById(target[1]);
      item.getName(); // buộc Drive xác nhận quyền đọc ngay tại đây
    } catch (e) {
      failures.push(target[0] + ': ' + ((e && e.message) || String(e)));
    }
  });
  return failures;
}

// Chạy từ menu bằng chính tài khoản quản lý để cấp lại quyền Drive và thay trigger cũ.
function suaLoiQuyenDriveVaTrigger() {
  const ui = SpreadsheetApp.getUi();
  try {
    const result = _caiDatTuDongHoaCore(_claimDriveAutomationOwner());
    ui.alert('Đã xác nhận quyền Drive cho ' + result.owner + ' và cài lại trigger. Tick cột "Xóa khách" sẽ được worker an toàn xử lý trong tối đa 1 phút.');
  } catch (e) {
    const account = Session.getEffectiveUser().getEmail() || '(không xác định được email)';
    ui.alert(
      'Chưa thể dùng Drive với tài khoản chạy script: ' + account + '.\n\n'
      + ((e && e.message) || String(e))
      + '\n\nHãy chia sẻ các folder/file trên cho tài khoản này với quyền Editor, rồi chạy lại mục này.'
    );
  }
}

// Entry point private cho Apps Script Execution API: tự nhận tài khoản chủ Drive,
// thay trigger cũ và trả kết quả máy đọc được. Không mở dữ liệu ra bên ngoài.
function tuSuaXoaKhachTuDong() {
  const result = _caiDatTuDongHoaCore(_claimDriveAutomationOwner());
  return JSON.stringify({ owner: result.owner, removedLegacy: result.removedLegacy, deleteWorker: 'every_1_minute' });
}

// Gộp các dòng đang nằm ở tab "Nhập mới" (đường tay dự phòng, khi không dùng new_rows.csv)
// vào đúng tab khách tương ứng, rồi TỰ ĐỘNG chạy phân phối + cập nhật Dashboard luôn.
function themMoiVaPhanPhoi() {
  const ss = SpreadsheetApp.getActiveSpreadsheet();
  const staging = ss.getSheetByName(STAGING_NAME);
  if (!staging) { SpreadsheetApp.getUi().alert('Không tìm thấy tab "' + STAGING_NAME + '"'); return; }

  const rows = staging.getDataRange().getValues();
  const added = mergeRowsIntoClientTabs(ss, rows);

  const lastStagingRow = staging.getLastRow();
  if (lastStagingRow > 1) staging.getRange(2, 1, lastStagingRow - 1, staging.getLastColumn()).clearContent();

  SpreadsheetApp.getActiveSpreadsheet().toast(`Đã thêm ${added} dòng mới, đang phân phối...`);
  phanPhoi();
}

// ============ PHÂN PHỐI ============

// Xử lý MỌI tab có header đúng định dạng (TenNguoiNhan | Email | TenFile | TrangThai),
// trừ Dashboard và tab "Nhập mới". Chạy lại vô hại: dòng đã "Xong" sẽ được bỏ qua.
function phanPhoi(options) {
  options = options || {};
  const ss = SpreadsheetApp.getActiveSpreadsheet();
  const sourceFolder = DriveApp.getFolderById(SOURCE_FOLDER_ID);
  const destRoot = DriveApp.getFolderById(DEST_ROOT_FOLDER_ID);
  let distributed = 0;
  let missing = 0;
  let touchedRows = 0;
  const registryEmailByName = {};
  const registry = ensureRegistry();
  if (registry.getLastRow() > 1) {
    registry.getRange(2, 1, registry.getLastRow() - 1, 2).getValues().forEach(row => {
      const key = String(row[0] || '').trim().toLowerCase();
      const email = String(row[1] || '').trim().toLowerCase();
      if (key && email && !registryEmailByName[key]) registryEmailByName[key] = email;
    });
  }

  ss.getSheets().forEach(sheet => {
    if (isSystemTab(sheet.getName())) return;

    const data = sheet.getDataRange().getValues();
    if (!data.length || data[0][0] !== 'TenNguoiNhan') return;
    const firstClientRow = data.slice(1).find(row => row[0] && row[1]);
    const canonicalEmail = registryEmailByName[sheet.getName().trim().toLowerCase()]
      || (firstClientRow ? String(firstClientRow[1]).trim().toLowerCase() : '');

    const seen = {}; // chống trùng dòng trong cùng 1 tab
    let touchedSheet = false;
    for (let i = 1; i < data.length; i++) {
      const [name, email, fileName, status] = data[i];
      const statusText = String(status || '');
      if (!name || !email || !fileName) continue;
      if (options.onlyMissing && !statusText.startsWith('Không thấy')) continue;
      const cleanEmail = String(email).trim().toLowerCase();
      const cleanName = String(name).trim().toLowerCase();
      const identityMismatch = cleanName !== sheet.getName().trim().toLowerCase()
        || (canonicalEmail && cleanEmail !== canonicalEmail);
      if (identityMismatch) {
        // Chặn cả dòng cũ từng ghi Xong: không cho tên/email xung đột tiếp tục giữ
        // quyền trên folder của khách chuẩn.
        try {
          const folders = destRoot.getFoldersByName(sheet.getName());
          while (folders.hasNext()) {
            const folder = folders.next();
            _removeAccess(folder, cleanEmail);
            const files = folder.getFiles();
            while (files.hasNext()) _removeAccess(files.next(), cleanEmail);
          }
        } catch (revokeError) {
          ghiLog('LỖI gỡ quyền dòng sai định danh', sheet.getName() + ': ' + cleanEmail + ' - '
            + ((revokeError && revokeError.message) || String(revokeError)));
          sheet.getRange(i + 1, 4).setValue('Lỗi gỡ quyền định danh - hệ thống sẽ thử lại');
          touchedSheet = true; touchedRows++;
          continue;
        }
        if (!statusText.startsWith('Lỗi định danh')) {
          ghiLog('CHẶN dòng khách sai định danh', sheet.getName() + ': ' + email + ' / tên dòng=' + name);
        }
        sheet.getRange(i + 1, 4).setValue('Lỗi định danh: tên/email không khớp khách của tab');
        touchedSheet = true; touchedRows++;
        continue;
      }
      if (statusText.startsWith('Xong')) continue;
      if (_isBotOnlyDocFileName(fileName)) {
        sheet.getRange(i + 1, 4).setValue('Bot-only (không phân phối)');
        touchedSheet = true; touchedRows++;
        continue;
      }
      if (seen[fileName]) {         // dòng lặp trong tab -> đánh dấu, không xử lý lại
        sheet.getRange(i + 1, 4).setValue('Trùng (bỏ qua)');
        touchedSheet = true; touchedRows++;
        continue;
      }
      seen[fileName] = true;

      try {
        const destFolder = getOrCreateFolder(destRoot, name);
        _ensureOnlyViewer(destFolder, cleanEmail);

        // IDEMPOTENT: nếu folder đích đã có file cùng tên -> dùng lại, KHÔNG copy thêm bản mới
        let target;
        const existingDest = destFolder.getFilesByName(fileName);
        if (existingDest.hasNext()) {
          target = existingDest.next();
        } else {
          const srcFiles = sourceFolder.getFilesByName(fileName);
          if (!srcFiles.hasNext()) {
            sheet.getRange(i + 1, 4).setValue('Không thấy file: ' + fileName);
            touchedSheet = true; touchedRows++; missing++;
            continue;
          }
          target = srcFiles.next().makeCopy(fileName, destFolder);
        }

        // Chỉ share nếu email CHƯA có quyền -> tránh gửi lại mail thông báo mỗi lần chạy
        _ensureOnlyViewer(target, cleanEmail);
        // Khoá tải/in/copy: nếu Advanced Drive Service chưa bật thì bỏ qua, KHÔNG chặn "Xong"
        try {
          Drive.Files.update({ copyRequiresWriterPermission: true }, target.getId());
        } catch (e2) { /* thiếu Drive service - vẫn share được, chỉ là chưa khoá tải */ }

        sheet.getRange(i + 1, 4).setValue('Xong: ' + target.getUrl());
        touchedSheet = true; touchedRows++; distributed++;
      } catch (e) {
        sheet.getRange(i + 1, 4).setValue('Lỗi: ' + e.message);
        touchedSheet = true; touchedRows++;
      }
    }
    if (touchedSheet && !options.skipDecorate) decorateSheet(sheet);
  });

  if (!options.skipPostSync) {
    dongBoKhachHang();   // cập nhật danh sách khách + set ngày cấp/hết hạn cho khách mới
    capQuyenFolderKhachHangTuDong();
    capNhatDashboard();
  }
  return { distributed: distributed, missing: missing, touchedRows: touchedRows };
}

// ============ DASHBOARD (tổng quan + tìm kiếm) ============

function capNhatDashboard(options) {
  options = options || {};
  const ss = SpreadsheetApp.getActiveSpreadsheet();
  let dash = ss.getSheetByName(DASHBOARD_NAME);
  if (!dash) dash = ss.insertSheet(DASHBOARD_NAME, 0);

  const searchTerm = (dash.getRange(SEARCH_CELL).getValue() || '').toString().trim().toLowerCase();
  // Xóa toàn bộ thân bảng, kể cả khi danh sách từng vượt quá 996 khách.
  if (dash.getMaxRows() > 3) {
    dash.getRange(4, 1, dash.getMaxRows() - 3, dash.getMaxColumns()).clearContent();
  }

  const destRoot = options.skipDrive ? null : DriveApp.getFolderById(DEST_ROOT_FOLDER_ID);
  const rows = [];

  ss.getSheets().forEach(sheet => {
    const name = sheet.getName();
    if (isSystemTab(name)) return;

    const data = sheet.getDataRange().getValues();
    if (!data.length || data[0][0] !== 'TenNguoiNhan') return;

    const body = data.slice(1).filter(r => r[0]);
    if (!body.length) return;

    const email = body[0][1];
    const total = body.length;
    const done = body.filter(r => (r[3] || '').toString().startsWith('Xong')).length;
    const error = body.filter(r =>
      (r[3] || '').toString().startsWith('Lỗi') || (r[3] || '').toString().startsWith('Không thấy')
    ).length;
    const pending = total - done - error;

    let folderUrl = '';
    if (destRoot) {
      const foundFolders = destRoot.getFoldersByName(name);
      if (foundFolders.hasNext()) folderUrl = foundFolders.next().getUrl();
    }

    rows.push({ name, email, total, done, error, pending, sheetId: sheet.getSheetId(), folderUrl });
  });

  const filtered = searchTerm
    ? rows.filter(r => r.name.toLowerCase().includes(searchTerm) || r.email.toLowerCase().includes(searchTerm))
    : rows;

  dash.getRange('A1').setValue('🔎 Tìm khách (tên hoặc email):');
  dash.getRange('D1').setValue('Tổng số khách:');
  dash.getRange('E1').setValue(rows.length);
  dash.getRange('F1').setValue('Tổng lỗi/thiếu file:');
  dash.getRange('G1').setValue(rows.reduce((s, r) => s + r.error, 0));

  const header = ['Tên khách', 'Email', 'Tổng tài liệu', 'Đã xong', 'Lỗi/Thiếu file', 'Chưa chạy', 'Mở tab', 'Folder Drive riêng'];
  dash.getRange(3, 1, 1, header.length).setValues([header]);

  const ssUrl = ss.getUrl();
  const tableRows = filtered.map(r => [
    r.name, r.email, r.total, r.done, r.error, r.pending,
    `=HYPERLINK("${ssUrl}#gid=${r.sheetId}","Mở tab")`,
    r.folderUrl ? `=HYPERLINK("${r.folderUrl}","Mở folder")` : '',
  ]);
  if (tableRows.length) {
    dash.getRange(4, 1, tableRows.length, header.length).setValues(tableRows);
  }

  decorateDashboard(dash, header.length);
  if (!options.skipDrive) xuatTrangThaiSheet();
}

function _fmtDate(value) {
  if (!value) return '';
  const d = new Date(value);
  if (isNaN(d.getTime())) return '';
  return Utilities.formatDate(d, Session.getScriptTimeZone(), 'yyyy-MM-dd');
}

function xuatTrangThaiSheet() {
  try {
    const ss = SpreadsheetApp.getActiveSpreadsheet();
    const reg = ensureRegistry();
    const docsSheet = ss.getSheetByName(DOCS_NAME);
    const clients = [];
    const docs = [];

    const regLast = reg.getLastRow();
    if (regLast >= 2) {
      const rows = reg.getRange(2, 1, regLast - 1, 6).getValues();
      rows.forEach(r => {
        if (!r[0] || !r[1]) return;
        const tab = ss.getSheetByName(r[0]);
        const docCount = tab && tab.getLastRow() > 1 ? tab.getLastRow() - 1 : 0;
        clients.push({
          name: String(r[0]),
          email: String(r[1]).toLowerCase(),
          grant_date: _fmtDate(r[2]),
          expiry_date: _fmtDate(r[3]),
          // days_left suy TỪ mốc hết hạn (cột "Còn lại" nay là chuỗi giờ, không parse được).
          days_left: r[3] ? Math.floor(_hoursBetween(_now(), new Date(r[3])) / 24) : null,
          hours_left: r[3] ? Math.floor(_hoursBetween(_now(), new Date(r[3]))) : null,
          status: String(r[5] || ''),
          doc_count: docCount,
        });
      });
    }

    if (docsSheet && docsSheet.getLastRow() >= 2) {
      const rows = docsSheet.getRange(2, 1, docsSheet.getLastRow() - 1, 2).getValues();
      rows.forEach(r => {
        if (!r[0]) return;
        docs.push({ doc_name: String(r[0]), client_count: Number(r[1] || 0) });
      });
    }

    const parent = DriveApp.getFolderById(HVHN_PARENT_FOLDER_ID_EARLY);
    const folder = getOrCreateFolder(parent, SHEET_STATUS_NAME);
    const payload = JSON.stringify({
      exported_at: new Date().toISOString(),
      clients,
      docs,
    });
    const files = folder.getFilesByName(SHEET_STATUS_FILE);
    if (files.hasNext()) files.next().setContent(payload);
    else folder.createFile(SHEET_STATUS_FILE, payload, MimeType.PLAIN_TEXT);
  } catch (e) {
    ghiLog('LỖI xuất trạng thái Sheet', e.message || String(e));
  }
}

function decorateDashboard(dash, numCols) {
  dash.getRange('A1:H1').setFontWeight('bold').setBackground('#e8eaed');
  dash.getRange('B1').setBackground('#ffffff').setFontWeight('normal').setBorder(true, true, true, true, null, null);
  dash.getRange('D1:G1').setFontWeight('bold');

  const header = dash.getRange(3, 1, 1, numCols);
  header.setBackground('#1a73e8').setFontColor('#ffffff').setFontWeight('bold')
    .setHorizontalAlignment('center').setVerticalAlignment('middle');
  dash.setFrozenRows(3);
  dash.setRowHeight(3, 30);

  dash.autoResizeColumns(1, numCols);
  dash.setColumnWidth(1, 220);
  dash.setColumnWidth(2, 220);

  const lastRow = dash.getLastRow();
  if (lastRow > 3) {
    const body = dash.getRange(4, 1, lastRow - 3, numCols);
    body.setVerticalAlignment('middle').setFontSize(10)
      .setBorder(true, true, true, true, true, true, '#d9d9d9', SpreadsheetApp.BorderStyle.SOLID);
    dash.getBandings().forEach(b => b.remove());
    body.applyRowBanding(SpreadsheetApp.BandingTheme.LIGHT_GREY, true, false);

    const errorRange = dash.getRange(4, 5, lastRow - 3, 1);
    dash.setConditionalFormatRules([
      SpreadsheetApp.newConditionalFormatRule()
        .whenNumberGreaterThan(0).setBackground('#f4cccc').setFontColor('#990000')
        .setRanges([errorRange]).build(),
    ]);
  }

  dash.setTabColor('#0b8043');
}

// ============ TRANG TRÍ TAB KHÁCH ============

function trangTriTatCa() {
  const ss = SpreadsheetApp.getActiveSpreadsheet();
  ss.getSheets().forEach(sheet => {
    if (isSystemTab(sheet.getName())) return;
    const data = sheet.getDataRange().getValues();
    if (data.length && data[0][0] === 'TenNguoiNhan') decorateSheet(sheet);
  });
  capNhatDashboard();
}

function capQuyenFolderKhachHangTuDong() {
  const ss = SpreadsheetApp.getActiveSpreadsheet();
  const destRoot = DriveApp.getFolderById(DEST_ROOT_FOLDER_ID);
  const granted = {};
  const failures = [];

  // Chi cap quyen cho khach CON HAN. Truoc day cap cho moi khach khong xet han ->
  // khach het han (da bi kiemTraHetHan go) bi cap lai o vong phanPhoi ke tiep.
  const now = _now();
  const conHan = {}; // email(lower) -> con han?
  const reg = ensureRegistry();
  if (reg.getLastRow() > 1) {
    reg.getRange(2, 1, reg.getLastRow() - 1, 6).getValues().forEach(r => {
      const email = String(r[1] || '').toLowerCase();
      if (!email) return;
      const expiry = r[3];
      const status = r[5];
      const ok = !!expiry && new Date(expiry).getTime() > now.getTime() && status !== 'Đã gỡ quyền';
      conHan[email] = conHan[email] || ok; // nhieu dong cung email: chi can 1 dong con han
    });
  }

  // Cấp quyền Viewer cho Then trên web theo cùng danh sách email còn hạn.
  // Mở file/quét quyền một lần cho cả lượt chạy, tránh gọi Drive lặp theo từng tài liệu.
  capQuyenThenTrenWebChoKhachConHan(conHan);

  ss.getSheets().forEach(sheet => {
    if (isSystemTab(sheet.getName())) return;
    const data = sheet.getDataRange().getValues();
    if (!data.length || data[0][0] !== 'TenNguoiNhan') return;

    for (let i = 1; i < data.length; i++) {
      const name = data[i][0] || sheet.getName();
      const email = data[i][1];
      if (!name || !email) continue;

      const key = String(name) + '|' + String(email).toLowerCase();
      if (granted[key]) continue;
      granted[key] = true;

      // Khach het han -> KHONG cap lai quyen (kiemTraHetHan lo viec go).
      if (!conHan[String(email).toLowerCase()]) break;

      const folders = destRoot.getFoldersByName(name);
      if (folders.hasNext()) {
        try {
          _ensureOnlyViewer(folders.next(), email);
        } catch (e) {
          const detail = name + ' - ' + email + ': ' + ((e && e.message) || String(e));
          failures.push(detail);
          ghiLog('Chưa cấp được quyền folder khách', detail);
        }
      }
      break;
    }
  });
  return failures;
}

function capQuyenFolderKhachHang() {
  const failures = capQuyenFolderKhachHangTuDong();
  const message = failures.length
    ? ('Đang thử lại quyền Drive cho ' + failures.length + ' khách. Xem tab Nhật ký nếu trạng thái này còn lặp lại.')
    : 'Đã cấp quyền xem folder cho các khách đang có folder Drive.';
  SpreadsheetApp.getActiveSpreadsheet().toast(message, 'HVHN', 8);
}

// ============ QUẢN LÝ GÓI / HẠN DÙNG ============

function ensureRegistry() {
  const ss = SpreadsheetApp.getActiveSpreadsheet();
  let reg = ss.getSheetByName(REGISTRY_NAME);
  const isNew = !reg;
  if (isNew) reg = ss.insertSheet(REGISTRY_NAME, 2);
  // LUÔN ghi lại header 9 cột (nâng cấp tab cũ -> có cột "Số giờ gia hạn")
  reg.getRange(1, 1, 1, 9).setValues([[
    'Tên khách', 'Email', 'Ngày cấp quyền', 'Ngày hết hạn',
    'Còn lại', 'Trạng thái', 'Gia hạn (tick)', 'Xóa khách', 'Số giờ gia hạn (trống=720)',
  ]]);
  if (isNew) decorateRegistry(reg);
  return reg;
}

function _today() {
  const d = new Date();
  return new Date(d.getFullYear(), d.getMonth(), d.getDate());
}

function _addDays(date, days) {
  const d = new Date(date);
  d.setDate(d.getDate() + days);
  return d;
}

function _daysBetween(a, b) {
  return Math.round((b.getTime() - a.getTime()) / 86400000);
}

// Mốc thời gian hiện tại ĐẦY ĐỦ (có giờ) - dùng cho hệ hạn theo giờ.
function _now() { return new Date(); }

function _addHours(date, hours) {
  const d = new Date(date);
  d.setTime(d.getTime() + Math.round(hours * 3600000));
  return d;
}

// Số giờ còn lại (có thể âm) giữa now và mốc hết hạn.
function _hoursBetween(a, b) {
  return (b.getTime() - a.getTime()) / 3600000;
}

// Hiển thị thời lượng còn lại thân thiện: <48h -> "Xh"; >=48h -> "Yn Zh".
function _fmtRemaining(hoursLeft) {
  if (hoursLeft < 0) return 'Hết hạn';
  const h = Math.floor(hoursLeft);
  if (h < 48) return h + 'h';
  const days = Math.floor(h / 24);
  const rem = h % 24;
  return rem ? (days + 'n ' + rem + 'h') : (days + 'n');
}

// Quét các tab khách -> đảm bảo mỗi khách có 1 dòng trong tab "Khách hàng".
// Khách MỚI (chưa có dòng): set Ngày cấp = hôm nay, Ngày hết hạn = hôm nay + SUB_DAYS.
// Khách cũ: giữ nguyên ngày, chỉ tính lại "còn lại" + trạng thái.
function dongBoKhachHang() {
  const ss = SpreadsheetApp.getActiveSpreadsheet();
  const reg = ensureRegistry();

  // đọc registry hiện có -> map theo tên
  const regData = reg.getDataRange().getValues();
  const existing = {}; // name -> {rowIndex, email, grant, expiry, status}
  for (let i = 1; i < regData.length; i++) {
    const nm = regData[i][0];
    if (nm) existing[nm] = { rowIndex: i + 1 };
  }

  // gom khách từ các tab dữ liệu
  const clients = {}; // name -> email
  ss.getSheets().forEach(sheet => {
    if (isSystemTab(sheet.getName())) return;
    const data = sheet.getDataRange().getValues();
    if (!data.length || data[0][0] !== 'TenNguoiNhan') return;
    for (let i = 1; i < data.length; i++) {
      if (data[i][0] && data[i][1] && !clients[data[i][0]]) clients[data[i][0]] = data[i][1];
    }
  });

  const now = _now();
  Object.keys(clients).forEach(name => {
    if (existing[name]) return; // đã có -> giữ nguyên mốc
    const grant = now;
    const expiry = _addHours(now, SUB_HOURS);
    reg.appendRow([name, clients[name], grant, expiry, '', 'Còn hạn', false, false, '']);
    ghiLog('Thêm khách vào danh sách', name + ' - ' + clients[name]);
  });

  capNhatTrangThaiHan(reg);
  decorateRegistry(reg);
}

// Tính lại cột "Còn lại" + "Trạng thái" cho mọi dòng (không đụng 'Đã gỡ quyền').
// CHI GHI cột 5-6 — tuyệt đối không ghi đè cột tick G/H hay cột Số giờ I
// (trước đây ghi cả block 1-7 làm nuốt tick người dùng vừa đặt).
function capNhatTrangThaiHan(reg) {
  const last = reg.getLastRow();
  if (last < 2) return;
  const now = _now();
  const vals = reg.getRange(2, 1, last - 1, 6).getValues();
  const out = [];

  vals.forEach(row => {
    let remaining = row[4];
    let status = row[5];
    const expiry = row[3] ? new Date(row[3]) : null;
    if (!expiry) {
      out.push(['', status]);
      return;
    }
    const hoursLeft = _hoursBetween(now, expiry);
    remaining = _fmtRemaining(hoursLeft);
    if (status !== 'Đã gỡ quyền') { // đã gỡ -> chờ gia hạn, không tự đổi
      if (hoursLeft < 0) status = 'Hết hạn - chờ gỡ';
      else if (hoursLeft <= WARN_HOURS) status = 'Sắp hết';
      else status = 'Còn hạn';
    }
    out.push([remaining, status]);
  });
  reg.getRange(2, 5, out.length, 2).setValues(out);
}

// TRIGGER HẰNG NGÀY: khách quá hạn -> XOÁ file phân phối (bỏ file) + gỡ chia sẻ, đánh 'Đã gỡ quyền'.
function kiemTraHetHan() {
  if (_skipDriveAutomationForUntrustedExecutor('kiemTraHetHan')) return;
  const ss = SpreadsheetApp.getActiveSpreadsheet();
  const reg = ensureRegistry();
  const destRoot = DriveApp.getFolderById(DEST_ROOT_FOLDER_ID);
  const last = reg.getLastRow();
  if (last < 2) { capNhatDashboard(); return; }

  const now = _now();
  const vals = reg.getRange(2, 1, last - 1, 7).getValues();
  let revoked = 0;

  for (let i = 0; i < vals.length; i++) {
    const [name, email, grant, expiry, , status] = vals[i];
    if (!name || !expiry || status === 'Đã gỡ quyền') continue;
    if (new Date(expiry).getTime() > now.getTime()) continue; // còn hạn (so tới GIỜ)

    // Quá hạn: xoá toàn bộ file trong folder khách + reset trạng thái các dòng của khách ở tab
    const folders = destRoot.getFoldersByName(name);
    while (folders.hasNext()) {
      const folder = folders.next();
      _removeAccess(folder, email);
      const files = folder.getFiles();
      while (files.hasNext()) {
        const f = files.next();
        _removeAccess(f, email);
        f.setTrashed(true); // BỎ LUÔN FILE
      }
    }
    // reset cột trạng thái ở tab khách -> để khi gia hạn sẽ phân phối lại
    const tab = ss.getSheetByName(name);
    if (tab) {
      const tData = tab.getDataRange().getValues();
      for (let r = 1; r < tData.length; r++) {
        if (tData[r][0]) tab.getRange(r + 1, 4).setValue('Đã gỡ (hết hạn)');
      }
    }
    if (!_goQuyenThenTrenWebNeuKhongConHan(email, name)) {
      ghiLog('Chờ thử lại gỡ quyền Then trên web', name + ' - ' + email);
      continue;
    }
    ghiLog('Hết hạn - gỡ quyền + xoá file', name + ' - ' + email);
    revoked++;
    // chi ghi o Trang thai cua dong nay — khong ghi de ca block (nuot tick nguoi dung)
    reg.getRange(i + 2, 6).setValue('Đã gỡ quyền');
  }

  capNhatTrangThaiHan(reg);
  decorateRegistry(reg);
  Logger.log(`Đã gỡ quyền ${revoked} khách hết hạn.`);
  capNhatDashboard();
}

// Gia hạn 1 dòng: cộng số GIỜ ở cột I (trống = SUB_HOURS = 720h); nếu đã gỡ -> chuẩn bị phân phối lại.
// runNow=true (từ menu, đủ quyền): chạy phanPhoi ngay. runNow=false (từ trigger): để trigger lo.
function giaHanMotDong(reg, rowIndex, runNow) {
  const row = reg.getRange(rowIndex, 1, 1, HOURS_COL).getValues()[0];
  const [name, email, grant, expiry, , status] = row;
  if (!name) return;

  const rawHours = parseInt(row[HOURS_COL - 1], 10);
  const hours = (rawHours && rawHours > 0) ? rawHours : SUB_HOURS; // ô trống -> gói mặc định
  const now = _now();
  const curExp = expiry ? new Date(expiry) : now;
  const base = curExp.getTime() > now.getTime() ? curExp : now; // còn hạn: nối tiếp; hết hạn: từ bây giờ
  const newExp = _addHours(base, hours);

  reg.getRange(rowIndex, 4).setValue(newExp);
  reg.getRange(rowIndex, RENEW_COL).setValue(false); // bỏ tick
  reg.getRange(rowIndex, HOURS_COL).setValue(''); // xoá ô giờ sau khi dùng
  reg.getRange(rowIndex, 6).setValue('Còn hạn');
  ghiLog('Gia hạn +' + hours + ' giờ', name + ' -> ' + newExp.toLocaleString());

  const ss = SpreadsheetApp.getActiveSpreadsheet();
  if (status === 'Đã gỡ quyền') {
    // đã xoá file -> cần phân phối lại: xoá trạng thái các dòng của khách để phanPhoi copy lại
    const tab = ss.getSheetByName(name);
    if (tab) {
      const tData = tab.getDataRange().getValues();
      for (let r = 1; r < tData.length; r++) {
        if (tData[r][0]) tab.getRange(r + 1, 4).setValue('');
      }
    }
    if (runNow) {
      phanPhoi(); // menu: phân phối lại ngay
      ss.toast(`Đã gia hạn + phân phối lại cho ${name}. Hết hạn: ${newExp.toLocaleString()}`);
    } else {
      ss.toast(`Đã gia hạn ${name}. Tài liệu sẽ được gửi lại trong ít phút.`);
    }
  } else {
    ss.toast(`Đã gia hạn ${name}. Hết hạn mới: ${newExp.toLocaleString()}`);
  }
}

// Quét toàn bộ ô Gia hạn đã tick (dùng khi tick nhiều dòng rồi chạy 1 lần qua menu).
function xuLyGiaHan() {
  const reg = ensureRegistry();
  const last = reg.getLastRow();
  if (last < 2) return;
  const checks = reg.getRange(2, RENEW_COL, last - 1, 1).getValues();
  for (let i = checks.length - 1; i >= 0; i--) {
    if (checks[i][0] === true) giaHanMotDong(reg, i + 2, true); // menu -> chạy ngay
  }
  capNhatTrangThaiHan(reg);
  decorateRegistry(reg);
}

// Bản tự động: xử lý mọi ô Gia hạn đã tick, không gọi UI/menu.
function xuLyGiaHanTuDong() {
  if (_skipDriveAutomationForUntrustedExecutor('xuLyGiaHanTuDong')) return;
  const reg = ensureRegistry();
  const last = reg.getLastRow();
  if (last < 2) return;
  const checks = reg.getRange(2, RENEW_COL, last - 1, 1).getValues();
  let changed = 0;
  for (let i = checks.length - 1; i >= 0; i--) {
    if (checks[i][0] === true) {
      giaHanMotDong(reg, i + 2, false);
      changed++;
    }
  }
  if (changed) {
    capNhatTrangThaiHan(reg);
    decorateRegistry(reg);
    phanPhoi();
    ghiLog('Tự động gia hạn', changed + ' khách');
  }
}

function _discordRenewJobId(parts) {
  const marker = String(parts[3] || '').trim();
  const match = marker.match(/^job:(\d+)$/);
  return match ? match[1] : '';
}

function _discordRenewHistory() {
  try {
    const raw = PropertiesService.getScriptProperties().getProperty(DISCORD_RENEW_HISTORY_PROP);
    const parsed = raw ? JSON.parse(raw) : [];
    return Array.isArray(parsed) ? parsed.map(String) : [];
  } catch (e) {
    return [];
  }
}

function _discordRenewSeen(jobId) {
  return !!jobId && _discordRenewHistory().indexOf(String(jobId)) >= 0;
}

function _discordRenewMark(jobId) {
  if (!jobId) return;
  const history = _discordRenewHistory().filter(id => id !== String(jobId));
  history.push(String(jobId));
  PropertiesService.getScriptProperties().setProperty(
    DISCORD_RENEW_HISTORY_PROP,
    JSON.stringify(history.slice(-300))
  );
}

// Discord -> watcher -> _don_sheet_giahan_khach: mỗi file chứa "email<TAB>số_lượng<TAB>đơn_vị".
// đơn_vị = 'h' (giờ) hoặc 'd' (ngày). Thiếu đơn_vị -> hiểu là NGÀY (tương thích đơn cũ).
function xuLyLenhGiaHanDiscordTuDong() {
  const ss = SpreadsheetApp.getActiveSpreadsheet();
  const reg = ensureRegistry();
  let changed = 0;

  _readTextFiles(SHEET_GIAHAN_KHACH_NAME).forEach(job => {
    try {
      const parts = job.text.replace(',', '\t').split('\t');
      const email = String(parts[0] || '').trim().toLowerCase();
      const amount = Math.max(1, parseInt(parts[1], 10) || 0);
      const unit = String(parts[2] || 'd').trim().toLowerCase();
      const jobId = _discordRenewJobId(parts);
      if (_discordRenewSeen(jobId)) {
        job.file.setTrashed(true);
        return;
      }
      const hours = amount > 0 ? (unit === 'h' ? amount : amount * 24) : SUB_HOURS;
      const found = _timKhachTheoEmail(ss, email);
      if (!found) {
        ghiLog('Discord gia hạn - không tìm thấy', email);
        _discordRenewMark(jobId);
        job.file.setTrashed(true);
        return;
      }

      let rowIndex = found.registryRow;
      if (!rowIndex) {
        reg.appendRow([found.name, found.email || email, _now(), _addHours(_now(), hours), '', 'Còn hạn', false, false, '']);
        rowIndex = reg.getLastRow();
      }

      const row = reg.getRange(rowIndex, 1, 1, 7).getValues()[0];
      const currentExpiry = row[3] ? new Date(row[3]) : _now();
      const base = currentExpiry.getTime() > _now().getTime() ? currentExpiry : _now();
      const newExpiry = _addHours(base, hours);
      reg.getRange(rowIndex, 4).setValue(newExpiry);
      reg.getRange(rowIndex, 6).setValue('Còn hạn');
      reg.getRange(rowIndex, RENEW_COL).setValue(false);

      const tab = ss.getSheetByName(found.name);
      if (tab && row[5] === 'Đã gỡ quyền') {
        const data = tab.getDataRange().getValues();
        for (let r = 1; r < data.length; r++) {
          if (data[r][0]) tab.getRange(r + 1, 4).setValue('');
        }
      }

      ghiLog('Discord gia hạn +' + hours + ' giờ', found.name + ' - ' + (found.email || email));
      _discordRenewMark(jobId);
      job.file.setTrashed(true);
      changed++;
    } catch (e) {
      ghiLog('LỖI Discord gia hạn', job.text + ' -> ' + (e.message || String(e)));
    }
  });

  if (changed) {
    capNhatTrangThaiHan(reg);
    decorateRegistry(reg);
    phanPhoi();
  }
}

function decorateRegistry(reg) {
  const lastCol = HOURS_COL; // 9 cột (đã có "Số giờ gia hạn")
  const lastRow = reg.getLastRow();
  const header = reg.getRange(1, 1, 1, lastCol);
  header.setBackground('#0b8043').setFontColor('#ffffff').setFontWeight('bold')
    .setHorizontalAlignment('center').setVerticalAlignment('middle').setWrap(true);
  reg.getRange(1, DEL_COL).setBackground('#990000');   // ô "Xóa khách" đỏ cảnh báo
  reg.getRange(1, HOURS_COL).setBackground('#1155cc'); // ô "Số giờ gia hạn" xanh dương nhập liệu
  reg.setFrozenRows(1);
  reg.setRowHeight(1, 32);
  reg.setColumnWidth(1, 200);
  reg.setColumnWidth(2, 220);
  reg.setColumnWidth(3, 120);
  reg.setColumnWidth(4, 120);
  reg.setColumnWidth(5, 110);
  reg.setColumnWidth(6, 130);
  reg.setColumnWidth(7, 110);
  reg.setColumnWidth(8, 100);
  reg.setColumnWidth(9, 150);

  if (lastRow > 1) {
    const n = lastRow - 1;
    reg.getRange(2, 3, Math.max(n, reg.getMaxRows() - 1), 2).setNumberFormat('dd/mm/yyyy HH:mm:ss'); // cột ngày, CẢ CỘT (24 GIỜ; hh=12h gây lệch 21:34->9:34)
    reg.getRange(2, HOURS_COL, n, 1).setNumberFormat('0').setHorizontalAlignment('center'); // số giờ nguyên
    reg.getRange(2, RENEW_COL, n, 1).insertCheckboxes();      // ô gia hạn
    reg.getRange(2, DEL_COL, n, 1).insertCheckboxes();        // ô xóa khách

    const body = reg.getRange(2, 1, n, lastCol);
    body.setVerticalAlignment('middle').setFontSize(10)
      .setBorder(true, true, true, true, true, true, '#d9d9d9', SpreadsheetApp.BorderStyle.SOLID);
    reg.getBandings().forEach(b => b.remove());
    body.applyRowBanding(SpreadsheetApp.BandingTheme.LIGHT_GREY, true, false);

    const statusRange = reg.getRange(2, 6, n, 1);
    reg.setConditionalFormatRules([
      SpreadsheetApp.newConditionalFormatRule().whenTextEqualTo('Còn hạn')
        .setBackground('#d9ead3').setFontColor('#274e13').setRanges([statusRange]).build(),
      SpreadsheetApp.newConditionalFormatRule().whenTextEqualTo('Sắp hết')
        .setBackground('#fff2cc').setFontColor('#7f6000').setRanges([statusRange]).build(),
      SpreadsheetApp.newConditionalFormatRule().whenTextStartsWith('Hết hạn')
        .setBackground('#fce5cd').setFontColor('#b45f06').setRanges([statusRange]).build(),
      SpreadsheetApp.newConditionalFormatRule().whenTextEqualTo('Đã gỡ quyền')
        .setBackground('#f4cccc').setFontColor('#990000').setRanges([statusRange]).build(),
    ]);
  }
  reg.setTabColor('#0b8043');
}

function decorateSheet(sheet) {
  const lastCol = sheet.getLastColumn();
  const lastRow = sheet.getLastRow();
  if (lastRow < 1) return;

  const header = sheet.getRange(1, 1, 1, lastCol);
  header.setBackground('#1a73e8').setFontColor('#ffffff').setFontWeight('bold')
    .setFontSize(11).setHorizontalAlignment('center').setVerticalAlignment('middle');
  sheet.setFrozenRows(1);
  sheet.setRowHeight(1, 32);

  sheet.autoResizeColumns(1, lastCol);
  if (lastCol >= 3) sheet.setColumnWidth(3, 380);
  if (lastCol >= 4) sheet.setColumnWidth(4, 320);

  if (lastRow > 1) {
    const body = sheet.getRange(2, 1, lastRow - 1, lastCol);
    body.setVerticalAlignment('middle').setFontSize(10)
      .setBorder(true, true, true, true, true, true, '#d9d9d9', SpreadsheetApp.BorderStyle.SOLID);

    sheet.getBandings().forEach(b => b.remove());
    body.applyRowBanding(SpreadsheetApp.BandingTheme.LIGHT_GREY, true, false);

    if (lastCol >= 4) {
      const statusRange = sheet.getRange(2, 4, lastRow - 1, 1);
      sheet.setConditionalFormatRules([
        SpreadsheetApp.newConditionalFormatRule()
          .whenTextStartsWith('Xong').setBackground('#d9ead3').setFontColor('#274e13')
          .setRanges([statusRange]).build(),
        SpreadsheetApp.newConditionalFormatRule()
          .whenTextStartsWith('Lỗi').setBackground('#f4cccc').setFontColor('#990000')
          .setRanges([statusRange]).build(),
        SpreadsheetApp.newConditionalFormatRule()
          .whenTextStartsWith('Không thấy').setBackground('#fff2cc').setFontColor('#7f6000')
          .setRanges([statusRange]).build(),
      ]);
    }
  }

  sheet.setTabColor('#1a73e8');
}

// Dọn file trùng đã lỡ tạo trong các folder khách (giữ bản CŨ nhất, xoá phần dư).
// Chạy 1 lần qua menu HVHN > "Dọn file trùng trên Drive".
function donFileTrung() {
  const destRoot = DriveApp.getFolderById(DEST_ROOT_FOLDER_ID);
  const clientFolders = destRoot.getFolders();
  let removed = 0;

  while (clientFolders.hasNext()) {
    const folder = clientFolders.next();
    const byName = {};
    const files = folder.getFiles();
    while (files.hasNext()) {
      const f = files.next();
      let n = f.getName();
      // Bản Drive tự đổi tên khi trùng: "... (1).pdf" -> gom về tên gốc để coi là trùng
      const m = n.match(/^(.*?) \(\d+\)(\.pdf)$/i);
      if (m) n = m[1] + m[2];
      (byName[n] = byName[n] || []).push(f);
    }
    Object.keys(byName).forEach(n => {
      const arr = byName[n];
      if (arr.length <= 1) return;
      // giữ bản có tên "sạch" (không có đuôi (N)) và tạo sớm nhất; xoá còn lại
      arr.sort((a, b) => {
        const ca = /\(\d+\)\.pdf$/i.test(a.getName()) ? 1 : 0;
        const cb = /\(\d+\)\.pdf$/i.test(b.getName()) ? 1 : 0;
        if (ca !== cb) return ca - cb;                    // tên sạch lên đầu
        return a.getDateCreated() - b.getDateCreated();   // rồi tới bản cũ nhất
      });
      for (let i = 1; i < arr.length; i++) { arr[i].setTrashed(true); removed++; }
    });
  }

  SpreadsheetApp.getActiveSpreadsheet().toast(`Đã xoá ${removed} file trùng.`);
  capNhatDashboard();
}

function getOrCreateFolder(parent, name) {
  const it = parent.getFoldersByName(name);
  if (it.hasNext()) return it.next();
  return parent.createFolder(name);
}

// Drive trả về email chuẩn của tài khoản Google. Với Gmail, dấu chấm và phần sau
// dấu + ở local-part không đổi hộp thư, nên phải so theo định danh tài khoản.
function _emailIdentityKey(email) {
  const clean = String(email || '').trim().toLowerCase();
  const at = clean.lastIndexOf('@');
  if (at <= 0) return clean;
  let local = clean.substring(0, at);
  let domain = clean.substring(at + 1);
  if (domain === 'gmail.com' || domain === 'googlemail.com') {
    local = local.split('+')[0].replace(/\./g, '');
    domain = 'gmail.com';
  }
  return local + '@' + domain;
}

function _matchingEmailIndex(emails, email) {
  const key = _emailIdentityKey(email);
  for (let i = 0; i < emails.length; i++) {
    if (_emailIdentityKey(emails[i]) === key) return i;
  }
  return -1;
}

// Drive có độ trễ đồng bộ quyền. Kiểm tra lại có giới hạn thay vì coi lần đọc ngay
// sau addViewer là kết quả cuối cùng.
function _viewerGrantConfirmed(item, email) {
  const pauses = [0, 250, 500, 1000, 2000, 4000];
  for (let i = 0; i < pauses.length; i++) {
    if (pauses[i]) Utilities.sleep(pauses[i]);
    const viewers = item.getViewers().map(u => String(u.getEmail() || '').toLowerCase());
    if (_matchingEmailIndex(viewers, email) >= 0) return true;
  }
  return false;
}

// Cap dung 1 quyen cho khach: viewer tren folder/file, khong editor.
function _ensureOnlyViewer(item, email) {
  const lower = String(email || '').trim().toLowerCase();
  if (!_isValidEmail(lower)) throw new Error('Email chia sẻ không hợp lệ: ' + lower);

  let editors = item.getEditors().map(u => String(u.getEmail() || '').toLowerCase());
  let editorIndex = _matchingEmailIndex(editors, lower);
  if (editorIndex >= 0) item.removeEditor(editors[editorIndex]);
  editors = item.getEditors().map(u => String(u.getEmail() || '').toLowerCase());
  if (_matchingEmailIndex(editors, lower) >= 0) {
    throw new Error('Không thể hạ quyền Editor xuống Viewer cho ' + lower);
  }

  let viewers = item.getViewers().map(u => String(u.getEmail() || '').toLowerCase());
  if (_matchingEmailIndex(viewers, lower) < 0) item.addViewer(lower);
  if (!_viewerGrantConfirmed(item, lower)) {
    throw new Error('Drive không xác nhận quyền Viewer cho ' + lower);
  }
  return true;
}

function _removeAccess(item, email) {
  const lower = String(email || '').trim().toLowerCase();
  if (!_isValidEmail(lower)) throw new Error('Email gỡ quyền không hợp lệ: ' + lower);

  let viewers = item.getViewers().map(u => String(u.getEmail() || '').toLowerCase());
  let viewerIndex = _matchingEmailIndex(viewers, lower);
  if (viewerIndex >= 0) item.removeViewer(viewers[viewerIndex]);
  let editors = item.getEditors().map(u => String(u.getEmail() || '').toLowerCase());
  let editorIndex = _matchingEmailIndex(editors, lower);
  if (editorIndex >= 0) item.removeEditor(editors[editorIndex]);

  viewers = item.getViewers().map(u => String(u.getEmail() || '').toLowerCase());
  editors = item.getEditors().map(u => String(u.getEmail() || '').toLowerCase());
  if (_matchingEmailIndex(viewers, lower) >= 0 || _matchingEmailIndex(editors, lower) >= 0) {
    throw new Error('Drive chưa xác nhận gỡ hết quyền của ' + lower);
  }
  return true;
}

// ============ THEN TRÊN WEB: QUYỀN VIEWER THEO GÓI KHÁCH ============

function _thenTrenWebFile() {
  return DriveApp.getFileById(THEN_TREN_WEB_FILE_ID);
}

// Nhận map email(lower) -> còn hạn từ registry, đảm bảo mọi email còn hạn chỉ
// có Viewer (không Editor) trên Then trên web. Lỗi quyền của ứng dụng được ghi
// log nhưng không làm hỏng luồng phân phối học liệu.
function capQuyenThenTrenWebChoKhachConHan(conHan) {
  const emails = Object.keys(conHan || {}).filter(email => conHan[email]);
  if (!emails.length) return;

  try {
    const app = _thenTrenWebFile();
    emails.forEach(email => {
      try {
        _ensureOnlyViewer(app, email);
      } catch (emailError) {
        ghiLog('LỖI cấp quyền Then trên web', email + ' - ' + ((emailError && emailError.message) || String(emailError)));
      }
    });
  } catch (e) {
    ghiLog('LỖI cấp quyền Then trên web', (e && e.message) || String(e));
  }
}

// Chỉ thu quyền nếu email không còn một gói khác đang còn hạn. excludedName
// được dùng khi đang xoá khách nhưng dòng registry của chính khách đó chưa bị xoá.
function _goQuyenThenTrenWebNeuKhongConHan(email, excludedName) {
  const cleanEmail = String(email || '').trim().toLowerCase();
  if (!_isValidEmail(cleanEmail)) return false;

  try {
    const reg = ensureRegistry();
    const now = _now().getTime();
    const last = reg.getLastRow();
    if (last >= 2) {
      const rows = reg.getRange(2, 1, last - 1, 6).getValues();
      const conGoiKhacConHan = rows.some(row => {
        const name = String(row[0] || '');
        const rowEmail = String(row[1] || '').trim().toLowerCase();
        const expiry = row[3] ? new Date(row[3]).getTime() : 0;
        const status = String(row[5] || '');
        return name !== String(excludedName || '') && rowEmail === cleanEmail
          && expiry > now && status !== 'Đã gỡ quyền';
      });
      if (conGoiKhacConHan) return true;
    }
    return _removeAccess(_thenTrenWebFile(), cleanEmail);
  } catch (e) {
    ghiLog('LỖI gỡ quyền Then trên web', cleanEmail + ' - ' + ((e && e.message) || String(e)));
    return false;
  }
}

// ============ XOÁ KHÁCH ============

// Ghi 1 đơn xoá (email khách / tên tài liệu) vào folder để watcher trên PC cập nhật clients.csv / docs/.
function _ghiDonXoa(folderName, content) {
  const parent = DriveApp.getFolderById(HVHN_PARENT_FOLDER_ID_EARLY);
  const folder = getOrCreateFolder(parent, folderName);
  folder.createFile('xoa_' + Date.now() + '_' + Math.floor(Math.random() * 1000) + '.txt',
    content, MimeType.PLAIN_TEXT);
}

// Xoá file phân phối + folder riêng của 1 khách trên Drive.
function _xoaFolderKhachTrenDrive(destRoot, name, email) {
  const folders = destRoot.getFoldersByName(name);
  while (folders.hasNext()) {
    const folder = folders.next();
    _removeAccess(folder, email);
    const files = folder.getFiles();
    while (files.hasNext()) {
      const f = files.next();
      _removeAccess(f, email);
      f.setTrashed(true);
    }
    folder.setTrashed(true);
  }
}

// Xoá hẳn 1 khách: file Drive + folder + tab + dòng registry + báo PC gỡ khỏi clients.csv.
function _xoaMotKhach(ss, destRoot, name, email) {
  _xoaFolderKhachTrenDrive(destRoot, name, email);
  if (!_goQuyenThenTrenWebNeuKhongConHan(email, name)) {
    throw new Error('Chưa gỡ được quyền Then trên web của ' + email + '; hệ thống sẽ thử lại');
  }
  const tab = ss.getSheetByName(name);
  if (tab) ss.deleteSheet(tab);
  if (email) _ghiDonXoa(XOA_KHACH_NAME, email);
  ghiLog('XÓA khách', name + ' - ' + email);
}

function _timKhachTheoEmail(ss, email) {
  const needle = String(email || '').trim().toLowerCase();
  if (!needle) return null;

  const reg = ensureRegistry();
  const regLast = reg.getLastRow();
  if (regLast >= 2) {
    const rows = reg.getRange(2, 1, regLast - 1, 2).getValues();
    for (let i = 0; i < rows.length; i++) {
      if (String(rows[i][1] || '').trim().toLowerCase() === needle) {
        return { name: rows[i][0], email: rows[i][1], registryRow: i + 2 };
      }
    }
  }

  const sheets = ss.getSheets();
  for (let s = 0; s < sheets.length; s++) {
    const sheet = sheets[s];
    if (isSystemTab(sheet.getName())) continue;
    const data = sheet.getDataRange().getValues();
    if (!data.length || data[0][0] !== 'TenNguoiNhan') continue;
    for (let i = 1; i < data.length; i++) {
      if (String(data[i][1] || '').trim().toLowerCase() === needle) {
        return { name: data[i][0] || sheet.getName(), email: data[i][1], registryRow: null };
      }
    }
  }
  return null;
}

function _readTextFiles(folderName) {
  const parent = DriveApp.getFolderById(HVHN_PARENT_FOLDER_ID_EARLY);
  const folder = getOrCreateFolder(parent, folderName);
  const files = folder.getFiles();
  const jobs = [];
  while (files.hasNext()) {
    const file = files.next();
    if (!/\.txt$/i.test(file.getName())) continue;
    jobs.push({ file, text: file.getBlob().getDataAsString('UTF-8').trim() });
  }
  return jobs;
}

// Discord -> watcher -> folder Drive mirror -> Apps Script:
// xoá thật trên Sheet/Drive, không cần bấm menu.
function xuLyLenhDiscordTuDong() {
  const ss = SpreadsheetApp.getActiveSpreadsheet();
  const destRoot = DriveApp.getFolderById(DEST_ROOT_FOLDER_ID);
  const sourceFolder = DriveApp.getFolderById(SOURCE_FOLDER_ID);
  let changed = false;

  _readTextFiles(SHEET_XOA_KHACH_NAME).forEach(job => {
    try {
      const found = _timKhachTheoEmail(ss, job.text);
      if (found && found.name) {
        _xoaMotKhach(ss, destRoot, found.name, found.email || job.text);
        if (found.registryRow) {
          const reg = ensureRegistry();
          if (found.registryRow <= reg.getLastRow()) reg.deleteRow(found.registryRow);
        }
        changed = true;
        ghiLog('Discord xoá khách', found.name + ' - ' + (found.email || job.text));
      } else {
        ghiLog('Discord xoá khách - không tìm thấy', job.text);
      }
      job.file.setTrashed(true);
    } catch (e) {
      ghiLog('LỖI Discord xoá khách', job.text + ' -> ' + (e.message || String(e)));
    }
  });

  _readTextFiles(SHEET_XOA_TAILIEU_NAME).forEach(job => {
    try {
      const docBase = _docBaseFromFileName(job.text);
      if (docBase) {
        _xoaMotTaiLieu(ss, sourceFolder, destRoot, docBase);
        changed = true;
        ghiLog('Discord xoá tài liệu', docBase);
      }
      job.file.setTrashed(true);
    } catch (e) {
      ghiLog('LỖI Discord xoá tài liệu', job.text + ' -> ' + (e.message || String(e)));
    }
  });

  if (changed) {
    decorateRegistry(ensureRegistry());
    capNhatTaiLieu();
    capNhatDashboard();
  }
}

// Menu: xoá các khách đã tick ô "Xóa khách" (cột H) ở tab Khách hàng.
function xoaKhachDaTich() {
  const ui = SpreadsheetApp.getUi();
  const ss = SpreadsheetApp.getActiveSpreadsheet();
  const reg = ensureRegistry();
  const last = reg.getLastRow();
  if (last < 2) { ui.alert('Chưa có khách nào.'); return; }

  const vals = reg.getRange(2, 1, last - 1, DEL_COL).getValues();
  const targets = [];
  vals.forEach((r, i) => { if (r[DEL_COL - 1] === true) targets.push({ row: i + 2, name: r[0], email: r[1] }); });
  if (!targets.length) { ui.alert('Chưa tích ô "Xóa khách" nào ở cột H.'); return; }

  const resp = ui.alert('Xoá ' + targets.length + ' khách?\n\n' + targets.map(t => '• ' + t.name).join('\n')
    + '\n\nSẽ xoá file + gỡ quyền + xoá tab của họ. Không hoàn tác được.',
    ui.ButtonSet.YES_NO);
  if (resp !== ui.Button.YES) return;

  // UI chỉ đánh dấu/yêu cầu xóa. Worker được xác minh quyền Drive sẽ xử lý trong nền.
  // Nhờ vậy tài khoản chỉ có quyền Sheet không thể làm bật lỗi quyền truy cập Drive.
  ghiLog('Xếp hàng xóa khách', targets.length + ' khách; chờ worker Drive được ủy quyền');
  ui.alert('Đã xếp ' + targets.length + ' khách vào hàng xóa an toàn. Hệ thống sẽ xử lý trong tối đa 1 phút.');
}

// Bản tự động: tick cột H là xoá trong vòng chạy trigger kế tiếp, không cần bấm menu.
function xoaKhachDaTichTuDong() {
  if (_skipDriveAutomationForUntrustedExecutor('xoaKhachDaTichTuDong')) return;
  const ss = SpreadsheetApp.getActiveSpreadsheet();
  const reg = ensureRegistry();
  const last = reg.getLastRow();
  if (last < 2) return;

  const vals = reg.getRange(2, 1, last - 1, DEL_COL).getValues();
  const targets = [];
  vals.forEach((r, i) => { if (r[DEL_COL - 1] === true) targets.push({ row: i + 2, name: r[0], email: r[1] }); });
  if (!targets.length) return;

  const destRoot = DriveApp.getFolderById(DEST_ROOT_FOLDER_ID);
  targets.sort((a, b) => b.row - a.row);
  targets.forEach(t => {
    _xoaMotKhach(ss, destRoot, t.name, t.email);
    reg.deleteRow(t.row);
  });
  decorateRegistry(reg);
  capNhatDashboard();
  ghiLog('Tự động xoá khách đã tick', targets.length + ' khách');
}

// Worker riêng cho hàng xóa khách. Chạy tách khỏi worker tổng để lỗi Drive không chặn
// các luồng phân phối, gia hạn hay pre-order.
function xuLyXoaKhachDaTichAnToan() {
  if (_skipDriveAutomationForUntrustedExecutor('xuLyXoaKhachDaTichAnToan')) return;
  try {
    xoaKhachDaTichTuDong();
  } catch (e) {
    ghiLog('LỖI worker xóa khách', (e && e.message) || String(e));
  }
}

// Menu: xoá TẤT CẢ khách (dọn sạch để bắt đầu lại). Xác nhận 2 lớp.
function xoaTatCaKhach() {
  const ui = SpreadsheetApp.getUi();
  const ss = SpreadsheetApp.getActiveSpreadsheet();
  const r1 = ui.alert('XÓA TẤT CẢ KHÁCH?', 'Xoá toàn bộ file phân phối, folder, tab của MỌI khách. Không hoàn tác.', ui.ButtonSet.YES_NO);
  if (r1 !== ui.Button.YES) return;
  const r2 = ui.prompt('Xác nhận lần 2', 'Gõ đúng chữ XOA rồi bấm OK để tiếp tục:', ui.ButtonSet.OK_CANCEL);
  if (r2.getSelectedButton() !== ui.Button.OK || r2.getResponseText().trim().toUpperCase() !== 'XOA') return;

  const destRoot = DriveApp.getFolderById(DEST_ROOT_FOLDER_ID);
  const reg = ensureRegistry();
  const last = reg.getLastRow();
  const vals = last >= 2 ? reg.getRange(2, 1, last - 1, 2).getValues() : [];
  const emails = {};
  vals.forEach(row => {
    const email = String(row[1] || '').trim().toLowerCase();
    if (email) emails[email] = true;
  });
  vals.forEach(row => { if (row[0]) _xoaMotKhach(ss, destRoot, row[0], row[1]); });
  // Thu hồi dứt điểm quyền app cho cả email trước khi xóa registry. Nếu Drive lỗi,
  // giữ registry để lần chạy sau còn đủ dữ liệu thử lại.
  try {
    const thenFile = _thenTrenWebFile();
    Object.keys(emails).forEach(email => _removeAccess(thenFile, email));
  } catch (e) {
    ghiLog('LỖI gỡ quyền Then trên web khi xóa tất cả', (e && e.message) || String(e));
    ui.alert('Chưa gỡ hết quyền Then trên web. Danh sách khách được giữ lại để bạn chạy lại thao tác.');
    return;
  }
  if (last >= 2) reg.deleteRows(2, last - 1);
  decorateRegistry(reg);
  capNhatDashboard();
  ui.alert('Đã xoá toàn bộ khách.');
}

// ============ TAB DANH SÁCH TÀI LIỆU + XOÁ TÀI LIỆU ============

// Lấy tên tài liệu gốc từ tên file "{tenKhach}__{tenTaiLieu}.pdf"
function _docBaseFromFileName(fileName) {
  const idx = fileName.indexOf('__');
  let base = idx >= 0 ? fileName.substring(idx + 2) : fileName;
  return base.replace(/\.pdf$/i, '');
}

function _isBotOnlyDocFileName(fileName) {
  const base = _docBaseFromFileName(String(fileName || '')).toLowerCase();
  return BOT_ONLY_DOC_PREFIXES.some(prefix => base.indexOf(prefix.toLowerCase()) === 0);
}

function _xoaFileTheoTenTrongFolder(folder, predicate) {
  const files = folder.getFiles();
  let removed = 0;
  while (files.hasNext()) {
    const f = files.next();
    if (predicate(f.getName())) {
      f.setTrashed(true);
      removed++;
    }
  }
  return removed;
}

function donTaiLieuBotOnlyKhoKhachTuDong() {
  const ss = SpreadsheetApp.getActiveSpreadsheet();
  const sourceFolder = DriveApp.getFolderById(SOURCE_FOLDER_ID);
  const destRoot = DriveApp.getFolderById(DEST_ROOT_FOLDER_ID);
  let removedRows = 0;
  let removedFiles = 0;

  ss.getSheets().forEach(sheet => {
    if (isSystemTab(sheet.getName())) return;
    const data = sheet.getDataRange().getValues();
    if (!data.length || data[0][0] !== 'TenNguoiNhan') return;

    for (let i = data.length - 1; i >= 1; i--) {
      const fn = data[i][2];
      if (!fn || !_isBotOnlyDocFileName(fn)) continue;
      const folders = destRoot.getFoldersByName(sheet.getName());
      while (folders.hasNext()) {
        const folder = folders.next();
        const df = folder.getFilesByName(String(fn));
        while (df.hasNext()) { df.next().setTrashed(true); removedFiles++; }
      }
      sheet.deleteRow(i + 1);
      removedRows++;
    }
  });

  removedFiles += _xoaFileTheoTenTrongFolder(sourceFolder, _isBotOnlyDocFileName);
  if (removedRows || removedFiles) {
    ghiLog('Dọn tài liệu bot-only khỏi kho khách', removedRows + ' dòng; ' + removedFiles + ' file');
    capNhatTaiLieu();
    capNhatDashboard();
  }
}

function donTaiLieuBotOnlyKhoKhach() {
  donTaiLieuBotOnlyKhoKhachTuDong();
  SpreadsheetApp.getUi().alert('Đã dọn các tài liệu bot-only (ví dụ tên bắt đầu bằng "discord") khỏi kho khách.');
}

// Menu/nút: dựng tab "Tài liệu" — mỗi tài liệu 1 dòng, kèm số khách đang có + ô tick Xóa.
function capNhatTaiLieu() {
  const ss = SpreadsheetApp.getActiveSpreadsheet();
  let sh = ss.getSheetByName(DOCS_NAME);
  if (!sh) sh = ss.insertSheet(DOCS_NAME);

  const count = {}; // docBase -> số khách
  ss.getSheets().forEach(sheet => {
    if (isSystemTab(sheet.getName())) return;
    const data = sheet.getDataRange().getValues();
    if (!data.length || data[0][0] !== 'TenNguoiNhan') return;
    const seen = {};
    for (let i = 1; i < data.length; i++) {
      const fn = data[i][2];
      if (!fn) continue;
      const b = _docBaseFromFileName(String(fn));
      if (seen[b]) continue; // 1 khách tính 1 lần / tài liệu
      seen[b] = true;
      count[b] = (count[b] || 0) + 1;
    }
  });

  // GIỮ tick "Xóa tài liệu" đang có (theo tên tài liệu) để rebuild không nuốt tick người dùng.
  const oldTicks = {};
  if (sh.getLastRow() > 1) {
    sh.getRange(2, 1, sh.getLastRow() - 1, 3).getValues().forEach(r => {
      if (r[0]) oldTicks[String(r[0])] = r[2] === true;
    });
  }

  sh.clear();
  sh.getRange(1, 1, 1, 3).setValues([['Tên tài liệu', 'Số khách đang có', 'Xóa tài liệu']]);
  const names = Object.keys(count).sort();
  if (names.length) {
    sh.getRange(2, 1, names.length, 2).setValues(names.map(n => [n, count[n]]));
    sh.getRange(2, 3, names.length, 1).insertCheckboxes();
    const ticks = names.map(n => [oldTicks[n] === true]);
    if (ticks.some(t => t[0])) sh.getRange(2, 3, names.length, 1).setValues(ticks);
  }

  // trang trí
  sh.getRange(1, 1, 1, 3).setBackground('#1a73e8').setFontColor('#fff').setFontWeight('bold')
    .setHorizontalAlignment('center');
  sh.getRange(1, 3).setBackground('#990000');
  sh.setFrozenRows(1);
  sh.setColumnWidth(1, 420); sh.setColumnWidth(2, 140); sh.setColumnWidth(3, 120);
  if (names.length) {
    const body = sh.getRange(2, 1, names.length, 3);
    body.setBorder(true, true, true, true, true, true, '#d9d9d9', SpreadsheetApp.BorderStyle.SOLID);
    sh.getBandings().forEach(b => b.remove());
    body.applyRowBanding(SpreadsheetApp.BandingTheme.LIGHT_GREY, true, false);
  }
  sh.setTabColor('#1a73e8');
  SpreadsheetApp.getActiveSpreadsheet().toast('Đã cập nhật danh sách tài liệu (' + names.length + ').');
}

// Xoá 1 tài liệu khỏi MỌI khách: dòng ở tab khách + file phân phối + file gốc watermark + báo PC gỡ docs/.
function _xoaMotTaiLieu(ss, sourceFolder, destRoot, docBase) {
  ss.getSheets().forEach(sheet => {
    if (isSystemTab(sheet.getName())) return;
    const data = sheet.getDataRange().getValues();
    if (!data.length || data[0][0] !== 'TenNguoiNhan') return;
    const clientName = data[1] ? data[1][0] : sheet.getName();
    // xoá dòng khớp tài liệu (từ dưới lên)
    for (let i = data.length - 1; i >= 1; i--) {
      const fn = data[i][2];
      if (fn && _docBaseFromFileName(String(fn)) === docBase) {
        // xoá file phân phối trong folder khách
        const folders = destRoot.getFoldersByName(sheet.getName());
        while (folders.hasNext()) {
          const df = folders.next().getFilesByName(String(fn));
          while (df.hasNext()) df.next().setTrashed(true);
        }
        sheet.deleteRow(i + 1);
      }
    }
  });
  // xoá file gốc watermark trong folder Source (mọi khách): "*__{docBase}.pdf"
  const sf = sourceFolder.getFiles();
  while (sf.hasNext()) {
    const f = sf.next();
    if (_docBaseFromFileName(f.getName()) === docBase && /\.pdf$/i.test(f.getName())) f.setTrashed(true);
  }
  _ghiDonXoa(XOA_TAILIEU_NAME, docBase); // báo PC xoá docs/{docBase}.pdf
  ghiLog('XÓA tài liệu', docBase);
}

// Menu: xoá các tài liệu đã tick ở tab "Tài liệu".
function xoaTaiLieuDaTich() {
  const ui = SpreadsheetApp.getUi();
  const ss = SpreadsheetApp.getActiveSpreadsheet();
  const sh = ss.getSheetByName(DOCS_NAME);
  if (!sh || sh.getLastRow() < 2) { ui.alert('Chưa có tài liệu. Chạy "Cập nhật danh sách Tài liệu" trước.'); return; }

  const vals = sh.getRange(2, 1, sh.getLastRow() - 1, 3).getValues();
  const targets = vals.filter(r => r[2] === true).map(r => r[0]);
  if (!targets.length) { ui.alert('Chưa tích ô "Xóa tài liệu" nào.'); return; }

  const resp = ui.alert('Xoá ' + targets.length + ' tài liệu khỏi TẤT CẢ khách?\n\n'
    + targets.map(t => '• ' + t).join('\n') + '\n\nKhông hoàn tác được.', ui.ButtonSet.YES_NO);
  if (resp !== ui.Button.YES) return;

  const sourceFolder = DriveApp.getFolderById(SOURCE_FOLDER_ID);
  const destRoot = DriveApp.getFolderById(DEST_ROOT_FOLDER_ID);
  targets.forEach(docBase => _xoaMotTaiLieu(ss, sourceFolder, destRoot, docBase));
  capNhatTaiLieu();
  capNhatDashboard();
  ui.alert('Đã xoá ' + targets.length + ' tài liệu.');
}

// Bản tự động: tick cột "Xóa tài liệu" là xoá trong vòng chạy trigger kế tiếp.
function xoaTaiLieuDaTichTuDong() {
  if (_skipDriveAutomationForUntrustedExecutor('xoaTaiLieuDaTichTuDong')) return;
  const ss = SpreadsheetApp.getActiveSpreadsheet();
  const sh = ss.getSheetByName(DOCS_NAME);
  if (!sh || sh.getLastRow() < 2) return;

  const vals = sh.getRange(2, 1, sh.getLastRow() - 1, 3).getValues();
  const targets = vals.filter(r => r[2] === true).map(r => r[0]);
  if (!targets.length) return;

  const sourceFolder = DriveApp.getFolderById(SOURCE_FOLDER_ID);
  const destRoot = DriveApp.getFolderById(DEST_ROOT_FOLDER_ID);
  targets.forEach(docBase => _xoaMotTaiLieu(ss, sourceFolder, destRoot, docBase));
  capNhatTaiLieu();
  capNhatDashboard();
  ghiLog('Tự động xoá tài liệu đã tick', targets.length + ' tài liệu');
}

// ============ GOOGLE FORM CHO ĐIỆN THOẠI ============
// Chạy caiDatForm() 1 LẦN qua menu để tạo 2 Form + folder đơn hàng + trigger nhận đơn.
// Sau đó gửi 2 link Form cho 3 quản lý — họ điền từ điện thoại là xong.

const HVHN_PARENT_FOLDER_ID = '10RjJY_DVmI8Ys-tV1k_HzMLIIFCvbRWs'; // folder cha "TÀI LIỆU ĐỘC QUYỀN HVHN"
const JOBS_KHACH_NAME = '_don_them_khach';      // nơi ghi đơn thêm khách (watcher PC đọc)
const INCOMING_DOCS_NAME = '_don_them_tai_lieu'; // nơi chứa PDF tài liệu mới (watcher PC đọc)
const BOT_DOCS_FORM_NAME = '_don_them_tai_lieu_bot'; // PDF chỉ nạp cho AI/bot, không phân phối khách
const INCOMING_BOT_MD_NAME = '_don_them_tai_lieu_bot_md'; // .md chỉ nạp cho AI/bot, không phân phối khách

// Mở form theo ID nếu form còn sống (không bị xoá/thùng rác); ngược lại trả null.
function _openFormIfAlive(id) {
  if (!id) return null;
  try {
    const form = FormApp.openById(id);
    if (DriveApp.getFileById(id).isTrashed()) return null; // đã xoá -> coi như không có
    return form;
  } catch (e) { return null; }
}

function _emailTextValidation() {
  return FormApp.createTextValidation()
    .requireTextIsEmail()
    .setHelpText('Hãy nhập đúng địa chỉ email.')
    .build();
}

function _isValidPersonName(name) {
  const clean = String(name || '').trim();
  return !!clean && clean.length <= 120 && !/[\x00-\x1f\x7f]/.test(clean)
    && !/^[=+\-@]/.test(clean);
}

function _isValidEmail(email) {
  const clean = String(email || '').trim();
  if (!clean || clean.length > 254 || /^[=+\-@]/.test(clean)) return false;
  const parts = clean.split('@');
  if (parts.length !== 2) return false;
  const local = parts[0];
  const labels = parts[1].toLowerCase().split('.');
  if (!local || local.length > 64 || local.startsWith('.') || local.endsWith('.')
      || local.indexOf('..') >= 0 || !/^[A-Za-z0-9.!#$%&'*+\/=?^_`{|}~-]+$/.test(local)
      || labels.length < 2) return false;
  return labels.every(label => !!label && label.length <= 63
    && /^[a-z0-9](?:[a-z0-9-]*[a-z0-9])?$/i.test(label));
}

function _ensureFormEmailValidation(form) {
  form.getItems(FormApp.ItemType.TEXT).forEach(item => {
    const textItem = item.asTextItem();
    if (textItem.getTitle().toLowerCase().indexOf('email') >= 0) {
      textItem.setValidation(_emailTextValidation());
    }
  });
}

function _ensureSingleFormTrigger(handler, form) {
  let kept = false;
  ScriptApp.getProjectTriggers().forEach(trigger => {
    if (trigger.getHandlerFunction() !== handler) return;
    let sameForm = false;
    try { sameForm = trigger.getTriggerSourceId() === form.getId(); } catch (e) {}
    if (sameForm && !kept) kept = true;
    else ScriptApp.deleteTrigger(trigger);
  });
  if (!kept) ScriptApp.newTrigger(handler).forForm(form).onFormSubmit().create();
}

// Tạo mới form THÊM KHÁCH + gắn trigger + lưu ID. Trả về form.
function _taoFormKhach(props) {
  const form = FormApp.create('HVHN — Thêm khách mới');
  form.setDescription('Nhập họ tên và email học viên để cấp tài liệu (gói 1 tháng). Hệ thống tự đóng dấu + gửi tài liệu.');
  form.addTextItem().setTitle('Họ và tên học viên').setRequired(true);
  form.addTextItem().setTitle('Email (Gmail) học viên').setRequired(true).setValidation(_emailTextValidation());
  form.setConfirmationMessage('Đã nhận! Tài liệu sẽ được gửi sau khi hệ thống xử lý.');
  form.setAcceptingResponses(true);
  _ensureSingleFormTrigger('xuLyFormKhach', form);
  props.setProperty('FORM_KHACH_ID', form.getId());
  return form;
}

function _taoFormBot(props) {
  const form = FormApp.create('HVHN — Nạp tài liệu cho bot AI');
  form.setDescription('Tải lên PDF để bot AI đọc làm căn cứ trả lời. Tài liệu này KHÔNG phân phối cho khách.');
  form.addTextItem().setTitle('Tên tài liệu (tuỳ chọn, để trống sẽ dùng tên file)');
  // Apps Script không tạo được câu hỏi upload file bằng code -> thêm tay 1 lần trong link sửa form.
  form.setConfirmationMessage('Đã nhận file. Bot sẽ đọc sau khi watcher trên PC xử lý.');
  form.setAcceptingResponses(true);
  _ensureSingleFormTrigger('xuLyFormTaiLieuBot', form);
  props.setProperty('FORM_BOT_TL_ID', form.getId());
  return form;
}

// Menu: tạo lại RIÊNG form thêm khách (khi lỡ xoá/hỏng), không đụng form tài liệu.
function taoLaiFormKhach() {
  const props = PropertiesService.getScriptProperties();
  const oldForm = _openFormIfAlive(props.getProperty('FORM_KHACH_ID'));
  if (oldForm) oldForm.setAcceptingResponses(false);
  const form = _taoFormKhach(props);
  const msg = 'Đã tạo lại Form THÊM KHÁCH. Gửi link này cho quản lý:\n\n' + form.getPublishedUrl();
  Logger.log(msg);
  SpreadsheetApp.getUi().alert(msg);
}

function taoLaiFormBot() {
  const props = PropertiesService.getScriptProperties();
  const oldForm = _openFormIfAlive(props.getProperty('FORM_BOT_TL_ID'));
  if (oldForm) oldForm.setAcceptingResponses(false);
  const form = _taoFormBot(props);
  const msg = 'Đã tạo lại Form NẠP TÀI LIỆU CHO BOT.\n\n'
    + 'Cần mở link SỬA rồi thêm tay 1 câu "Tải tệp lên" bắt buộc.\n\n'
    + 'Link SỬA: ' + form.getEditUrl() + '\n\n'
    + 'Link GỬI quản lý: ' + form.getPublishedUrl();
  Logger.log(msg);
  SpreadsheetApp.getUi().alert(msg);
}

// Tạo mới form NẠP .MD CHO BOT + gắn trigger + lưu ID. Trả về form.
function _taoFormMd(props) {
  const form = FormApp.create('HVHN — Nạp tài liệu .md cho bot');
  form.setDescription('Tải lên file .md để bot AI đọc làm căn cứ trả lời. Tài liệu này KHÔNG phân phối cho khách.\n\n'
    + 'Cứ soạn theo cách trình bày quen thuộc của bạn — bot tự nhận diện đề mục, trích dẫn, tác giả, '
    + 'đoạn văn ở nhiều định dạng khác nhau. Vài mẹo giúp bot hiểu chính xác hơn (không bắt buộc):\n'
    + '• Dùng đề mục (#, ##…) để tách ý sẽ giúp tra cứu gọn hơn.\n'
    + '• Trích dẫn kèm tác giả ghi liền nhau, ví dụ: > "…nội dung…" — Tác giả.\n'
    + '• Thơ, danh sách, văn xuôi… đều đọc được, không cần ép về một khuôn.');
  form.addTextItem().setTitle('Tên tài liệu (tuỳ chọn, để trống sẽ dùng tên file)');
  form.addTextItem().setTitle('Tác giả tài liệu (nếu là sách/bài của MỘT người — vd Chu Văn Sơn; để trống nếu là tuyển tập nhiều tác giả)');
  // Apps Script không tạo được câu hỏi upload file bằng code -> thêm tay 1 lần trong link sửa form.
  form.setConfirmationMessage('Đã nhận file. Bot sẽ đọc sau khi watcher trên PC xử lý.');
  form.setAcceptingResponses(true);
  _ensureSingleFormTrigger('xuLyFormMd', form);
  props.setProperty('FORM_MD_ID', form.getId());
  return form;
}

// Menu: tạo lại RIÊNG form nạp .md cho bot (khi lỡ xoá/hỏng), không đụng các form khác.
function taoLaiFormMd() {
  const props = PropertiesService.getScriptProperties();
  const oldForm = _openFormIfAlive(props.getProperty('FORM_MD_ID'));
  if (oldForm) oldForm.setAcceptingResponses(false);
  const form = _taoFormMd(props);
  const msg = 'Đã tạo lại Form NẠP .MD CHO BOT.\n\n'
    + 'Cần mở link SỬA rồi thêm tay 1 câu "Tải tệp lên" bắt buộc (chỉ nhận .md).\n\n'
    + 'Link SỬA: ' + form.getEditUrl() + '\n\n'
    + 'Link GỬI quản lý: ' + form.getPublishedUrl();
  Logger.log(msg);
  SpreadsheetApp.getUi().alert(msg);
}

function caiDatForm() {
  const ui = SpreadsheetApp.getUi();
  const parent = DriveApp.getFolderById(HVHN_PARENT_FOLDER_ID);
  const jobsFolder = getOrCreateFolder(parent, JOBS_KHACH_NAME);
  const incomingFolder = getOrCreateFolder(parent, INCOMING_DOCS_NAME);
  const botDocsFolder = getOrCreateFolder(parent, BOT_DOCS_FORM_NAME);

  const props = PropertiesService.getScriptProperties();

  // --- Form 1: THÊM KHÁCH ---
  let formKhach = _openFormIfAlive(props.getProperty('FORM_KHACH_ID'));
  if (!formKhach) formKhach = _taoFormKhach(props);
  _ensureFormEmailValidation(formKhach);
  _ensureSingleFormTrigger('xuLyFormKhach', formKhach);

  // --- Form 2: THÊM TÀI LIỆU ---
  let formTL = _openFormIfAlive(props.getProperty('FORM_TL_ID'));
  if (!formTL) {
    formTL = FormApp.create('HVHN — Thêm tài liệu mới');
    formTL.setDescription('Tải lên file PDF tài liệu mới. Hệ thống tự đóng dấu tên từng khách + gửi cho TẤT CẢ khách đang còn hạn.');
    formTL.addTextItem().setTitle('Tên tài liệu (tuỳ chọn, để trống sẽ dùng tên file)');
    // LƯU Ý: Apps Script KHÔNG tạo được câu hỏi upload file bằng code -> phải thêm tay 1 lần.
    formTL.setConfirmationMessage('Đã nhận file! Hệ thống sẽ đóng dấu và phân phối.');
    formTL.setAcceptingResponses(true);
    _ensureSingleFormTrigger('xuLyFormTaiLieu', formTL);
    props.setProperty('FORM_TL_ID', formTL.getId());
  }
  _ensureSingleFormTrigger('xuLyFormTaiLieu', formTL);

  // --- Form 3: NẠP TÀI LIỆU CHO BOT AI ---
  let formBotTL = _openFormIfAlive(props.getProperty('FORM_BOT_TL_ID'));
  if (!formBotTL) formBotTL = _taoFormBot(props);
  _ensureSingleFormTrigger('xuLyFormTaiLieuBot', formBotTL);

  props.setProperty('JOBS_KHACH_ID', jobsFolder.getId());
  props.setProperty('INCOMING_DOCS_ID', incomingFolder.getId());
  props.setProperty('BOT_DOCS_FORM_ID', botDocsFolder.getId());
  // Cài luôn trigger tự động khi cài Form, tránh tình trạng watcher đã đẩy new_rows*.csv
  // lên Drive nhưng Sheet chỉ cập nhật sau khi chủ bấm menu thủ công.
  caiDatTuDongHoa();

  const msg = 'ĐÃ TẠO XONG.\n\n'
    + '① Form THÊM KHÁCH (gửi quản lý ngay được):\n' + formKhach.getPublishedUrl() + '\n\n'
    + '② Form THÊM TÀI LIỆU — CẦN THÊM TAY 1 CÂU UPLOAD:\n'
    + 'Mở link SỬA form dưới đây → bấm (+) thêm câu hỏi → chọn kiểu "Tải tệp lên" (File upload) '
    + '→ đặt tên "File PDF tài liệu" → bật Bắt buộc. Xong mới gửi link cho quản lý.\n'
    + 'Link SỬA: ' + formTL.getEditUrl() + '\n'
    + 'Link GỬI quản lý (sau khi thêm câu upload): ' + formTL.getPublishedUrl() + '\n\n'
    + '③ Form NẠP TÀI LIỆU CHO BOT AI — CẦN THÊM TAY 1 CÂU UPLOAD:\n'
    + 'Link SỬA: ' + formBotTL.getEditUrl() + '\n'
    + 'Link GỬI quản lý (sau khi thêm câu upload): ' + formBotTL.getPublishedUrl();
  Logger.log(msg);
  ui.alert(msg);
}

// Handler khi có người submit Form "Thêm khách": ghi 1 file đơn .txt vào folder _don_them_khach.
function xuLyFormKhach(e) {
  if (!_formAllowed(e)) return;
  const props = PropertiesService.getScriptProperties();
  const jobsFolder = DriveApp.getFolderById(props.getProperty('JOBS_KHACH_ID'));
  let name = '', email = '';
  e.response.getItemResponses().forEach(it => {
    const t = it.getItem().getTitle().toLowerCase();
    if (t.indexOf('tên') >= 0) name = String(it.getResponse()).trim();
    else if (t.indexOf('email') >= 0) email = String(it.getResponse()).trim();
  });
  if (!_isValidPersonName(name) || !_isValidEmail(email)) {
    ghiLog('Từ chối Form thêm khách (tên/email không hợp lệ)', name + ' - ' + email);
    return;
  }
  jobsFolder.createFile('khach_' + Date.now() + '.txt', name + '\t' + email, MimeType.PLAIN_TEXT);
}

// Handler khi có người submit Form "Thêm tài liệu": copy file PDF vào folder _don_them_tai_lieu.
function xuLyFormTaiLieu(e) {
  if (!_formAllowed(e)) return;
  const props = PropertiesService.getScriptProperties();
  const incoming = DriveApp.getFolderById(props.getProperty('INCOMING_DOCS_ID'));
  let tenTL = '';
  let fileIds = [];
  e.response.getItemResponses().forEach(it => {
    const type = it.getItem().getType();
    if (type === FormApp.ItemType.FILE_UPLOAD) {
      fileIds = fileIds.concat(it.getResponse());
    } else if (type === FormApp.ItemType.TEXT) {
      tenTL = String(it.getResponse()).trim();
    }
  });
  fileIds.forEach(id => {
    const f = DriveApp.getFileById(id);
    let newName = f.getName();
    if (tenTL) newName = tenTL.replace(/[\\\/:*?"<>|]/g, '').trim() + '.pdf';
    if (!/\.pdf$/i.test(newName)) newName += '.pdf';
    f.makeCopy(newName, incoming);
  });
}

function xuLyFormTaiLieuBot(e) {
  if (!_formAllowed(e)) return;
  const props = PropertiesService.getScriptProperties();
  const incoming = DriveApp.getFolderById(props.getProperty('BOT_DOCS_FORM_ID'));
  let tenTL = '';
  let fileIds = [];
  e.response.getItemResponses().forEach(it => {
    const type = it.getItem().getType();
    if (type === FormApp.ItemType.FILE_UPLOAD) {
      fileIds = fileIds.concat(it.getResponse());
    } else if (type === FormApp.ItemType.TEXT) {
      tenTL = String(it.getResponse()).trim();
    }
  });
  fileIds.forEach(id => {
    const f = DriveApp.getFileById(id);
    let newName = f.getName();
    if (tenTL) newName = tenTL.replace(/[\\\/:*?"<>|]/g, '').trim() + '.pdf';
    if (!/\.pdf$/i.test(newName)) newName += '.pdf';
    f.makeCopy(newName, incoming);
  });
}

// Handler khi có người submit Form "Nạp .md cho bot": copy file .md vào folder _don_them_tai_lieu_bot_md.
function xuLyFormMd(e) {
  if (!_formAllowed(e)) return;
  const parent = DriveApp.getFolderById(HVHN_PARENT_FOLDER_ID);
  const incoming = getOrCreateFolder(parent, INCOMING_BOT_MD_NAME);
  let tenTL = '', tacGia = '';
  let fileIds = [];
  e.response.getItemResponses().forEach(it => {
    const type = it.getItem().getType();
    const title = it.getItem().getTitle().toLowerCase();
    if (type === FormApp.ItemType.FILE_UPLOAD) {
      fileIds = fileIds.concat(it.getResponse());
    } else if (type === FormApp.ItemType.TEXT) {
      if (title.indexOf('tác giả') >= 0 || title.indexOf('tac gia') >= 0) tacGia = String(it.getResponse()).trim();
      else tenTL = String(it.getResponse()).trim();
    }
  });
  fileIds.forEach(id => {
    const f = DriveApp.getFileById(id);
    let newName = f.getName();
    if (tenTL) newName = tenTL.replace(/[\\\/:*?"<>|]/g, '').trim() + '.md';
    if (!/\.md$/i.test(newName)) newName += '.md';
    if (tacGia) {
      // Ghi tác giả vào ĐẦU file để watcher/parser đọc (ưu tiên ô Form). Không ghi đè nếu file đã có sẵn.
      let text = f.getBlob().getDataAsString('UTF-8');
      if (!/^\s*t[aá]c gi[aả]\s*:/im.test(text) && !/^\s*---/.test(text)) {
        text = 'Tác giả: ' + tacGia + '\n\n' + text;
      }
      incoming.createFile(newName, text, 'text/markdown');
    } else {
      f.makeCopy(newName, incoming);
    }
  });
  ghiLog('Nạp .md cho bot', fileIds.length + ' file (tác giả: ' + (tacGia || '—') + ') -> ' + INCOMING_BOT_MD_NAME);
}

// ============================================================================
// ============== PHASE 3: PAYOS QR RIÊNG -> TỰ GỬI LINK DISCORD =============
// ============================================================================
// PayOS tạo một payment link/QR RIÊNG cho từng đơn. Khi có webhook hợp lệ (HMAC),
// hệ thống đối chiếu orderCode và số tiền, không phụ thuộc nội dung CK bị ngân hàng chèn.
// Bí mật chỉ lưu trong Script Properties, tuyệt đối không ghi vào file/GitHub.

const PMT_ORDER_TAB = '_don_dat_mua';
const PMT_DEFAULT_AMOUNT = 99999;
const PMT_AMOUNT_PROP = 'PMT_FIXED_AMOUNT';
const PMT_LINK_MINUTES = 30;
const PMT_PAYOS_API = 'https://api-merchant.payos.vn';
const CUSTOMER_GUIDE_FILE_ID = '1DeHcLRGqFWfNVETFRdfx-4dro1-yMsEf';
const CUSTOMER_GUIDE_URL = 'https://docs.google.com/document/d/1DeHcLRGqFWfNVETFRdfx-4dro1-yMsEf/edit?usp=sharing';
const CUSTOMER_NOTICE_IMAGE_FILE_ID_PROP = 'CUSTOMER_NOTICE_IMAGE_FILE_ID';
const CUSTOMER_MAIL_RELEASE = '2026-07-19-guide-mail-2';

function _pmtProp(key, def) {
  const v = PropertiesService.getScriptProperties().getProperty(key);
  return (v === null || v === undefined || v === '') ? def : v;
}

function _pmtAmount() {
  const raw = String(_pmtProp(PMT_AMOUNT_PROP, PMT_DEFAULT_AMOUNT)).replace(/\D/g, '');
  const amount = parseInt(raw, 10);
  return amount >= 1000 ? amount : PMT_DEFAULT_AMOUNT;
}

function _pmtFormatAmount(amount) {
  return Number(amount).toLocaleString('vi-VN') + 'đ';
}

function _driveFileIdFromUrlOrId(value) {
  const text = String(value || '').trim();
  const fromUrl = text.match(/\/d\/([a-zA-Z0-9_-]+)/) || text.match(/[?&]id=([a-zA-Z0-9_-]+)/);
  if (fromUrl) return fromUrl[1];
  return /^[a-zA-Z0-9_-]{10,}$/.test(text) ? text : '';
}

// Cài một lần bằng đúng ảnh "Một số lưu ý" trên Drive. File chỉ được đọc bởi
// Apps Script để đính kèm riêng trong email, không cần mở quyền công khai.
function caiDatTaiLieuHuongDanKhach() {
  const ui = SpreadsheetApp.getUi();
  const props = PropertiesService.getScriptProperties();
  const current = props.getProperty(CUSTOMER_NOTICE_IMAGE_FILE_ID_PROP);
  const response = ui.prompt(
    'Cài ảnh lưu ý gửi khách',
    'Tải đúng ảnh "Một số lưu ý" lên Google Drive của tài khoản đang chạy Apps Script, rồi dán link hoặc File ID tại đây.' +
      (current ? '\n\nHiện đã có ảnh. Bấm Hủy nếu không muốn đổi.' : ''),
    ui.ButtonSet.OK_CANCEL
  );
  if (response.getSelectedButton() !== ui.Button.OK) return;

  const fileId = _driveFileIdFromUrlOrId(response.getResponseText());
  if (!fileId) {
    ui.alert('Link hoặc File ID chưa hợp lệ. Hãy dán link Google Drive của ảnh.');
    return;
  }

  try {
    const file = DriveApp.getFileById(fileId);
    if (String(file.getMimeType() || '').indexOf('image/') !== 0) {
      throw new Error('File được chọn không phải ảnh.');
    }
    props.setProperty(CUSTOMER_NOTICE_IMAGE_FILE_ID_PROP, fileId);
    ghiLog('Cài ảnh lưu ý gửi khách', file.getName());
    ui.alert('Đã lưu ảnh lưu ý. Từ các email xác nhận thanh toán và pre-order tiếp theo, khách sẽ nhận kèm hướng dẫn sử dụng và ảnh này.');
  } catch (e) {
    ui.alert('Không đọc được ảnh: ' + ((e && e.message) || String(e)));
  }
}

function _customerOnboardingMaterials() {
  const materials = {
    attachments: [],
    guideAttachment: null,
    noticeAttachment: null,
    guideAttached: false,
    noticeAttached: false,
  };

  try {
    const guide = DriveApp.getFileById(CUSTOMER_GUIDE_FILE_ID);
    materials.guideAttachment = guide.getAs(MimeType.PDF).setName('Huong-dan-su-dung-he-thong-HVHN.pdf');
    materials.attachments.push(materials.guideAttachment);
    materials.guideAttached = true;
  } catch (e) {
    ghiLog('LỖI đính kèm hướng dẫn khách', (e && e.message) || String(e));
  }

  const noticeId = _pmtProp(CUSTOMER_NOTICE_IMAGE_FILE_ID_PROP, '');
  if (noticeId) {
    try {
      const notice = DriveApp.getFileById(noticeId);
      if (String(notice.getMimeType() || '').indexOf('image/') !== 0) {
        throw new Error('File ảnh lưu ý không còn là ảnh.');
      }
      materials.noticeAttachment = notice.getBlob().setName(notice.getName());
      materials.attachments.push(materials.noticeAttachment);
      materials.noticeAttached = true;
    } catch (e) {
      ghiLog('LỖI đính kèm ảnh lưu ý khách', (e && e.message) || String(e));
    }
  }

  return materials;
}

function _customerOnboardingPlainText(materials) {
  const attached = [];
  if (materials.guideAttached) attached.push('bản PDF hướng dẫn');
  if (materials.noticeAttached) attached.push('ảnh "Một số lưu ý"');
  const attachmentText = attached.length
    ? ' Email này có đính kèm ' + attached.join(' và ') + '.'
    : '';
  const requiredMaterials = attached.length ? ' hướng dẫn và các tài liệu đính kèm' : ' hướng dẫn';
  return '\n\nTrước khi sử dụng hệ thống, bạn vui lòng đọc kỹ hướng dẫn tại: ' + CUSTOMER_GUIDE_URL +
    attachmentText +
    '\n\nViệc đọc đầy đủ' + requiredMaterials + ' là bắt buộc để tài khoản, học liệu và quyền truy cập hoạt động ổn định. Sau khi đã đọc, bạn mới tiếp tục kích hoạt và sử dụng hệ thống.';
}

function _customerOnboardingHtml(materials) {
  const attached = [];
  if (materials.guideAttached) attached.push('bản PDF hướng dẫn');
  if (materials.noticeAttached) attached.push('ảnh “Một số lưu ý”');
  const attachmentText = attached.length
    ? '<p style="margin:8px 0 0">Email này có đính kèm ' + _pmtEsc(attached.join(' và ')) + '.</p>'
    : '';
  const materialText = attached.length ? ' và các tài liệu đính kèm' : '';
  return '<div style="margin:22px 0;padding:14px 16px;background:#f1f8f4;border-left:4px solid #0b8043;border-radius:4px">' +
    '<p style="margin:0 0 8px"><strong>Việc cần làm trước khi sử dụng hệ thống</strong></p>' +
    '<p style="margin:0">Vui lòng <strong>đọc kỹ</strong> <a href="' + _pmtEsc(CUSTOMER_GUIDE_URL) + '">Hướng dẫn sử dụng hệ thống HVHN</a>' + materialText + ' trước khi kích hoạt quyền truy cập.</p>' +
    attachmentText +
    '<p style="margin:8px 0 0">Đây là bước bắt buộc để tài khoản, học liệu và quyền truy cập của bạn hoạt động ổn định.</p>' +
    '</div>';
}

function _emptyCustomerOnboardingMaterials() {
  return {
    attachments: [],
    guideAttachment: null,
    noticeAttachment: null,
    guideAttached: false,
    noticeAttached: false,
  };
}

function _guideOnlyCustomerOnboardingMaterials(materials) {
  const guide = materials && materials.guideAttachment;
  if (!guide) return _emptyCustomerOnboardingMaterials();
  return {
    attachments: [guide],
    guideAttachment: guide,
    noticeAttachment: null,
    guideAttached: true,
    noticeAttached: false,
  };
}

function _sendCustomerMail(buildMessage, materials, attachments) {
  const message = buildMessage(materials);
  if (attachments && attachments.length) message.attachments = attachments;
  MailApp.sendEmail(message);
}

// The guide is a required delivery item. An optional notice image must never
// cause the guide PDF to disappear: retry with the guide only before falling
// back to the guide link in the message body.
function _sendCustomerAccessEmail(buildMessage, materials) {
  const current = materials || _emptyCustomerOnboardingMaterials();
  const attachments = current.attachments || [];
  if (attachments.length) {
    try {
      _sendCustomerMail(buildMessage, current, attachments);
      const result = current.guideAttached && current.noticeAttached
        ? 'sent_with_guide_and_notice'
        : (current.guideAttached ? 'sent_with_guide_only' : 'sent_with_notice_only');
      ghiLog('Gửi mail truy cập khách', CUSTOMER_MAIL_RELEASE + ' ' + result);
      return result;
    } catch (attachmentError) {
      ghiLog('LỖI mail khách kèm đủ tệp', (attachmentError && attachmentError.message) || String(attachmentError));
    }
  }

  const guideOnly = _guideOnlyCustomerOnboardingMaterials(current);
  if (guideOnly.attachments.length && attachments.length !== guideOnly.attachments.length) {
    try {
      _sendCustomerMail(buildMessage, guideOnly, guideOnly.attachments);
      ghiLog('Gửi mail truy cập khách', CUSTOMER_MAIL_RELEASE + ' sent_with_guide_only_after_attachment_fallback');
      return 'sent_with_guide_only';
    } catch (guideError) {
      ghiLog('LỖI mail khách kèm PDF hướng dẫn', (guideError && guideError.message) || String(guideError));
    }
  }

  try {
    _sendCustomerMail(buildMessage, _emptyCustomerOnboardingMaterials(), []);
    ghiLog('Gửi mail truy cập khách', CUSTOMER_MAIL_RELEASE + ' sent_with_guide_link_only');
    return 'sent_with_guide_link_only';
  } catch (mailError) {
    ghiLog('LỖI gửi mail truy cập khách', (mailError && mailError.message) || String(mailError));
    throw mailError;
  }
}

function _pmtOut(s) { return ContentService.createTextOutput(s); }

function _pmtEsc(value) {
  return String(value == null ? '' : value).replace(/&/g, '&amp;').replace(/</g, '&lt;')
    .replace(/>/g, '&gt;').replace(/"/g, '&quot;').replace(/'/g, '&#39;');
}

function _pmtHex(bytes) {
  return bytes.map(b => ((b + 256) % 256).toString(16).padStart(2, '0')).join('');
}

function _pmtHmac(value, key) {
  return _pmtHex(Utilities.computeHmacSha256Signature(String(value), String(key)));
}

// Quy tắc PayOS: sort key alphabet, null/undefined thành chuỗi rỗng.
function _pmtPayosDataString(data) {
  return Object.keys(data || {}).sort().map(key => {
    let value = data[key];
    if (value === null || value === undefined || value === 'null' || value === 'undefined') value = '';
    else if (Array.isArray(value)) value = JSON.stringify(value.map(v => v && typeof v === 'object' ? _pmtSortObject(v) : v));
    else if (typeof value === 'object') value = JSON.stringify(_pmtSortObject(value));
    return key + '=' + String(value);
  }).join('&');
}

function _pmtSortObject(obj) {
  const out = {};
  Object.keys(obj || {}).sort().forEach(key => { out[key] = obj[key]; });
  return out;
}

function _pmtOrderSheet() {
  const ss = SpreadsheetApp.getActiveSpreadsheet();
  let sh = ss.getSheetByName(PMT_ORDER_TAB);
  if (!sh) sh = ss.insertSheet(PMT_ORDER_TAB);
  _pmtEnsureOrderSheetColumns(sh);
  return sh;
}

function _pmtEnsureOrderSheetColumns(sh) {
  const headers = [
    'Thời gian', 'Mã đơn', 'Tên', 'Email', 'Số tiền', 'Trạng thái', 'Invite URL',
    'Thanh toán lúc', 'Gửi mail lúc', 'Ghi chú', 'PayOS orderCode', 'Payment link ID',
    'Link thanh toán', 'Dữ liệu QR', 'Hết hạn lúc'
  ];
  if (sh.getMaxColumns() < headers.length) sh.insertColumnsAfter(sh.getMaxColumns(), headers.length - sh.getMaxColumns());
  sh.getRange(1, 1, 1, headers.length).setValues([headers]);
  sh.getRange(1, 1, 1, headers.length).setBackground('#0b8043').setFontColor('#fff').setFontWeight('bold');
  sh.setFrozenRows(1);
  sh.setColumnWidth(2, 110); sh.setColumnWidth(3, 160); sh.setColumnWidth(4, 220);
  sh.setColumnWidth(7, 320); sh.setColumnWidth(13, 320); sh.setColumnWidth(14, 320);
  sh.getRange(2, 1, Math.max(1, sh.getMaxRows() - 1), 1).setNumberFormat('dd/mm/yyyy HH:mm:ss');
  sh.getRange(2, 8, Math.max(1, sh.getMaxRows() - 1), 2).setNumberFormat('dd/mm/yyyy HH:mm:ss');
  sh.getRange(2, 15, Math.max(1, sh.getMaxRows() - 1), 1).setNumberFormat('dd/mm/yyyy HH:mm:ss');
}

function _pmtAppUrl() {
  const configured = _pmtProp('PMT_APP_URL', '');
  if (configured) return configured.replace(/\/+$/, '');
  try { return (ScriptApp.getService().getUrl() || '').replace(/\/+$/, ''); } catch (e) { return ''; }
}

function _pmtShortOrderCode(sheet) {
  const existing = sheet.getLastRow() < 2 ? [] : sheet.getRange(2, 2, sheet.getLastRow() - 1, 1).getValues().flat();
  for (let attempt = 0; attempt < 20; attempt++) {
    const code = 'HV' + Math.floor(1000000 + Math.random() * 9000000);
    if (existing.indexOf(code) < 0) return code;
  }
  throw new Error('Không tạo được mã đơn duy nhất; hãy thử lại.');
}

function _pmtNumericOrderCode(sheet) {
  const existing = sheet.getLastRow() < 2 ? [] : sheet.getRange(2, 11, sheet.getLastRow() - 1, 1).getValues().flat().map(String);
  for (let attempt = 0; attempt < 20; attempt++) {
    // PayOS cần integer; 13 chữ số vẫn an toàn trong JavaScript và không đụng đơn cũ.
    const code = Date.now() * 10 + Math.floor(Math.random() * 10);
    if (existing.indexOf(String(code)) < 0) return code;
    Utilities.sleep(2);
  }
  throw new Error('Không tạo được PayOS orderCode duy nhất; hãy thử lại.');
}

// ---- Cài đặt một lần: bot, khóa PayOS và thời hạn gói. Giá đổi riêng qua menu. ----
function caiDatThanhToanTuDong() {
  const ui = SpreadsheetApp.getUi();
  const props = PropertiesService.getScriptProperties();
  function ask(step, message, current, secret) {
    const hint = current ? ('\n\n(đã có: ' + (secret ? '••••••••' : current) + ' — để trống rồi OK để giữ nguyên)') : '';
    const r = ui.prompt('Cài đặt PayOS QR — ' + step, message + hint, ui.ButtonSet.OK_CANCEL);
    if (r.getSelectedButton() !== ui.Button.OK) return null;
    return r.getResponseText().trim();
  }
  let v;
  v = ask('1/7', 'Địa chỉ bot Render, ví dụ https://ten-bot.onrender.com (không kèm /mint-invite).', props.getProperty('PMT_BOT_URL'));
  if (v === null) return; if (v) props.setProperty('PMT_BOT_URL', v.replace(/\/+$/, ''));
  v = ask('2/7', 'Mật khẩu bot: đúng giá trị HVHN_MINT_SECRET trên Render.', props.getProperty('PMT_SECRET'), true);
  if (v === null) return; if (v) props.setProperty('PMT_SECRET', v);
  v = ask('3/7', 'PayOS Client ID (Kênh thanh toán > Thông tin tích hợp).', props.getProperty('PAYOS_CLIENT_ID'), true);
  if (v === null) return; if (v) props.setProperty('PAYOS_CLIENT_ID', v);
  v = ask('4/7', 'PayOS API Key (Kênh thanh toán > Thông tin tích hợp).', props.getProperty('PAYOS_API_KEY'), true);
  if (v === null) return; if (v) props.setProperty('PAYOS_API_KEY', v);
  v = ask('5/7', 'PayOS Checksum Key (Kênh thanh toán > Thông tin tích hợp).', props.getProperty('PAYOS_CHECKSUM_KEY'), true);
  if (v === null) return; if (v) props.setProperty('PAYOS_CHECKSUM_KEY', v);
  v = ask('6/7', 'Số ngày truy cập sau thanh toán (ví dụ 30).', props.getProperty('PMT_DAYS') || '30');
  if (v === null) return; if (v) props.setProperty('PMT_DAYS', String(Math.max(1, parseInt(v.replace(/\D/g, ''), 10) || 30)));
  const appUrl = _pmtAppUrl();
  v = ask('7/7', 'Web app URL Apps Script đã Deploy (dạng https://script.google.com/macros/s/.../exec). Dùng để PayOS gọi webhook và để khách quay lại sau thanh toán.', props.getProperty('PMT_APP_URL') || appUrl);
  if (v === null) return; if (v) props.setProperty('PMT_APP_URL', v.replace(/\/+$/, ''));
  ui.alert('✅ Đã lưu cài đặt PayOS.\n\nGiá gói hiện tại: ' + _pmtFormatAmount(_pmtAmount()) + '.\nĐổi giá sau này tại HVHN > Thanh toán tự động > Đổi giá gói học liệu.\n\nTiếp theo: bấm “🔗 Kết nối/kiểm tra webhook PayOS”, sau đó tạo Form đặt mua.');
}

function _pmtConfigured() {
  const missing = ['PMT_BOT_URL', 'PMT_SECRET', 'PAYOS_CLIENT_ID', 'PAYOS_API_KEY', 'PAYOS_CHECKSUM_KEY', 'PMT_APP_URL']
    .filter(key => !_pmtProp(key, ''));
  if (missing.length) throw new Error('Thiếu cấu hình: ' + missing.join(', ') + '. Vào HVHN > Thanh toán tự động > Cài đặt PayOS QR.');
}

function xemCaiDatThanhToan() {
  const p = PropertiesService.getScriptProperties();
  SpreadsheetApp.getUi().alert('Cài đặt PayOS hiện tại:\n\n' +
    '• Bot URL: ' + (p.getProperty('PMT_BOT_URL') || '(chưa đặt)') + '\n' +
    '• Mật khẩu bot: ' + (p.getProperty('PMT_SECRET') ? '(đã đặt)' : '(chưa đặt)') + '\n' +
    '• PayOS Client ID: ' + (p.getProperty('PAYOS_CLIENT_ID') ? '(đã đặt)' : '(chưa đặt)') + '\n' +
    '• PayOS API Key: ' + (p.getProperty('PAYOS_API_KEY') ? '(đã đặt)' : '(chưa đặt)') + '\n' +
    '• PayOS Checksum Key: ' + (p.getProperty('PAYOS_CHECKSUM_KEY') ? '(đã đặt)' : '(chưa đặt)') + '\n' +
    '• Web app URL: ' + (p.getProperty('PMT_APP_URL') || '(chưa đặt)') + '\n' +
    '• Giá gói hiện tại: ' + _pmtFormatAmount(_pmtAmount()) + '\n' +
    '• Số ngày/gói: ' + (p.getProperty('PMT_DAYS') || '30') + '\n\n' +
    'Webhook PayOS không dùng token URL: hệ thống xác thực bằng HMAC Checksum Key.');
}

// Đổi giá cho CÁC ĐƠN TẠO SAU KHI LƯU. Đơn cũ giữ nguyên số tiền đã ghi ở tab _don_dat_mua.
function datGiaGoiHocLieu() {
  const ui = SpreadsheetApp.getUi();
  const current = _pmtAmount();
  const resp = ui.prompt(
    'Đổi giá gói học liệu',
    'Nhập giá mới theo VND, chỉ dùng chữ số. Giá hiện tại: ' + _pmtFormatAmount(current) + '.',
    ui.ButtonSet.OK_CANCEL
  );
  if (resp.getSelectedButton() !== ui.Button.OK) return;

  const raw = String(resp.getResponseText() || '').replace(/\D/g, '');
  const amount = parseInt(raw, 10);
  if (!amount || amount < 1000) {
    ui.alert('Giá không hợp lệ. Hãy nhập số tiền từ 1.000đ trở lên.');
    return;
  }

  PropertiesService.getScriptProperties().setProperty(PMT_AMOUNT_PROP, String(amount));
  _capNhatMoTaFormDatMua();
  ghiLog('Đổi giá gói học liệu', _pmtFormatAmount(current) + ' -> ' + _pmtFormatAmount(amount));
  ui.alert('Đã đổi giá thành ' + _pmtFormatAmount(amount) + '. Giá này chỉ áp dụng cho đơn mới; đơn đang chờ thanh toán giữ nguyên giá cũ.');
}

function ketNoiWebhookPayOS() {
  try {
    _pmtConfigured();
    const res = UrlFetchApp.fetch(PMT_PAYOS_API + '/confirm-webhook', {
      method: 'post', contentType: 'application/json',
      headers: { 'x-client-id': _pmtProp('PAYOS_CLIENT_ID', ''), 'x-api-key': _pmtProp('PAYOS_API_KEY', '') },
      payload: JSON.stringify({ webhookUrl: _pmtAppUrl() }), muteHttpExceptions: true,
    });
    const out = _pmtParseJsonSafe(res.getContentText());
    if (res.getResponseCode() < 200 || res.getResponseCode() >= 300 || out.code !== '00') {
      throw new Error('PayOS HTTP ' + res.getResponseCode() + ': ' + res.getContentText());
    }
    ghiLog('Đã kết nối webhook PayOS', _pmtAppUrl());
    SpreadsheetApp.getUi().alert('✅ PayOS đã xác thực webhook thành công. Bạn có thể tạo Form đặt mua và chạy thử 1 đơn.');
  } catch (e) {
    ghiLog('LỖI kết nối webhook PayOS', e.message || String(e));
    SpreadsheetApp.getUi().alert('Không kết nối được webhook PayOS:\n' + (e.message || String(e)) + '\n\nXem hướng dẫn PayOS QR để kiểm tra Deploy và 3 khóa PayOS.');
  }
}

// ---- Form đặt mua ----
function _taoFormDatMua(props) {
  const form = FormApp.create('HVHN — Đăng ký học liệu');
  form.setDescription(_pmtFormDatMuaDescription());
  form.addTextItem().setTitle('Họ và tên').setRequired(true);
  form.addTextItem().setTitle('Email nhận link Discord').setRequired(true).setValidation(_emailTextValidation());
  form.setConfirmationMessage('HVHN đã tiếp nhận. Vui lòng kiểm tra email (cả Spam) để mở mã QR thanh toán riêng của bạn.');
  form.setAcceptingResponses(true);
  _ensureSingleFormTrigger('xuLyFormDatMua', form);
  props.setProperty('FORM_DATMUA_ID', form.getId());
  return form;
}

function _pmtFormDatMuaDescription() {
  return 'Điền họ tên và email. Hệ thống gửi một mã QR thanh toán riêng, đúng ' + _pmtFormatAmount(_pmtAmount()) + '; sau khi thanh toán thành công, link Discord sẽ tự gửi về email này.';
}

// Cập nhật giá hiển thị trên Form đang dùng; không tạo Form/trigger mới.
function _capNhatMoTaFormDatMua() {
  const id = PropertiesService.getScriptProperties().getProperty('FORM_DATMUA_ID');
  const form = _openFormIfAlive(id);
  if (form) form.setDescription(_pmtFormDatMuaDescription());
}

function taoLaiFormDatMua() {
  const props = PropertiesService.getScriptProperties();
  let form = _openFormIfAlive(props.getProperty('FORM_DATMUA_ID'));
  if (!form) form = _taoFormDatMua(props);
  form.setDescription(_pmtFormDatMuaDescription());
  _ensureFormEmailValidation(form);
  _ensureSingleFormTrigger('xuLyFormDatMua', form);
  const msg = 'Form ĐĂNG KÝ HỌC LIỆU đang dùng. Đăng/gửi link này cho khách:\n\n' + form.getPublishedUrl();
  Logger.log(msg); SpreadsheetApp.getUi().alert(msg);
}

function _pmtParseJsonSafe(text) {
  try { return JSON.parse(text || '{}'); } catch (e) { return { error: 'bad_json', raw: String(text || '').slice(0, 300) }; }
}

function _pmtCreatePayosLink(orderCode, shortCode, name, email, amount, expiry) {
  _pmtConfigured();
  const appUrl = _pmtAppUrl();
  const payload = {
    orderCode: orderCode, amount: amount, description: shortCode,
    cancelUrl: appUrl + '?pmt=cancelled', returnUrl: appUrl + '?pmt=completed',
    buyerName: name, buyerEmail: email,
    items: [{ name: 'Gói học liệu HVHN', quantity: 1, price: amount }],
    expiredAt: Math.floor(expiry.getTime() / 1000),
  };
  payload.signature = _pmtHmac('amount=' + payload.amount + '&cancelUrl=' + payload.cancelUrl + '&description=' + payload.description + '&orderCode=' + payload.orderCode + '&returnUrl=' + payload.returnUrl, _pmtProp('PAYOS_CHECKSUM_KEY', ''));
  const res = UrlFetchApp.fetch(PMT_PAYOS_API + '/v2/payment-requests', {
    method: 'post', contentType: 'application/json',
    headers: { 'x-client-id': _pmtProp('PAYOS_CLIENT_ID', ''), 'x-api-key': _pmtProp('PAYOS_API_KEY', '') },
    payload: JSON.stringify(payload), muteHttpExceptions: true,
  });
  const out = _pmtParseJsonSafe(res.getContentText());
  if (res.getResponseCode() < 200 || res.getResponseCode() >= 300 || out.code !== '00' || !out.data || !out.data.checkoutUrl) {
    throw new Error('PayOS HTTP ' + res.getResponseCode() + ': ' + res.getContentText());
  }
  return out.data;
}

function _pmtQrImageUrl(qrData) {
  // Ảnh QR chỉ là tiện ích hiển thị trong email; nút checkoutUrl vẫn là đường thanh toán chính thức.
  return 'https://quickchart.io/qr?size=300&margin=1&text=' + encodeURIComponent(qrData || '');
}

function _pmtSendPaymentEmail(email, name, shortCode, amount, checkoutUrl, qrData, expiry) {
  const formatted = Utilities.formatDate(expiry, Session.getScriptTimeZone(), 'HH:mm, dd/MM/yyyy');
  const qrUrl = _pmtQrImageUrl(qrData);
  const body = 'Chào ' + name + ',\n\nHVHN đã tạo mã QR thanh toán riêng cho bạn. Vui lòng thanh toán đúng ' + amount.toLocaleString('vi-VN') + 'đ trước ' + formatted + '. Sau khi giao dịch được hệ thống xác nhận, link Discord sẽ tự gửi về email này.\n\nMã tham chiếu: ' + shortCode + '\nThanh toán: ' + checkoutUrl;
  const html = '<div style="max-width:620px;margin:auto;font-family:Arial,sans-serif;color:#202124;line-height:1.6">' +
    '<h2 style="margin:0 0 8px;color:#0b8043">HVHN · Mã QR thanh toán của bạn</h2>' +
    '<p>Chào <strong>' + _pmtEsc(name) + '</strong>,</p>' +
    '<p>HVHN đã tạo <strong>một mã QR thanh toán riêng</strong> cho đơn đăng ký của bạn. Vui lòng hoàn tất giao dịch trước <strong>' + _pmtEsc(formatted) + '</strong>.</p>' +
    '<div style="background:#f1f8f4;border-left:4px solid #0b8043;padding:14px 16px;border-radius:4px">' +
    '<div><strong>Số tiền:</strong> ' + amount.toLocaleString('vi-VN') + 'đ</div><div><strong>Mã tham chiếu:</strong> ' + _pmtEsc(shortCode) + '</div></div>' +
    '<p style="text-align:center;margin:22px 0 10px"><img src="' + _pmtEsc(qrUrl) + '" width="260" height="260" alt="Mã QR thanh toán HVHN" style="max-width:260px;border:1px solid #e0e0e0;padding:8px;border-radius:8px"></p>' +
    '<p style="text-align:center"><a href="' + _pmtEsc(checkoutUrl) + '" style="display:inline-block;padding:12px 20px;background:#0b8043;color:#fff;text-decoration:none;border-radius:6px;font-weight:bold">Mở trang thanh toán an toàn</a></p>' +
    '<p>Sau khi hệ thống xác nhận thanh toán, hệ thống sẽ tự gửi <strong>link tham gia Discord</strong> đến đúng email này. Bạn không cần gửi ảnh giao dịch.</p>' +
    '<p style="font-size:13px;color:#5f6368">Nếu QR không hiển thị, hãy bấm nút “Mở trang thanh toán an toàn”. Nếu quá thời hạn hoặc cần hỗ trợ, hãy tạo lại đơn bằng Form HVHN.</p>' +
    '<p>Trân trọng,<br><strong>HVHN · Hồn Văn, Hồn Người</strong></p></div>';
  MailApp.sendEmail({ to: email, subject: '[HVHN] Mã QR thanh toán ' + _pmtFormatAmount(amount), body: body, htmlBody: html, name: 'HVHN' });
}

// onFormSubmit: tạo QR/link PayOS riêng, lưu đầy đủ thông tin trước rồi mới gửi email.
function xuLyFormDatMua(e) {
  let name = '', email = '';
  e.response.getItemResponses().forEach(it => {
    const t = it.getItem().getTitle().toLowerCase();
    if (t.indexOf('tên') >= 0) name = String(it.getResponse()).trim();
    else if (t.indexOf('email') >= 0) email = String(it.getResponse()).trim().toLowerCase();
  });
  if (!_isValidPersonName(name) || !_isValidEmail(email)) {
    ghiLog('Từ chối Form đặt mua (tên/email không hợp lệ)', name + ' - ' + email);
    return;
  }
  let sheet, amount, shortCode, orderCode, expiry, row;
  const lock = LockService.getScriptLock();
  lock.waitLock(30000);
  try {
    // Giữ lock chỉ trong lúc cấp mã + đặt chỗ dòng. Hai Form submit đồng
    // thời không thể chọn cùng một dòng hay sinh trùng orderCode.
    sheet = _pmtOrderSheet();
    amount = _pmtAmount();
    shortCode = _pmtShortOrderCode(sheet);
    orderCode = _pmtNumericOrderCode(sheet);
    expiry = new Date(Date.now() + PMT_LINK_MINUTES * 60 * 1000);
    row = sheet.getLastRow() + 1;
    sheet.getRange(row, 1, 1, 15).setValues([[new Date(), shortCode, name, email, amount, 'dang_tao_qr', '', '', '', '', orderCode, '', '', '', expiry]]);
  } finally {
    lock.releaseLock();
  }
  let payment;
  try {
    payment = _pmtCreatePayosLink(orderCode, shortCode, name, email, amount, expiry);
  } catch (err) {
    const errorLock = LockService.getScriptLock();
    errorLock.waitLock(30000);
    try {
      if (String(sheet.getRange(row, 6).getValue() || '') !== 'da_xu_ly') {
        sheet.getRange(row, 6).setValue('loi_tao_qr');
        sheet.getRange(row, 10).setValue((err && err.message) || String(err));
      }
    } finally {
      errorLock.releaseLock();
    }
    ghiLog('LỖI tạo QR PayOS', shortCode + ' - ' + ((err && err.message) || String(err)));
    throw err;
  }

  // PayOS có thể gọi webhook ngay sau khi link được tạo. Khóa lần hai để Form
  // không bao giờ hạ trạng thái da_xu_ly về cho_thanh_toan.
  const finalizeLock = LockService.getScriptLock();
  finalizeLock.waitLock(30000);
  try {
    const currentStatus = String(sheet.getRange(row, 6).getValue() || '');
    sheet.getRange(row, 12, 1, 3).setValues([[
      payment.paymentLinkId || '', payment.checkoutUrl || '', payment.qrCode || ''
    ]]);
    if (currentStatus !== 'da_xu_ly') {
      sheet.getRange(row, 6).setValue('cho_thanh_toan');
      try {
        _pmtSendPaymentEmail(email, name, shortCode, amount, payment.checkoutUrl, payment.qrCode, expiry);
        sheet.getRange(row, 9).setValue(new Date());
      } catch (mailError) {
        sheet.getRange(row, 6).setValue('loi_gui_email_qr');
        sheet.getRange(row, 10).setValue((mailError && mailError.message) || String(mailError));
        throw mailError;
      }
    }
  } finally {
    finalizeLock.releaseLock();
  }
  ghiLog('Đơn PayOS QR mới', shortCode + ' / ' + orderCode + ' - ' + name + ' - ' + email);
}

function _pmtMintInvite(maDon, name, email) {
  const url = _pmtProp('PMT_BOT_URL', '');
  const secret = _pmtProp('PMT_SECRET', '');
  const days = parseInt(_pmtProp('PMT_DAYS', '30'), 10);
  if (!url || !secret) return { error: 'chua_cau_hinh' };
  const res = UrlFetchApp.fetch(url + '/mint-invite', {
    method: 'post', contentType: 'application/json', headers: { 'X-HVHN-Secret': secret },
    payload: JSON.stringify({ order_code: maDon, name: name, email: email, duration_days: days }), muteHttpExceptions: true,
  });
  const out = _pmtParseJsonSafe(res.getContentText());
  if (!out.invite_url) {
    ghiLog('Bot tạo link lỗi', maDon + ' HTTP ' + res.getResponseCode() + ' -> ' + res.getContentText());
    return { error: 'mint_loi' };
  }
  return out;
}

function _pmtSendInviteEmail(email, name, inviteUrl) {
  const buildMessage = function(materials) {
    const body = 'Chào ' + name + ',\n\nThanh toán của bạn đã được xác nhận. Link tham gia Discord HVHN: ' + inviteUrl + _customerOnboardingPlainText(materials) + '\n\nSau khi vào Discord, hãy vào kênh #truy-cập-tài-liệu và bấm “Kích hoạt quyền truy cập tài liệu” để điền Họ tên + Email.\n\nTrân trọng,\nHVHN · Hồn Văn, Hồn Người';
    const html = '<div style="max-width:620px;margin:auto;font-family:Arial,sans-serif;color:#202124;line-height:1.6">' +
      '<h2 style="margin:0 0 8px;color:#0b8043">HVHN · Thanh toán đã được xác nhận</h2><p>Chào <strong>' + _pmtEsc(name) + '</strong>,</p>' +
      '<p>Hệ thống đã xác nhận thanh toán của bạn. Bấm nút dưới đây để tham gia cộng đồng Discord HVHN.</p>' +
      '<p style="text-align:center;margin:24px 0"><a href="' + _pmtEsc(inviteUrl) + '" style="display:inline-block;padding:12px 20px;background:#5865F2;color:#fff;text-decoration:none;border-radius:6px;font-weight:bold">Tham gia Discord HVHN</a></p>' +
      _customerOnboardingHtml(materials) +
      '<p>Sau khi vào Discord, hãy vào kênh <strong>#truy-cập-tài-liệu</strong> và bấm <strong>“Kích hoạt quyền truy cập tài liệu”</strong> để điền Họ tên + Email.</p>' +
      '<p style="font-size:13px;color:#5f6368">Link mời có giới hạn sử dụng. Nếu link hết hiệu lực, hãy phản hồi email này để được hỗ trợ.</p><p>Trân trọng,<br><strong>HVHN · Hồn Văn, Hồn Người</strong></p></div>';
    return { to: email, subject: '[HVHN] Thanh toán thành công – link Discord của bạn', body: body, htmlBody: html, name: 'HVHN' };
  };
  return _sendCustomerAccessEmail(buildMessage, _customerOnboardingMaterials());
}

function _pmtMintAndSendForRow(sheet, rowNumber, opts) {
  opts = opts || {};
  const row = sheet.getRange(rowNumber, 1, 1, 15).getValues()[0];
  const maDon = String(row[1] || '').trim(), name = String(row[2] || '').trim(), email = String(row[3] || '').trim().toLowerCase();
  if (!maDon || !_isValidPersonName(name) || !_isValidEmail(email)) {
    throw new Error('Dòng đơn có mã/tên/email không hợp lệ');
  }
  const out = _pmtMintInvite(maDon, name, email);
  if (!out.invite_url) return out.error || 'mint_loi';
  const mailResult = _pmtSendInviteEmail(email, name, out.invite_url);
  sheet.getRange(rowNumber, 6).setValue('da_xu_ly');
  sheet.getRange(rowNumber, 7).setValue(out.invite_url);
  if (opts.paidAt) sheet.getRange(rowNumber, 8).setValue(opts.paidAt);
  sheet.getRange(rowNumber, 9).setValue(new Date());
  sheet.getRange(rowNumber, 10).setValue((opts.note || '') + (out.reused ? ' reused_invite' : '') + ' mail=' + mailResult);
  ghiLog('Đã cấp link Discord', maDon + ' - ' + email + (opts.note ? ' - ' + opts.note : ''));
  return 'ok';
}

function guiLaiLinkDiscordChoDonDangChon() {
  const sheet = SpreadsheetApp.getActiveSpreadsheet().getActiveSheet();
  if (sheet.getName() !== PMT_ORDER_TAB || sheet.getActiveRange().getRow() <= 1) {
    SpreadsheetApp.getUi().alert('Hãy chọn một dòng đơn (không phải header) trong tab ' + PMT_ORDER_TAB + '.'); return;
  }
  const row = sheet.getActiveRange().getRow();
  const lock = LockService.getScriptLock();
  let locked = false;
  let status;
  try {
    lock.waitLock(30000);
    locked = true;
    status = _pmtMintAndSendForRow(sheet, row, { note: 'gui_lai_thu_cong' });
  } finally {
    if (locked) lock.releaseLock();
  }
  SpreadsheetApp.getUi().alert(status === 'ok' ? 'Đã gửi lại link Discord cho khách.' : ('Không gửi được: ' + status));
}

function _pmtVerifyWebhook(data, signature) {
  const key = _pmtProp('PAYOS_CHECKSUM_KEY', '');
  return !!key && String(signature || '').toLowerCase() === _pmtHmac(_pmtPayosDataString(data), key).toLowerCase();
}

const PREORDER_WORKER_RELAY_ACTION = 'schedule_preorder_worker';
const PREORDER_WORKER_RELAY_MAX_AGE_MS = 5 * 60 * 1000;

function _preorderWorkerRelaySignature(timestamp) {
  return _pmtHmac(PREORDER_WORKER_RELAY_ACTION + ':' + String(timestamp), _pmtProp('PMT_SECRET', ''));
}

function _isAuthorizedPreorderWorkerRelay(payload) {
  const timestamp = Number(payload && payload.timestamp || 0);
  const secret = _pmtProp('PMT_SECRET', '');
  if (!secret || !timestamp || Math.abs(Date.now() - timestamp) > PREORDER_WORKER_RELAY_MAX_AGE_MS) return false;
  return String(payload.signature || '').toLowerCase() === _preorderWorkerRelaySignature(timestamp).toLowerCase();
}

// Hàm này chạy dưới danh tính Web App đã deploy, tức tài khoản chủ automation.
// Nó chỉ cài trigger, không mint invite hay gửi email trong request webhook ngắn này.
function _schedulePreorderWorkerAsDeploymentOwner() {
  const triggers = ScriptApp.getProjectTriggers();
  const hasRecurring = triggers.some(t => t.getHandlerFunction() === 'xuLyDonPreorderTuDong');
  const hasFast = triggers.some(t => t.getHandlerFunction() === PREORDER_FAST_TRIGGER_HANDLER);
  if (!hasRecurring) ScriptApp.newTrigger('xuLyDonPreorderTuDong').timeBased().everyMinutes(1).create();
  if (!hasFast) {
    ScriptApp.newTrigger(PREORDER_FAST_TRIGGER_HANDLER)
      .timeBased()
      .after(PREORDER_FAST_DELAY_MS)
      .create();
  }
}

function _relayPreorderWorkerToDeploymentOwner() {
  const appUrl = _pmtAppUrl();
  const secret = _pmtProp('PMT_SECRET', '');
  if (!appUrl || !secret) return false;
  const timestamp = Date.now();
  const res = UrlFetchApp.fetch(appUrl, {
    method: 'post', contentType: 'application/json', muteHttpExceptions: true,
    payload: JSON.stringify({
      internalAction: PREORDER_WORKER_RELAY_ACTION,
      timestamp: timestamp,
      signature: _preorderWorkerRelaySignature(timestamp),
    }),
  });
  const body = String(res.getContentText() || '').trim();
  if (res.getResponseCode() >= 200 && res.getResponseCode() < 300 && body === 'preorder_worker_scheduled') return true;
  throw new Error('Relay worker HTTP ' + res.getResponseCode() + ': ' + body.slice(0, 200));
}

function testWebhookThanhToanChoDonDangChon() {
  const sheet = SpreadsheetApp.getActiveSpreadsheet().getActiveSheet();
  if (sheet.getName() !== PMT_ORDER_TAB || sheet.getActiveRange().getRow() <= 1) {
    SpreadsheetApp.getUi().alert('Hãy chọn một dòng đơn (không phải header) trong tab ' + PMT_ORDER_TAB + '.'); return;
  }
  const row = sheet.getActiveRange().getRow();
  const vals = sheet.getRange(row, 1, 1, 15).getValues()[0];
  const data = { orderCode: Number(vals[10]), amount: Number(vals[4]), description: String(vals[1]), paymentLinkId: String(vals[11] || 'test'), code: '00', desc: 'Thành công' };
  const fake = { postData: { contents: JSON.stringify({ code: '00', success: true, data: data, signature: _pmtHmac(_pmtPayosDataString(data), _pmtProp('PAYOS_CHECKSUM_KEY', '')) }) } };
  const out = doPost(fake).getContent();
  SpreadsheetApp.getUi().alert('Kết quả test webhook: ' + out + '\nLưu ý: test này cấp invite và gửi mail thật. Xem tab Nhật ký.');
}

// PayOS webhook: xác thực HMAC trước, sau đó khớp orderCode + số tiền cố định.
function doPost(e) {
  let payload;
  try {
    payload = JSON.parse((e && e.postData && e.postData.contents) || '{}');
  } catch (e2) {
    return _pmtOut('bo_qua');
  }
  if (payload.internalAction === PREORDER_WORKER_RELAY_ACTION) {
    if (!_isAuthorizedPreorderWorkerRelay(payload)) return _pmtOut('unauthorized');
    try {
      _schedulePreorderWorkerAsDeploymentOwner();
      return _pmtOut('preorder_worker_scheduled');
    } catch (relayError) {
      ghiLog('LỖI relay worker pre-order', (relayError && relayError.message) || String(relayError));
      return _pmtOut('loi');
    }
  }
  const lock = LockService.getScriptLock();
  let locked = false;
  try {
    // PayOS có thể gửi trùng webhook. Tuần tự hóa toàn bộ đoạn
    // check -> mint -> email -> đánh dấu để một đơn chỉ gửi mail một lần.
    lock.waitLock(30000);
    locked = true;
    const data = payload.data || {};
    if (!payload.success || payload.code !== '00' || data.code !== '00') return _pmtOut('bo_qua');
    if (!_pmtVerifyWebhook(data, payload.signature)) {
      ghiLog('Webhook PayOS bị từ chối (sai chữ ký)', 'orderCode=' + String(data.orderCode || ''));
      return _pmtOut('unauthorized');
    }
    const sheet = _pmtOrderSheet(), last = sheet.getLastRow();
    if (last < 2) return _pmtOut('khong_khop');
    const rows = sheet.getRange(2, 1, last - 1, 15).getValues();
    const expectedOrderCode = String(data.orderCode || '');
    for (let i = 0; i < rows.length; i++) {
      if (String(rows[i][10] || '') !== expectedOrderCode) continue;
      const maDon = String(rows[i][1] || ''), gia = Number(rows[i][4] || 0), status = String(rows[i][5] || '');
      if (status === 'da_xu_ly') return _pmtOut('da_xu_ly');
      if (gia < 1000 || Number(data.amount || 0) !== gia) {
        ghiLog('Webhook PayOS sai số tiền', maDon + ' nhận ' + data.amount + '/' + gia);
        return _pmtOut('sai_so_tien');
      }
      const result = _pmtMintAndSendForRow(sheet, i + 2, { paidAt: data.transactionDateTime || new Date(), note: 'payos orderCode=' + expectedOrderCode + ' ref=' + String(data.reference || '') });
      return _pmtOut(result);
    }
    ghiLog('Webhook PayOS không khớp orderCode', expectedOrderCode);
    return _pmtOut('khong_khop');
  } catch (err) {
    ghiLog('LỖI doPost PayOS', (err && err.message) || String(err));
    return _pmtOut('loi');
  } finally {
    if (locked) lock.releaseLock();
  }
}

// Trang khách thấy sau khi PayOS quay về. Không dùng trang này làm căn cứ cấp quyền.
function doGet(e) {
  const state = e && e.parameter && e.parameter.pmt;
  const done = state === 'completed';
  const text = done ? 'Thanh toán đang được xác nhận' : 'Đơn thanh toán đã được hủy';
  const detail = done ? 'Nếu giao dịch thành công, link Discord sẽ tự gửi vào email bạn đã đăng ký trong ít phút.' : 'Bạn có thể quay lại Form HVHN để tạo mã QR mới khi cần.';
  return HtmlService.createHtmlOutput('<!doctype html><html><meta name="viewport" content="width=device-width,initial-scale=1"><body style="font-family:Arial,sans-serif;max-width:620px;margin:56px auto;padding:0 20px;color:#202124"><h2 style="color:#0b8043">HVHN</h2><h3>' + _pmtEsc(text) + '</h3><p>' + _pmtEsc(detail) + '</p></body></html>').setTitle('HVHN');
}

// ============================================================================
// =============== KHÁCH PRE-ORDER: FORM -> INVITE DISCORD RIÊNG =============
// ============================================================================
// Form này dành cho người đã đặt slot từ trước, không đi qua PayOS. Allowlist
// được đọc sống từ Google Sheet responses cũ, độc lập với Sheet Phân phối.
// Tab _khach_preorder chỉ là nhật ký cấp invite + chống submit lần hai.

const PREORDER_TAB = '_khach_preorder';
const PREORDER_FORM_ID_PROP = 'FORM_PREORDER_ID';
const PREORDER_SOURCE_SPREADSHEET_ID_PROP = 'PREORDER_SOURCE_SPREADSHEET_ID';
const PREORDER_SOURCE_GID_PROP = 'PREORDER_SOURCE_GID';
const PREORDER_SOURCE_SHEET_NAME_PROP = 'PREORDER_SOURCE_SHEET_NAME';
const PREORDER_SOURCE_EMAIL_HEADER_PROP = 'PREORDER_SOURCE_EMAIL_HEADER';
const PREORDER_DEFAULT_SOURCE_SPREADSHEET_ID = '1YB9tc7mHoLijcSJgUwSGiE1z-kQwTSPF03An92sgw68';
const PREORDER_DEFAULT_SOURCE_GID = '368858728';
const PREORDER_DEFAULT_EMAIL_HEADER = 'Gmail của bạn là gì?';

function _preorderSourceFromInput(value) {
  const text = String(value || '').trim();
  if (!text) return { spreadsheetId: '', gid: '' };
  const idMatch = text.match(/\/spreadsheets\/d\/([a-zA-Z0-9-_]+)/) || text.match(/[?&]id=([a-zA-Z0-9-_]+)/);
  const gidMatch = text.match(/[?&#]gid=([0-9]+)/);
  return {
    spreadsheetId: idMatch ? idMatch[1] : text,
    gid: gidMatch ? gidMatch[1] : '',
  };
}

function _preorderSourceConfig() {
  const props = PropertiesService.getScriptProperties();
  return {
    spreadsheetId: props.getProperty(PREORDER_SOURCE_SPREADSHEET_ID_PROP) || PREORDER_DEFAULT_SOURCE_SPREADSHEET_ID,
    gid: props.getProperty(PREORDER_SOURCE_GID_PROP) || PREORDER_DEFAULT_SOURCE_GID,
    sheetName: props.getProperty(PREORDER_SOURCE_SHEET_NAME_PROP) || '',
    emailHeader: props.getProperty(PREORDER_SOURCE_EMAIL_HEADER_PROP) || PREORDER_DEFAULT_EMAIL_HEADER,
  };
}

function _preorderSheetByGid(spreadsheet, gid) {
  const target = Number(gid || 0);
  if (!target) return null;
  const sheets = spreadsheet.getSheets();
  for (let i = 0; i < sheets.length; i++) {
    if (sheets[i].getSheetId() === target) return sheets[i];
  }
  return null;
}

function _preorderEmailColumnIndex(headers, configuredHeader) {
  const normalized = headers.map(h => String(h || '').trim().toLowerCase());
  if (configuredHeader) {
    const needle = String(configuredHeader || '').trim().toLowerCase();
    const exact = normalized.indexOf(needle);
    if (exact >= 0) return exact;
    return -1;
  }
  for (let i = 0; i < normalized.length; i++) {
    if (normalized[i] === 'email' || normalized[i].indexOf('email') >= 0 || normalized[i].indexOf('gmail') >= 0) {
      return i;
    }
  }
  return -1;
}

function _preorderEmailsFromSourceSheet() {
  return _preorderEmailsFromConfig(_preorderSourceConfig());
}

function _preorderEmailsFromConfig(cfg) {
  if (!cfg.spreadsheetId) return [];
  const src = SpreadsheetApp.openById(cfg.spreadsheetId);
  const sh = _preorderSheetByGid(src, cfg.gid) || (cfg.sheetName ? src.getSheetByName(cfg.sheetName) : src.getSheets()[0]);
  if (!sh) throw new Error('Không tìm thấy tab responses cũ.');
  const values = sh.getDataRange().getValues();
  if (values.length < 2) return [];
  const col = _preorderEmailColumnIndex(values[0], cfg.emailHeader);
  if (col < 0) {
    throw new Error('Không tìm thấy cột email trong sheet responses cũ. Hãy cấu hình đúng tiêu đề cột email.');
  }
  const seen = {};
  const emails = [];
  for (let r = 1; r < values.length; r++) {
    const email = String(values[r][col] || '').trim().toLowerCase();
    if (!_isValidEmail(email) || seen[email]) continue;
    seen[email] = true;
    emails.push(email);
  }
  return emails;
}

function _preorderAllowedEmails() {
  const allowed = {};
  _preorderEmailsFromSourceSheet().forEach(email => { allowed[email] = true; });
  return allowed;
}

function _preorderSheet() {
  const ss = SpreadsheetApp.getActiveSpreadsheet();
  let sh = ss.getSheetByName(PREORDER_TAB);
  if (!sh) sh = ss.insertSheet(PREORDER_TAB);
  const headers = ['Thời gian', 'Tên', 'Email', 'Mã pre-order', 'Trạng thái', 'Invite URL', 'Gửi mail lúc', 'Ghi chú'];
  if (sh.getMaxColumns() < headers.length) sh.insertColumnsAfter(sh.getMaxColumns(), headers.length - sh.getMaxColumns());
  sh.getRange(1, 1, 1, headers.length).setValues([headers]);
  sh.getRange(1, 1, 1, headers.length).setBackground('#6a1b9a').setFontColor('#fff').setFontWeight('bold');
  sh.setFrozenRows(1);
  sh.setColumnWidth(2, 180); sh.setColumnWidth(3, 240); sh.setColumnWidth(6, 330); sh.setColumnWidth(8, 250);
  sh.getRange(2, 1, Math.max(1, sh.getMaxRows() - 1), 1).setNumberFormat('dd/mm/yyyy HH:mm:ss');
  sh.getRange(2, 7, Math.max(1, sh.getMaxRows() - 1), 1).setNumberFormat('dd/mm/yyyy HH:mm:ss');
  return sh;
}

// Dùng mã ổn định theo email: một slot luôn gắn với một mã invite duy nhất.
function _preorderCode(email) {
  const digest = Utilities.computeDigest(Utilities.DigestAlgorithm.SHA_256, String(email || '').trim().toLowerCase());
  return 'PRE' + _pmtHex(digest).slice(0, 16).toUpperCase();
}

function caiDatEmailPreorder() {
  const ui = SpreadsheetApp.getUi();
  const props = PropertiesService.getScriptProperties();
  const current = _preorderSourceConfig();
  const sourceResp = ui.prompt(
    'Kết nối sheet responses cũ',
    'Dán URL hoặc ID của Google Sheet responses cũ đang ghi đơn mua của khách.\n\nHiện tại: ' + (current.spreadsheetId || '(chưa cài)'),
    ui.ButtonSet.OK_CANCEL
  );
  if (sourceResp.getSelectedButton() !== ui.Button.OK) return;
  const parsedSource = _preorderSourceFromInput(sourceResp.getResponseText());
  if (!parsedSource.spreadsheetId) { ui.alert('Chưa nhập URL/ID Google Sheet responses cũ.'); return; }

  const sheetResp = ui.prompt(
    'Tên tab responses',
    'Nhập tên tab chứa responses. Để trống sẽ dùng tab đầu tiên.\n\nHiện tại: ' + (current.sheetName || '(tab đầu tiên)'),
    ui.ButtonSet.OK_CANCEL
  );
  if (sheetResp.getSelectedButton() !== ui.Button.OK) return;

  const headerResp = ui.prompt(
    'Cột email khách',
    'Nhập đúng tiêu đề cột chứa email khách. Mặc định là "Gmail của bạn là gì?". Hệ thống sẽ tìm chính xác tiêu đề này.\n\nHiện tại: ' + current.emailHeader,
    ui.ButtonSet.OK_CANCEL
  );
  if (headerResp.getSelectedButton() !== ui.Button.OK) return;

  const candidate = {
    spreadsheetId: parsedSource.spreadsheetId,
    gid: parsedSource.gid || current.gid || '',
    sheetName: String(sheetResp.getResponseText() || '').trim(),
    emailHeader: String(headerResp.getResponseText() || '').trim() || PREORDER_DEFAULT_EMAIL_HEADER,
  };
  let emails;
  try {
    // Kiểm tra quyền truy cập/tab/header trước khi ghi Properties; cấu hình
    // sai không còn làm hỏng allowlist đang chạy.
    emails = _preorderEmailsFromConfig(candidate);
  } catch (e) {
    ui.alert('Không thể kết nối sheet responses: ' + ((e && e.message) || String(e)));
    return;
  }
  props.setProperty(PREORDER_SOURCE_SPREADSHEET_ID_PROP, candidate.spreadsheetId);
  props.setProperty(PREORDER_SOURCE_GID_PROP, candidate.gid);
  props.setProperty(PREORDER_SOURCE_SHEET_NAME_PROP, candidate.sheetName);
  props.setProperty(PREORDER_SOURCE_EMAIL_HEADER_PROP, candidate.emailHeader);
  ghiLog('Kết nối allowlist pre-order từ sheet responses cũ', emails.length + ' email');
  ui.alert('Đã kết nối sheet responses cũ. Hiện đọc được ' + emails.length + ' email hợp lệ. Từ giờ allowlist tự cập nhật khi sheet responses có dòng mới.');
}

// Dùng khi cần kiểm tra nhanh một email có thực sự nằm trong allowlist hay đã
// nhận invite trước đó chưa. Không gửi email và không thay đổi dữ liệu.
function kiemTraEmailPreorder() {
  const ui = SpreadsheetApp.getUi();
  const response = ui.prompt('Kiểm tra email pre-order', 'Nhập email cần kiểm tra:', ui.ButtonSet.OK_CANCEL);
  if (response.getSelectedButton() !== ui.Button.OK) return;
  const email = String(response.getResponseText() || '').trim().toLowerCase();
  if (!_isValidEmail(email)) {
    ui.alert('Email không hợp lệ.');
    return;
  }

  try {
    const allowed = _preorderAllowedEmails();
    const sheet = _preorderSheet();
    const row = _preorderFindRowByEmail(sheet, email);
    const status = row ? String(sheet.getRange(row, 5).getValue() || '') : '';
    const note = row ? String(sheet.getRange(row, 8).getValue() || '') : '';
    const message = allowed[email]
      ? 'Email có trong allowlist pre-order.'
      : 'Email KHÔNG có trong allowlist pre-order hiện tại.';
    ui.alert(message + '\n\n' +
      (row ? ('Dòng pre-order: ' + row + '\nTrạng thái: ' + (status || '(trống)') + '\nGhi chú: ' + (note || '(trống)')) : 'Chưa có lần gửi nào trong tab pre-order.') +
      '\n\nHạn mức gửi email còn lại hôm nay: ' + MailApp.getRemainingDailyQuota());
  } catch (e) {
    ui.alert('Không kiểm tra được: ' + ((e && e.message) || String(e)));
  }
}

function _taoFormPreorder(props) {
  const form = FormApp.create('HVHN — Xác nhận slot nhóm học tập');
  form.setDescription('Form dành cho khách đã được HVHN xác nhận slot trước đó. Điền đúng họ tên và email đã đăng ký để nhận link tham gia Discord riêng qua email.');
  form.addTextItem().setTitle('Họ và tên').setRequired(true);
  form.addTextItem().setTitle('Email nhận link Discord').setRequired(true).setValidation(_emailTextValidation());
  form.setConfirmationMessage('HVHN đã nhận thông tin. Nếu email của bạn nằm trong danh sách pre-order đã xác nhận, link Discord riêng sẽ được gửi vào email này trong ít phút. Vui lòng kiểm tra cả mục Spam.');
  form.setAcceptingResponses(true);
  _ensureSingleFormTrigger('xuLyFormPreorder', form);
  props.setProperty(PREORDER_FORM_ID_PROP, form.getId());
  return form;
}

function taoLaiFormPreorder() {
  const props = PropertiesService.getScriptProperties();
  let form = _openFormIfAlive(props.getProperty(PREORDER_FORM_ID_PROP));
  if (!form) form = _taoFormPreorder(props);
  _ensureFormEmailValidation(form);
  _ensureSingleFormTrigger('xuLyFormPreorder', form);
  const cfg = _preorderSourceConfig();
  let sourceStatus = cfg.spreadsheetId ? 'đã kết nối sheet responses cũ' : 'chưa kết nối sheet responses cũ';
  let count = 0;
  if (cfg.spreadsheetId) count = _preorderEmailsFromSourceSheet().length;
  const msg = 'Form xác nhận slot pre-order:\n\n' + form.getPublishedUrl() + '\n\nAllowlist: ' + sourceStatus + ', hiện đọc được ' + count + ' email. Chỉ email có trong sheet responses cũ mới nhận invite Discord.';
  Logger.log(msg); SpreadsheetApp.getUi().alert(msg);
}

function _preorderSendInviteEmail(email, name, inviteUrl) {
  const buildMessage = function(materials) {
    const body = 'Chào ' + name + ',\n\nHVHN đã xác nhận slot nhóm học tập của bạn. Bấm link sau để tham gia Discord: ' + inviteUrl + _customerOnboardingPlainText(materials) + '\n\nSau khi vào Discord, hãy vào kênh #truy-cập-tài-liệu và bấm “Kích hoạt quyền truy cập tài liệu” để điền Họ tên + Email. Khi hoàn tất, hệ thống sẽ tiếp tục cấp học liệu theo quy trình của HVHN.\n\nTrân trọng,\nHVHN · Hồn Văn, Hồn Người';
    const html = '<div style="max-width:620px;margin:auto;font-family:Arial,sans-serif;color:#202124;line-height:1.6">' +
      '<h2 style="margin:0 0 8px;color:#6a1b9a">HVHN · Xác nhận slot nhóm học tập</h2>' +
      '<p>Chào <strong>' + _pmtEsc(name) + '</strong>,</p>' +
      '<p>HVHN đã xác nhận slot nhóm học tập của bạn. Bấm nút dưới đây để tham gia cộng đồng Discord HVHN.</p>' +
      '<p style="text-align:center;margin:24px 0"><a href="' + _pmtEsc(inviteUrl) + '" style="display:inline-block;padding:12px 20px;background:#5865F2;color:#fff;text-decoration:none;border-radius:6px;font-weight:bold">Tham gia Discord HVHN</a></p>' +
      _customerOnboardingHtml(materials) +
      '<p>Sau khi vào Discord, hãy vào kênh <strong>#truy-cập-tài-liệu</strong> và bấm <strong>“Kích hoạt quyền truy cập tài liệu”</strong> để điền Họ tên + Email. Khi hoàn tất, hệ thống sẽ tiếp tục cấp học liệu theo quy trình của HVHN.</p>' +
      '<p style="font-size:13px;color:#5f6368">Link mời là link riêng, có giới hạn sử dụng. Nếu cần hỗ trợ, hãy phản hồi email này để được hỗ trợ.</p>' +
      '<p>Trân trọng,<br><strong>HVHN · Hồn Văn, Hồn Người</strong></p></div>';
    return { to: email, subject: '[HVHN] Link tham gia nhóm học tập của bạn', body: body, htmlBody: html, name: 'HVHN' };
  };
  return _sendCustomerAccessEmail(buildMessage, _customerOnboardingMaterials());
}

function _preorderFindRowByEmail(sheet, email) {
  const last = sheet.getLastRow();
  if (last < 2) return 0;
  const emails = sheet.getRange(2, 3, last - 1, 1).getValues();
  for (let i = 0; i < emails.length; i++) {
    if (String(emails[i][0] || '').trim().toLowerCase() === email) return i + 2;
  }
  return 0;
}

// Form submit: mỗi email allowlist CHỈ được submit một lần. Lượt submit thứ hai
// bị từ chối, kể cả khi nhiều người cùng dùng chung một hộp thư. Nếu khách cần
// hỗ trợ, quản lý dùng nút gửi lại link trong tab _khach_preorder, không mở lại Form.
// Bot vẫn lưu pending member nên khách bấm invite rồi kích hoạt ở #truy-cập-tài-liệu như luồng thường.
const PREORDER_STALE_MINUTES = 2;
const PREORDER_FAST_TRIGGER_HANDLER = 'xuLyDonPreorderNhanh';
const PREORDER_FAST_DELAY_MS = 10000;
const PREORDER_MAX_AUTO_RETRIES = 3;

function _preorderIsStale(lastAttemptAt) {
  const created = new Date(lastAttemptAt);
  return !isNaN(created.getTime()) && (_now().getTime() - created.getTime()) >= PREORDER_STALE_MINUTES * 60000;
}

function _preorderMarkFailure(sheet, row, status, error) {
  sheet.getRange(row, 5).setValue(status);
  sheet.getRange(row, 8).setValue(String((error && error.message) || error || '').slice(0, 500));
}

function _preorderRetryInfo(note) {
  const text = String(note || '');
  const count = Number((text.match(/retry=(\d+)/) || [])[1] || 0);
  const when = (text.match(/retry_after=([^;\s]+)/) || [])[1] || '';
  return { count: count, when: when };
}

function _preorderRetryDue(status, note, createdAt) {
  if (status === 'cho_tao_invite') return true;
  if (status === 'dang_tao_invite') {
    return _preorderIsStale(String(note || '').replace(/^worker_bat_dau\s+/, '') || createdAt);
  }
  if (status !== 'loi_tao_invite' && status !== 'loi_gui_email') return false;
  const retry = _preorderRetryInfo(note);
  if (!retry.when) return false;
  const due = new Date(retry.when);
  return !isNaN(due.getTime()) && due.getTime() <= _now().getTime();
}

function _ensurePreorderWorkerTrigger() {
  if (_coTrigger('xuLyDonPreorderTuDong')) return;
  ScriptApp.newTrigger('xuLyDonPreorderTuDong').timeBased().everyMinutes(1).create();
  ghiLog('Tự chữa trigger pre-order', 'Đã cài worker mỗi 1 phút');
}

// Ưu tiên relay sang Web App để trigger thuộc đúng tài khoản chủ automation.
// Nếu Web App đang tạm thời không phản hồi, vẫn thử scheduler cục bộ làm dự phòng.
function _schedulePreorderWorkerSoon(delayMs) {
  try {
    if (_relayPreorderWorkerToDeploymentOwner()) return;
  } catch (relayError) {
    ghiLog('LỖI relay worker pre-order', (relayError && relayError.message) || String(relayError));
  }
  try {
    _ensurePreorderWorkerTrigger();
    const hasFast = ScriptApp.getProjectTriggers().some(t => t.getHandlerFunction() === PREORDER_FAST_TRIGGER_HANDLER);
    if (!hasFast) {
      ScriptApp.newTrigger(PREORDER_FAST_TRIGGER_HANDLER)
        .timeBased()
        .after(Math.max(1000, Number(delayMs) || PREORDER_FAST_DELAY_MS))
        .create();
    }
  } catch (e) {
    ghiLog('LỖI lên lịch worker pre-order', (e && e.message) || String(e));
  }
}

function xuLyDonPreorderNhanh() {
  // Đây là trigger một lần; tự dọn trước khi xử lý để không tiêu quota trigger.
  ScriptApp.getProjectTriggers().forEach(t => {
    if (t.getHandlerFunction() === PREORDER_FAST_TRIGGER_HANDLER) ScriptApp.deleteTrigger(t);
  });
  xuLyDonPreorderTuDong();
}

function _preorderScheduleFailure(sheet, row, status, error) {
  const previous = _preorderRetryInfo(sheet.getRange(row, 8).getValue());
  const retryCount = previous.count + 1;
  const detail = String((error && error.message) || error || '').slice(0, 420);
  if (retryCount > PREORDER_MAX_AUTO_RETRIES) {
    _preorderMarkFailure(sheet, row, 'can_admin_ho_tro', 'retry=' + previous.count + '; ' + detail);
    return;
  }
  const retryAt = new Date(_now().getTime() + PREORDER_FAST_DELAY_MS);
  _preorderMarkFailure(sheet, row, status,
    'retry=' + retryCount + '; retry_after=' + retryAt.toISOString() + '; ' + detail);
  _schedulePreorderWorkerSoon(PREORDER_FAST_DELAY_MS);
}

function _preorderRecordRejected(name, email, status, note) {
  const sheet = _preorderSheet();
  const cleanEmail = String(email || '').trim().toLowerCase();
  const existing = _isValidEmail(cleanEmail) ? _preorderFindRowByEmail(sheet, cleanEmail) : 0;
  if (existing) {
    _preorderMarkFailure(sheet, existing, status, note);
    return existing;
  }
  const code = _preorderCode(cleanEmail || ('invalid-' + Date.now()));
  sheet.appendRow([new Date(), String(name || '').trim(), cleanEmail, code, status, '', '', String(note || '')]);
  return sheet.getLastRow();
}

// Chạy bằng trigger riêng để Form submit không bị treo khi bot/Render đang khởi động.
// Dòng đang tạo quá lâu được thử lại an toàn: endpoint bot idempotent theo mã pre-order.
function xuLyDonPreorderTuDong() {
  const lock = LockService.getScriptLock();
  if (!lock.tryLock(1000)) return;
  try {
    const sheet = _preorderSheet();
    const last = sheet.getLastRow();
    if (last < 2) return;
    const rows = sheet.getRange(2, 1, last - 1, 8).getValues();
    for (let i = 0; i < rows.length; i++) {
      const row = i + 2;
      const name = String(rows[i][1] || '').trim();
      const email = String(rows[i][2] || '').trim().toLowerCase();
      const code = String(rows[i][3] || _preorderCode(email)).trim();
      const status = String(rows[i][4] || '');
      const note = String(rows[i][7] || '');
      const shouldProcess = _preorderRetryDue(status, note, rows[i][0]);
      if (!shouldProcess) continue;

      if (!_isValidPersonName(name) || !_isValidEmail(email)) {
        _preorderMarkFailure(sheet, row, 'loi_du_lieu', 'Tên hoặc email không hợp lệ.');
        continue;
      }

      let stage = 'tao_invite';
      try {
        sheet.getRange(row, 4).setValue(code);
        sheet.getRange(row, 5).setValue('dang_tao_invite');
        sheet.getRange(row, 8).setValue('worker_bat_dau ' + new Date().toISOString());
        const out = _pmtMintInvite(code, name, email);
        if (!out.invite_url) throw new Error(out.error || 'Không tạo được invite Discord.');
        sheet.getRange(row, 5).setValue('dang_gui_email');
        stage = 'gui_email';
        const mailResult = _preorderSendInviteEmail(email, name, out.invite_url);
        sheet.getRange(row, 5).setValue('da_gui_link');
        sheet.getRange(row, 6).setValue(out.invite_url);
        sheet.getRange(row, 7).setValue(new Date());
        sheet.getRange(row, 8).setValue((out.reused ? 'gui_lai_invite_cu' : 'invite_moi') + '; mail=' + mailResult);
        ghiLog('Đã cấp link Discord pre-order', code + ' - ' + name + ' - ' + email);
      } catch (e) {
        _preorderScheduleFailure(sheet, row, stage === 'gui_email' ? 'loi_gui_email' : 'loi_tao_invite', e);
        ghiLog('LỖI worker pre-order', code + ' - ' + ((e && e.message) || String(e)));
      }
      return; // Mỗi lượt chỉ xử lý 1 đơn để tránh chuỗi request mạng kéo dài.
    }
  } finally {
    lock.releaseLock();
  }
}

function xuLyFormPreorder(e) {
  const lock = LockService.getScriptLock();
  lock.waitLock(30000);
  try {
    let name = '', email = '';
    e.response.getItemResponses().forEach(it => {
      const title = it.getItem().getTitle().toLowerCase();
      if (title.indexOf('tên') >= 0) name = String(it.getResponse()).trim();
      else if (title.indexOf('email') >= 0) email = String(it.getResponse()).trim().toLowerCase();
    });
    if (!_isValidPersonName(name) || !_isValidEmail(email)) {
      _preorderRecordRejected(name, email, 'tu_choi_du_lieu', 'Tên hoặc email không hợp lệ.');
      ghiLog('Từ chối Form pre-order (tên/email không hợp lệ)', name + ' - ' + email);
      return;
    }
    const allowed = _preorderAllowedEmails();
    if (!allowed[email]) {
      _preorderRecordRejected(name, email, 'tu_choi_allowlist', 'Email không có trong sheet responses cũ.');
      ghiLog('Từ chối Form pre-order (email không có trong sheet responses cũ)', email);
      return;
    }
    const sheet = _preorderSheet();
    const code = _preorderCode(email);
    let row = _preorderFindRowByEmail(sheet, email);
    if (row) {
      ghiLog('Từ chối Form pre-order (đã submit)', code + ' - ' + email);
      return;
    }
    row = sheet.getLastRow() + 1;
    sheet.getRange(row, 1, 1, 8).setValues([[new Date(), name, email, code, 'cho_tao_invite', '', '', '']]);
    _schedulePreorderWorkerSoon(PREORDER_FAST_DELAY_MS);
    ghiLog('Đã nhận pre-order, chờ tạo invite', code + ' - ' + name + ' - ' + email);
  } catch (err) {
    ghiLog('LỖI Form pre-order', (err && err.message) || String(err));
    throw err;
  } finally {
    lock.releaseLock();
  }
}

function guiLaiLinkDiscordChoPreorderDangChon() {
  const sheet = SpreadsheetApp.getActiveSpreadsheet().getActiveSheet();
  if (sheet.getName() !== PREORDER_TAB || sheet.getActiveRange().getRow() <= 1) {
    SpreadsheetApp.getUi().alert('Hãy chọn một dòng khách trong tab ' + PREORDER_TAB + '.'); return;
  }
  const row = sheet.getActiveRange().getRow();
  const values = sheet.getRange(row, 1, 1, 8).getValues()[0];
  const name = String(values[1] || '').trim(), email = String(values[2] || '').trim().toLowerCase();
  const code = String(values[3] || _preorderCode(email)).trim();
  if (!_isValidPersonName(name) || !_isValidEmail(email)) {
    SpreadsheetApp.getUi().alert('Dòng này có tên hoặc email không hợp lệ.'); return;
  }
  sheet.getRange(row, 4).setValue(code);
  sheet.getRange(row, 5).setValue('cho_tao_invite');
  sheet.getRange(row, 8).setValue('yeu_cau_gui_lai ' + new Date().toISOString());
  _schedulePreorderWorkerSoon(PREORDER_FAST_DELAY_MS);
  ghiLog('Xếp hàng gửi lại link Discord pre-order', code + ' - ' + email);
  SpreadsheetApp.getUi().alert('Đã xếp hàng gửi lại link. Hệ thống sẽ thử xử lý sau khoảng 10 giây; trigger 1 phút là đường dự phòng. Nếu lỗi, trạng thái và lý do sẽ hiện ngay trên dòng này.');
}
