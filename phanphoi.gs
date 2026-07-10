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
const XOA_KHACH_NAME = '_don_xoa_khach';
const XOA_TAILIEU_NAME = '_don_xoa_tai_lieu';
const SHEET_XOA_KHACH_NAME = '_don_sheet_xoa_khach';
const SHEET_XOA_TAILIEU_NAME = '_don_sheet_xoa_tai_lieu';
const SHEET_GIAHAN_KHACH_NAME = '_don_sheet_giahan_khach';
const SHEET_STATUS_NAME = '_sheet_status';
const SHEET_STATUS_FILE = 'sheet_status.json';
const BOT_ONLY_DOC_PREFIXES = ['discord'];

// Tab không phải dữ liệu khách -> luôn bỏ qua khi quét
function isSystemTab(name) {
  return name === DASHBOARD_NAME || name === STAGING_NAME || name === REGISTRY_NAME
      || name === DOCS_NAME || name === LOG_NAME;
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
    .addItem('📝 Nhập mới thủ công (tab "Nhập mới") + Phân phối', 'themMoiVaPhanPhoi')
    .addItem('🔁 Phân phối lại (quét toàn bộ)', 'phanPhoi')
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
      .addItem('Tạo Google Form cho điện thoại', 'caiDatForm'))
    .addToUi();
}

// Tự chạy khi người dùng sửa ô: tìm kiếm Dashboard, hoặc tick ô Gia hạn ở tab Khách hàng.
function onEdit(e) {
  const sheet = e.range.getSheet();
  const name = sheet.getName();
  if (name === DASHBOARD_NAME && e.range.getA1Notation() === SEARCH_CELL) {
    capNhatDashboard();
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
  }
}

function ensureDashboard() {
  const ss = SpreadsheetApp.getActiveSpreadsheet();
  let dash = ss.getSheetByName(DASHBOARD_NAME);
  if (!dash) {
    dash = ss.insertSheet(DASHBOARD_NAME, 0);
    capNhatDashboard();
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

  for (let i = 1; i < data.length; i++) {
    const name = data[i][0];
    if (!name) continue;
    if (!groups[name]) groups[name] = [header];
    groups[name].push(data[i]);
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

    let sheet = ss.getSheetByName(name);
    if (!sheet) {
      sheet = ss.insertSheet(name);
      sheet.getRange(1, 1, 1, 4).setValues([['TenNguoiNhan', 'Email', 'TenFile', 'TrangThai']]);
    }

    const lastRow = sheet.getLastRow();
    const existing = lastRow > 1
      ? sheet.getRange(2, 3, lastRow - 1, 1).getValues().flat()
      : [];
    if (existing.includes(fileName)) return; // đã có rồi, khỏi thêm trùng

    sheet.getRange(sheet.getLastRow() + 1, 1, 1, 3).setValues([[name, email, fileName]]);
    added++;
  });
  return added;
}

// TỰ ĐỘNG HOÀN TOÀN: quét folder Source trên Drive tìm mọi file tên "new_rows.csv"
// (Claude hoặc app khác có thể tự tạo file này lên Drive không cần đụng vào Sheet),
// đọc nội dung, gộp vào đúng tab khách, xoá file đã xử lý, rồi phân phối + cập nhật Dashboard.
// Gắn hàm này vào 1 Trigger chạy theo giờ (Triggers > Add Trigger > Time-driven) để tự chạy định kỳ,
// khỏi cần mở Sheet lên bấm gì cả.
function tuDongXuLyFileMoi() {
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
  // LUÔN chạy phanPhoi: dòng "Xong" tự bỏ qua; dòng "Không thấy file" (do PDF upload chưa
  // kịp lần trước) sẽ được thử lại ở lần trigger sau — tự chữa lành, không kẹt.
  phanPhoi();
}

// TRIGGER 5 PHÚT: gom toàn bộ việc cần tự động hoá vào 1 hàm duy nhất.
// Chạy vô hại nhiều lần: dòng đã Xong bỏ qua, tick đã xử lý thì tự mất/xoá dòng.
function hvhnTuDongHoa() {
  const lock = LockService.getScriptLock();
  if (!lock.tryLock(1000)) return;
  try {
    tuDongXuLyFileMoi();      // kéo new_rows*.csv + phân phối + sync khách/dashboard
    xuLyGiaHanTuDong();       // tick Gia hạn -> tự gia hạn, nếu cần thì phân phối lại
    xuLyLenhGiaHanDiscordTuDong(); // lệnh gia hạn từ Discord
    kiemTraHetHan();          // quá hạn -> tự gỡ quyền/xoá file
    xuLyLenhDiscordTuDong();  // lệnh xoá từ Discord -> xoá Sheet/Drive thật
    donTaiLieuBotOnlyKhoKhachTuDong(); // tài liệu bot-only lỡ lọt kho khách -> gỡ khỏi Sheet/Drive
    xoaKhachDaTichTuDong();   // tick Xóa khách -> tự xoá, không cần bấm menu
    xoaTaiLieuDaTichTuDong(); // tick Xóa tài liệu -> tự xoá, không cần bấm menu
    capNhatTaiLieu();         // tab Tài liệu luôn mới
    capNhatDashboard();       // dashboard luôn mới
  } catch (e) {
    ghiLog('LỖI tự động hoá', e.message || String(e));
    throw e;
  } finally {
    lock.releaseLock();
  }
}

// Chạy 1 lần sau khi dán code: tạo đủ trigger tự động, xoá trigger cũ trùng để tránh chạy lặp.
function caiDatTuDongHoa() {
  const ss = SpreadsheetApp.getActiveSpreadsheet();
  const keepHandlers = {
    hvhnTuDongHoa: true,
    tuDongXuLyFileMoi: true,
    kiemTraHetHan: true,
  };
  ScriptApp.getProjectTriggers().forEach(t => {
    if (keepHandlers[t.getHandlerFunction()]) ScriptApp.deleteTrigger(t);
  });

  ScriptApp.newTrigger('hvhnTuDongHoa')
    .timeBased()
    .everyMinutes(5)
    .create();

  ScriptApp.newTrigger('kiemTraHetHan')
    .timeBased()
    .atHour(1)
    .everyDays(1)
    .create();

  ensureDashboard();
  ensureStaging();
  ensureRegistry();
  capNhatTaiLieu();
  capNhatDashboard();
  ghiLog('Cài tự động hoá', 'hvhnTuDongHoa mỗi 5 phút; kiemTraHetHan hằng ngày 1h');
  ss.toast('Đã cài tự động hoá. Từ giờ không cần bấm menu để cập nhật sheet.');
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
function phanPhoi() {
  const ss = SpreadsheetApp.getActiveSpreadsheet();
  const sourceFolder = DriveApp.getFolderById(SOURCE_FOLDER_ID);
  const destRoot = DriveApp.getFolderById(DEST_ROOT_FOLDER_ID);

  ss.getSheets().forEach(sheet => {
    if (isSystemTab(sheet.getName())) return;

    const data = sheet.getDataRange().getValues();
    if (!data.length || data[0][0] !== 'TenNguoiNhan') return;

    const seen = {}; // chống trùng dòng trong cùng 1 tab
    for (let i = 1; i < data.length; i++) {
      const [name, email, fileName, status] = data[i];
      if (!name || !email || !fileName || String(status || '').startsWith('Xong')) continue;
      if (_isBotOnlyDocFileName(fileName)) {
        sheet.getRange(i + 1, 4).setValue('Bot-only (không phân phối)');
        continue;
      }
      if (seen[fileName]) {         // dòng lặp trong tab -> đánh dấu, không xử lý lại
        sheet.getRange(i + 1, 4).setValue('Trùng (bỏ qua)');
        continue;
      }
      seen[fileName] = true;

      try {
        const destFolder = getOrCreateFolder(destRoot, name);
        _ensureOnlyViewer(destFolder, email);

        // IDEMPOTENT: nếu folder đích đã có file cùng tên -> dùng lại, KHÔNG copy thêm bản mới
        let target;
        const existingDest = destFolder.getFilesByName(fileName);
        if (existingDest.hasNext()) {
          target = existingDest.next();
        } else {
          const srcFiles = sourceFolder.getFilesByName(fileName);
          if (!srcFiles.hasNext()) {
            sheet.getRange(i + 1, 4).setValue('Không thấy file: ' + fileName);
            continue;
          }
          target = srcFiles.next().makeCopy(fileName, destFolder);
        }

        // Chỉ share nếu email CHƯA có quyền -> tránh gửi lại mail thông báo mỗi lần chạy
        _ensureOnlyViewer(target, email);
        // Khoá tải/in/copy: nếu Advanced Drive Service chưa bật thì bỏ qua, KHÔNG chặn "Xong"
        try {
          Drive.Files.update({ copyRequiresWriterPermission: true }, target.getId());
        } catch (e2) { /* thiếu Drive service - vẫn share được, chỉ là chưa khoá tải */ }

        sheet.getRange(i + 1, 4).setValue('Xong: ' + target.getUrl());
      } catch (e) {
        sheet.getRange(i + 1, 4).setValue('Lỗi: ' + e.message);
      }
    }
    decorateSheet(sheet);
  });

  dongBoKhachHang();   // cập nhật danh sách khách + set ngày cấp/hết hạn cho khách mới
  capQuyenFolderKhachHangTuDong();
  capNhatDashboard();
}

// ============ DASHBOARD (tổng quan + tìm kiếm) ============

function capNhatDashboard() {
  const ss = SpreadsheetApp.getActiveSpreadsheet();
  let dash = ss.getSheetByName(DASHBOARD_NAME);
  if (!dash) dash = ss.insertSheet(DASHBOARD_NAME, 0);

  const searchTerm = (dash.getRange(SEARCH_CELL).getValue() || '').toString().trim().toLowerCase();
  dash.getRange('A4:Z999').clearContent();

  const destRoot = DriveApp.getFolderById(DEST_ROOT_FOLDER_ID);
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
    const foundFolders = destRoot.getFoldersByName(name);
    if (foundFolders.hasNext()) folderUrl = foundFolders.next().getUrl();

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
  xuatTrangThaiSheet();
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

      const folders = destRoot.getFoldersByName(name);
      if (folders.hasNext()) _ensureOnlyViewer(folders.next(), email);
      break;
    }
  });
}

function capQuyenFolderKhachHang() {
  capQuyenFolderKhachHangTuDong();
  SpreadsheetApp.getActiveSpreadsheet().toast('Đã cấp quyền xem folder cho các khách đang có folder Drive.');
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
      if (data[i][0] && data[i][1]) clients[data[i][0]] = data[i][1];
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
    if (folders.hasNext()) {
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
      const hours = amount > 0 ? (unit === 'h' ? amount : amount * 24) : SUB_HOURS;
      const found = _timKhachTheoEmail(ss, email);
      if (!found) {
        ghiLog('Discord gia hạn - không tìm thấy', email);
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
    reg.getRange(2, 3, n, 2).setNumberFormat('dd/mm/yyyy hh:mm'); // cột ngày (có giờ)
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

// Cap dung 1 quyen cho khach: viewer tren folder/file, khong editor.
function _ensureOnlyViewer(item, email) {
  const lower = String(email || '').trim().toLowerCase();
  if (!lower) return;

  try {
    const editors = item.getEditors().map(u => u.getEmail().toLowerCase());
    if (editors.indexOf(lower) >= 0) item.removeEditor(email);
  } catch (e) {}

  try {
    const viewers = item.getViewers().map(u => u.getEmail().toLowerCase());
    const editors = item.getEditors().map(u => u.getEmail().toLowerCase());
    if (viewers.indexOf(lower) < 0 && editors.indexOf(lower) < 0) item.addViewer(email);
  } catch (e) {}
}

function _removeAccess(item, email) {
  const lower = String(email || '').trim().toLowerCase();
  if (!lower) return;

  try {
    const viewers = item.getViewers().map(u => u.getEmail().toLowerCase());
    if (viewers.indexOf(lower) >= 0) item.removeViewer(email);
  } catch (e) {}

  try {
    const editors = item.getEditors().map(u => u.getEmail().toLowerCase());
    if (editors.indexOf(lower) >= 0) item.removeEditor(email);
  } catch (e) {}
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

  const destRoot = DriveApp.getFolderById(DEST_ROOT_FOLDER_ID);
  // xoá tab trước sẽ làm dịch dòng registry -> xoá registry theo thứ tự giảm dần, xử Drive/tab luôn
  targets.sort((a, b) => b.row - a.row);
  targets.forEach(t => {
    _xoaMotKhach(ss, destRoot, t.name, t.email);
    reg.deleteRow(t.row);
  });
  decorateRegistry(reg);
  capNhatDashboard();
  ui.alert('Đã xoá ' + targets.length + ' khách.');
}

// Bản tự động: tick cột H là xoá trong vòng chạy trigger kế tiếp, không cần bấm menu.
function xoaKhachDaTichTuDong() {
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
  vals.forEach(row => { if (row[0]) _xoaMotKhach(ss, destRoot, row[0], row[1]); });
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

  sh.clear();
  sh.getRange(1, 1, 1, 3).setValues([['Tên tài liệu', 'Số khách đang có', 'Xóa tài liệu']]);
  const names = Object.keys(count).sort();
  if (names.length) {
    sh.getRange(2, 1, names.length, 2).setValues(names.map(n => [n, count[n]]));
    sh.getRange(2, 3, names.length, 1).insertCheckboxes();
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
        if (folders.hasNext()) {
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

// Tạo mới form THÊM KHÁCH + gắn trigger + lưu ID. Trả về form.
function _taoFormKhach(props) {
  const form = FormApp.create('HVHN — Thêm khách mới');
  form.setDescription('Nhập họ tên và email học viên để cấp tài liệu (gói 1 tháng). Hệ thống tự đóng dấu + gửi tài liệu.');
  form.addTextItem().setTitle('Họ và tên học viên').setRequired(true);
  form.addTextItem().setTitle('Email (Gmail) học viên').setRequired(true);
  form.setConfirmationMessage('Đã nhận! Tài liệu sẽ được gửi sau khi hệ thống xử lý.');
  form.setAcceptingResponses(true);
  ScriptApp.newTrigger('xuLyFormKhach').forForm(form).onFormSubmit().create();
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
  ScriptApp.newTrigger('xuLyFormTaiLieuBot').forForm(form).onFormSubmit().create();
  props.setProperty('FORM_BOT_TL_ID', form.getId());
  return form;
}

// Menu: tạo lại RIÊNG form thêm khách (khi lỡ xoá/hỏng), không đụng form tài liệu.
function taoLaiFormKhach() {
  const props = PropertiesService.getScriptProperties();
  const form = _taoFormKhach(props);
  const msg = 'Đã tạo lại Form THÊM KHÁCH. Gửi link này cho quản lý:\n\n' + form.getPublishedUrl();
  Logger.log(msg);
  SpreadsheetApp.getUi().alert(msg);
}

function taoLaiFormBot() {
  const props = PropertiesService.getScriptProperties();
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
    + 'Quy ước soạn .md: dùng heading (#, ##, ...) để tách từng đoạn/mục; trích dẫn ghi theo dạng '
    + '> "…nội dung trích dẫn…" — Tác giả (mỗi trích dẫn 1 dòng blockquote riêng).');
  form.addTextItem().setTitle('Tên tài liệu (tuỳ chọn, để trống sẽ dùng tên file)');
  // Apps Script không tạo được câu hỏi upload file bằng code -> thêm tay 1 lần trong link sửa form.
  form.setConfirmationMessage('Đã nhận file. Bot sẽ đọc sau khi watcher trên PC xử lý.');
  form.setAcceptingResponses(true);
  ScriptApp.newTrigger('xuLyFormMd').forForm(form).onFormSubmit().create();
  props.setProperty('FORM_MD_ID', form.getId());
  return form;
}

// Menu: tạo lại RIÊNG form nạp .md cho bot (khi lỡ xoá/hỏng), không đụng các form khác.
function taoLaiFormMd() {
  const props = PropertiesService.getScriptProperties();
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

  // --- Form 2: THÊM TÀI LIỆU ---
  let formTL = _openFormIfAlive(props.getProperty('FORM_TL_ID'));
  if (!formTL) {
    formTL = FormApp.create('HVHN — Thêm tài liệu mới');
    formTL.setDescription('Tải lên file PDF tài liệu mới. Hệ thống tự đóng dấu tên từng khách + gửi cho TẤT CẢ khách đang còn hạn.');
    formTL.addTextItem().setTitle('Tên tài liệu (tuỳ chọn, để trống sẽ dùng tên file)');
    // LƯU Ý: Apps Script KHÔNG tạo được câu hỏi upload file bằng code -> phải thêm tay 1 lần.
    formTL.setConfirmationMessage('Đã nhận file! Hệ thống sẽ đóng dấu và phân phối.');
    formTL.setAcceptingResponses(true);
    ScriptApp.newTrigger('xuLyFormTaiLieu').forForm(formTL).onFormSubmit().create();
    props.setProperty('FORM_TL_ID', formTL.getId());
  }

  // --- Form 3: NẠP TÀI LIỆU CHO BOT AI ---
  let formBotTL = _openFormIfAlive(props.getProperty('FORM_BOT_TL_ID'));
  if (!formBotTL) formBotTL = _taoFormBot(props);

  props.setProperty('JOBS_KHACH_ID', jobsFolder.getId());
  props.setProperty('INCOMING_DOCS_ID', incomingFolder.getId());
  props.setProperty('BOT_DOCS_FORM_ID', botDocsFolder.getId());

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
  const props = PropertiesService.getScriptProperties();
  const jobsFolder = DriveApp.getFolderById(props.getProperty('JOBS_KHACH_ID'));
  let name = '', email = '';
  e.response.getItemResponses().forEach(it => {
    const t = it.getItem().getTitle().toLowerCase();
    if (t.indexOf('tên') >= 0) name = String(it.getResponse()).trim();
    else if (t.indexOf('email') >= 0) email = String(it.getResponse()).trim();
  });
  if (!name || !email) return;
  jobsFolder.createFile('khach_' + Date.now() + '.txt', name + '\t' + email, MimeType.PLAIN_TEXT);
}

// Handler khi có người submit Form "Thêm tài liệu": copy file PDF vào folder _don_them_tai_lieu.
function xuLyFormTaiLieu(e) {
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
  const parent = DriveApp.getFolderById(HVHN_PARENT_FOLDER_ID);
  const incoming = getOrCreateFolder(parent, INCOMING_BOT_MD_NAME);
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
    if (tenTL) newName = tenTL.replace(/[\\\/:*?"<>|]/g, '').trim() + '.md';
    if (!/\.md$/i.test(newName)) newName += '.md';
    f.makeCopy(newName, incoming);
  });
  ghiLog('Nạp .md cho bot', fileIds.length + ' file -> ' + INCOMING_BOT_MD_NAME);
}
