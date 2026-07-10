# Chương Trình Trải Nghiệm (Nhóm D) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development. Steps use `- [ ]`.

**Goal:** Chương trình dùng thử tài liệu 72h: watermark cố định "Nguyễn Văn A", phân phối vào 1 folder chung, có nút xóa cả chương trình.

**Architecture:** Python (`hvhn_batch.render_trial` + watcher handler) render PDF trải nghiệm với recipient cố định vào folder chung. Apps Script quản 2 tab (Khách/Tài liệu trải nghiệm), 2 Form riêng, cấp/gỡ quyền xem folder chung theo hạn 72h, nút xóa chương trình.

**Tech Stack:** Python, unittest; Google Apps Script (không test được ở máy — review bằng đọc + chủ deploy/test).

## Global Constraints

- Watermark trải nghiệm cố định: `TRIAL_NAME = "Nguyễn Văn A"`, `TRIAL_EMAIL = "nguyenvana@gmail.com"`, hạn `TRIAL_HOURS = 72`.
- Hệ hạn theo GIỜ (nhóm E: `_addHours`, `_hoursBetween`, `_fmtRemaining` đã có trong phanphoi.gs).
- `onEdit` KHÔNG gọi DriveApp; thao tác Drive qua menu/onFormSubmit/time-trigger.
- Câu hỏi upload PDF của Form phải thêm TAY 1 lần (Apps Script không tạo được `addFileUploadItem`).
- Không đụng hệ phân phối chính (per-client) và kho .md.
- Python test: `python -m unittest tests.<mod> -v` từ D:\Bothvhn.

---

### Task 1: Python — `render_trial` + watcher handler

**Files:**
- Modify: `hvhn_batch.py` (thêm `render_trial`), `watcher.py` (constants + `xu_ly_don_trai_nghiem` + loop)
- Test: `tests/test_trial_render.py` (mới)

**Interfaces:**
- Produces: `hvhn_batch.render_trial(doc_path, out_folder, *, name="Nguyễn Văn A", email="nguyenvana@gmail.com") -> str` (trả tên file `{name}__{doc}.pdf`, gọi `convert_to_secure_image_pdf` với recipient cố định); `watcher.xu_ly_don_trai_nghiem` (async); `watcher.INCOMING_TRIAL`, `watcher.TRIAL_SHARED`.

- [ ] **Step 1: Viết test (monkeypatch render nặng)**

Tạo `tests/test_trial_render.py`:

```python
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


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Chạy test — FAIL** (`AttributeError: render_trial`). `python -m unittest tests.test_trial_render -v`

- [ ] **Step 3: Thêm `render_trial` vào `hvhn_batch.py`** (sau `_render_job`):

```python
def render_trial(doc_path, out_folder, *, name="Nguyễn Văn A", email="nguyenvana@gmail.com"):
    doc_name = os.path.splitext(os.path.basename(doc_path))[0]
    file_name = f"{name}__{doc_name}.pdf"
    out_path = os.path.join(out_folder, file_name)
    os.makedirs(out_folder, exist_ok=True)
    convert_to_secure_image_pdf(
        doc_path, out_path,
        recipient_name=name,
        recipient_email=email,
        warning_text=WARNING_TEXT,
    )
    return file_name
```

- [ ] **Step 4: Chạy test — PASS.** `python -m unittest tests.test_trial_render -v`

- [ ] **Step 5: Thêm watcher handler.** Trong `watcher.py`:
  - Cạnh `INCOMING_BOT_MD` thêm:
    ```python
    INCOMING_TRIAL = os.path.join(MIRROR_PARENT, "_don_them_tai_lieu_trai_nghiem")
    TRIAL_SHARED = os.path.join(MIRROR_PARENT, "TÀI LIỆU TRẢI NGHIỆM")
    PROCESSED_TRIAL = os.path.join(MIRROR_PARENT, "_da_xu_ly_trai_nghiem")
    ```
  - Import: đảm bảo `from hvhn_batch import ... render_trial` (thêm `render_trial` vào danh sách import hvhn_batch hiện có).
  - Thêm hàm (cạnh `xu_ly_don_them_md`):
    ```python
    def xu_ly_don_trai_nghiem():
        if not os.path.isdir(INCOMING_TRIAL):
            return
        os.makedirs(PROCESSED_TRIAL, exist_ok=True)
        pdfs = [f for f in os.listdir(INCOMING_TRIAL) if f.lower().endswith(".pdf")]
        for pdf in pdfs:
            path = os.path.join(INCOMING_TRIAL, pdf)
            if not _stable(path):
                continue
            try:
                render_trial(path, TRIAL_SHARED)
                print(f"[TRAI NGHIEM] render {pdf} -> {TRIAL_SHARED}", flush=True)
                dest = _unique_path(PROCESSED_TRIAL, pdf)
                os.replace(path, dest)
            except Exception:
                traceback.print_exc()
    ```
  - Trong `main_async` loop, sau `await xu_ly_don_them_md()` thêm dòng đồng bộ: `xu_ly_don_trai_nghiem()` (hàm sync, không await).

- [ ] **Step 6: Test tĩnh watcher.** Thêm vào `tests/test_trial_render.py`:

```python
import inspect
import watcher


class WatcherTrialTest(unittest.TestCase):
    def test_watcher_has_trial_handler_and_loop(self):
        self.assertTrue(hasattr(watcher, "xu_ly_don_trai_nghiem"))
        self.assertTrue(hasattr(watcher, "INCOMING_TRIAL"))
        self.assertIn("xu_ly_don_trai_nghiem", inspect.getsource(watcher.main_async))
```

- [ ] **Step 7: Chạy test + import — PASS.** `python -m unittest tests.test_trial_render -v`; `python -c "import watcher, hvhn_batch"`

- [ ] **Step 8: Commit**

```bash
git add hvhn_batch.py watcher.py tests/test_trial_render.py
git commit -m "Add trial-program render with fixed watermark and watcher handler"
```

---

### Task 2: Apps Script — hằng + 2 tab + isSystemTab + submenu

**Files:** Modify `phanphoi.gs`.
**Interfaces:** hằng trải nghiệm; `ensureTraiNghiem()` tạo 2 tab + folder chung + folder đơn; `isSystemTab` bao 2 tab mới; submenu "🧪 Trải nghiệm".

- [ ] **Step 1:** Thêm hằng (cạnh các hằng đầu file, sau `INCOMING_BOT_MD_NAME`):

```javascript
const TRIAL_HOURS = 72;
const TRIAL_NAME = 'Nguyễn Văn A';
const TRIAL_EMAIL = 'nguyenvana@gmail.com';
const TRIAL_CLIENT_TAB = 'Khách trải nghiệm';
const TRIAL_DOC_TAB = 'Tài liệu trải nghiệm';
const TRIAL_SHARED_NAME = 'TÀI LIỆU TRẢI NGHIỆM';
const INCOMING_TRIAL_NAME = '_don_them_tai_lieu_trai_nghiem';
const TRIAL_DEL_COL = 7;      // cột G tab Khách trải nghiệm: ☑Xóa
const TRIAL_DOC_DEL_COL = 3;  // cột C tab Tài liệu trải nghiệm: ☑Xóa
```

- [ ] **Step 2:** Sửa `isSystemTab` bao 2 tab mới:

```javascript
function isSystemTab(name) {
  return name === DASHBOARD_NAME || name === STAGING_NAME || name === REGISTRY_NAME
      || name === DOCS_NAME || name === LOG_NAME
      || name === TRIAL_CLIENT_TAB || name === TRIAL_DOC_TAB;
}
```

- [ ] **Step 3:** Thêm `ensureTraiNghiem()` + helper folder chung:

```javascript
function _trialSharedFolder() {
  const parent = DriveApp.getFolderById(HVHN_PARENT_FOLDER_ID_EARLY);
  return getOrCreateFolder(parent, TRIAL_SHARED_NAME);
}

function ensureTraiNghiem() {
  const ss = SpreadsheetApp.getActiveSpreadsheet();
  let kh = ss.getSheetByName(TRIAL_CLIENT_TAB);
  if (!kh) kh = ss.insertSheet(TRIAL_CLIENT_TAB);
  kh.getRange(1, 1, 1, 7).setValues([[
    'Tên khách', 'Email', 'Ngày cấp', 'Ngày hết hạn', 'Còn lại', 'Trạng thái', 'Xóa'
  ]]);
  kh.getRange(1, 1, 1, 7).setBackground('#8e24aa').setFontColor('#fff').setFontWeight('bold');
  kh.setFrozenRows(1);
  if (kh.getLastRow() > 1) kh.getRange(2, TRIAL_DEL_COL, kh.getLastRow() - 1, 1).insertCheckboxes();

  let tl = ss.getSheetByName(TRIAL_DOC_TAB);
  if (!tl) tl = ss.insertSheet(TRIAL_DOC_TAB);
  tl.getRange(1, 1, 1, 3).setValues([['Tên tài liệu', 'Trạng thái', 'Xóa']]);
  tl.getRange(1, 1, 1, 3).setBackground('#8e24aa').setFontColor('#fff').setFontWeight('bold');
  tl.setFrozenRows(1);

  _trialSharedFolder(); // đảm bảo folder chung tồn tại
  ghiLog('Trải nghiệm', 'Đã đảm bảo tab + folder chương trình trải nghiệm');
}
```

- [ ] **Step 4:** Gọi `ensureTraiNghiem()` trong `onOpen` (cạnh `ensureRegistry()`).

- [ ] **Step 5:** Thêm submenu vào `onOpen` (trước `.addToUi()`):

```javascript
    .addSubMenu(ui.createMenu('🧪 Trải nghiệm')
      .addItem('Cập nhật danh sách tài liệu trải nghiệm', 'capNhatTaiLieuTraiNghiem')
      .addItem('Kiểm tra hết hạn khách trải nghiệm (ngay)', 'kiemTraHetHanTraiNghiem')
      .addItem('Xóa KHÁCH trải nghiệm đã tích', 'xoaKhachTraiNghiemDaTich')
      .addItem('Xóa TÀI LIỆU trải nghiệm đã tích', 'xoaTaiLieuTraiNghiemDaTich')
      .addSeparator()
      .addItem('🗑️ XÓA CẢ CHƯƠNG TRÌNH trải nghiệm', 'xoaChuongTrinhTraiNghiem')
      .addItem('📱 Tạo lại Form thêm khách trải nghiệm', 'taoLaiFormKhachTraiNghiem')
      .addItem('📱 Tạo lại Form thêm tài liệu trải nghiệm', 'taoLaiFormTaiLieuTraiNghiem'))
```

- [ ] **Step 6:** Kiểm cú pháp bằng mắt (ngoặc khớp, tên hàm menu sẽ định nghĩa ở Task 3-4). Commit `git add phanphoi.gs; git commit -m "Trial program: constants, tabs, and menu skeleton"`.

---

### Task 3: Apps Script — 2 Form trải nghiệm + handler

**Files:** Modify `phanphoi.gs`.
**Interfaces:** `taoLaiFormKhachTraiNghiem`, `taoLaiFormTaiLieuTraiNghiem`, `xuLyFormKhachTraiNghiem`, `xuLyFormTaiLieuTraiNghiem`.

- [ ] **Step 1:** Thêm Form + handler khách trải nghiệm (cấp quyền TRỰC TIẾP, không qua watcher):

```javascript
function taoLaiFormKhachTraiNghiem() {
  const props = PropertiesService.getScriptProperties();
  const form = FormApp.create('HVHN — Thêm khách TRẢI NGHIỆM');
  form.setDescription('Nhập họ tên + email để cấp quyền xem tài liệu trải nghiệm (72 giờ).');
  form.addTextItem().setTitle('Họ và tên').setRequired(true);
  form.addTextItem().setTitle('Email (Gmail)').setRequired(true);
  form.setConfirmationMessage('Đã nhận! Bạn sẽ được cấp quyền xem tài liệu trải nghiệm.');
  form.setAcceptingResponses(true);
  ScriptApp.newTrigger('xuLyFormKhachTraiNghiem').forForm(form).onFormSubmit().create();
  props.setProperty('FORM_KHACH_TN_ID', form.getId());
  const msg = 'Đã tạo Form THÊM KHÁCH TRẢI NGHIỆM. Link gửi quản lý:\n\n' + form.getPublishedUrl();
  Logger.log(msg); SpreadsheetApp.getUi().alert(msg);
}

// onFormSubmit (installable) -> được phép DriveApp. Thêm dòng + cấp quyền xem folder chung.
function xuLyFormKhachTraiNghiem(e) {
  let name = '', email = '';
  e.response.getItemResponses().forEach(it => {
    const t = it.getItem().getTitle().toLowerCase();
    if (t.indexOf('tên') >= 0) name = String(it.getResponse()).trim();
    else if (t.indexOf('email') >= 0) email = String(it.getResponse()).trim().toLowerCase();
  });
  if (!name || !email) return;
  ensureTraiNghiem();
  const ss = SpreadsheetApp.getActiveSpreadsheet();
  const kh = ss.getSheetByName(TRIAL_CLIENT_TAB);
  const now = _now();
  const expiry = _addHours(now, TRIAL_HOURS);
  kh.appendRow([name, email, now, expiry, '', 'Còn hạn', false]);
  const shared = _trialSharedFolder();
  try { shared.addViewer(email); } catch (err) { ghiLog('LỖI cấp quyền trải nghiệm', email + ' -> ' + err); }
  ghiLog('Thêm khách trải nghiệm', name + ' - ' + email);
}
```

- [ ] **Step 2:** Thêm Form + handler tài liệu trải nghiệm (copy PDF vào folder đơn):

```javascript
function taoLaiFormTaiLieuTraiNghiem() {
  const props = PropertiesService.getScriptProperties();
  const form = FormApp.create('HVHN — Thêm tài liệu TRẢI NGHIỆM');
  form.setDescription('Tải lên PDF cho chương trình trải nghiệm. Watermark cố định "Nguyễn Văn A", phân phối vào folder chung.');
  form.addTextItem().setTitle('Tên tài liệu (tuỳ chọn, để trống sẽ dùng tên file)');
  // Apps Script không tạo được câu hỏi upload -> thêm tay 1 câu "Tải tệp lên" trong link SỬA.
  form.setConfirmationMessage('Đã nhận file. Watcher trên PC sẽ đóng dấu + đưa vào folder chung.');
  form.setAcceptingResponses(true);
  ScriptApp.newTrigger('xuLyFormTaiLieuTraiNghiem').forForm(form).onFormSubmit().create();
  props.setProperty('FORM_TL_TN_ID', form.getId());
  const msg = 'Đã tạo Form THÊM TÀI LIỆU TRẢI NGHIỆM.\n\n'
    + 'Mở link SỬA thêm tay 1 câu "Tải tệp lên" (PDF):\n' + form.getEditUrl()
    + '\n\nLink GỬI quản lý: ' + form.getPublishedUrl();
  Logger.log(msg); SpreadsheetApp.getUi().alert(msg);
}

function xuLyFormTaiLieuTraiNghiem(e) {
  const parent = DriveApp.getFolderById(HVHN_PARENT_FOLDER_ID);
  const incoming = getOrCreateFolder(parent, INCOMING_TRIAL_NAME);
  let tenTL = '';
  let fileIds = [];
  e.response.getItemResponses().forEach(it => {
    const type = it.getItem().getType();
    if (type === FormApp.ItemType.FILE_UPLOAD) fileIds = fileIds.concat(it.getResponse());
    else if (type === FormApp.ItemType.TEXT) tenTL = String(it.getResponse()).trim();
  });
  fileIds.forEach(id => {
    const f = DriveApp.getFileById(id);
    let newName = f.getName();
    if (tenTL) newName = tenTL.replace(/[\\\/:*?"<>|]/g, '').trim() + '.pdf';
    if (!/\.pdf$/i.test(newName)) newName += '.pdf';
    f.makeCopy(newName, incoming);
  });
}
```

- [ ] **Step 3:** Kiểm cú pháp + tên hàm khớp menu Task 2. Commit `git add phanphoi.gs; git commit -m "Trial program: separate forms and submit handlers"`.

---

### Task 4: Apps Script — cập nhật/hết hạn/xóa + tích hợp trigger

**Files:** Modify `phanphoi.gs`.
**Interfaces:** `capNhatTaiLieuTraiNghiem`, `kiemTraHetHanTraiNghiem`, `xoaKhachTraiNghiemDaTich`, `xoaTaiLieuTraiNghiemDaTich`, `xoaChuongTrinhTraiNghiem`; gọi trong `hvhnTuDongHoa`.

- [ ] **Step 1:** Thêm 5 hàm:

```javascript
// Quét folder chung -> tab Tài liệu trải nghiệm + khóa tải từng file.
function capNhatTaiLieuTraiNghiem() {
  const ss = SpreadsheetApp.getActiveSpreadsheet();
  ensureTraiNghiem();
  const tl = ss.getSheetByName(TRIAL_DOC_TAB);
  const shared = _trialSharedFolder();
  const rows = [];
  const files = shared.getFiles();
  while (files.hasNext()) {
    const f = files.next();
    try { Drive.Files.update({ copyRequiresWriterPermission: true }, f.getId()); } catch (e2) {}
    rows.push([f.getName(), 'Trong chương trình', false]);
  }
  if (tl.getLastRow() > 1) tl.getRange(2, 1, tl.getLastRow() - 1, 3).clearContent();
  if (rows.length) {
    tl.getRange(2, 1, rows.length, 3).setValues(rows);
    tl.getRange(2, TRIAL_DOC_DEL_COL, rows.length, 1).insertCheckboxes();
  }
}

// Khách quá 72h -> gỡ quyền xem folder chung của RIÊNG khách đó.
function kiemTraHetHanTraiNghiem() {
  const ss = SpreadsheetApp.getActiveSpreadsheet();
  ensureTraiNghiem();
  const kh = ss.getSheetByName(TRIAL_CLIENT_TAB);
  const last = kh.getLastRow();
  if (last < 2) return;
  const now = _now();
  const shared = _trialSharedFolder();
  const vals = kh.getRange(2, 1, last - 1, 6).getValues();
  const out = [];
  for (let i = 0; i < vals.length; i++) {
    let [name, email, grant, expiry, remaining, status] = vals[i];
    if (email && expiry && status !== 'Đã gỡ (hết hạn)' && new Date(expiry).getTime() <= now.getTime()) {
      try { shared.removeViewer(String(email)); } catch (e) {}
      status = 'Đã gỡ (hết hạn)';
      ghiLog('Trải nghiệm hết hạn - gỡ quyền', name + ' - ' + email);
    }
    remaining = expiry ? _fmtRemaining(_hoursBetween(now, new Date(expiry))) : '';
    out.push([remaining, status]);
  }
  kh.getRange(2, 5, out.length, 2).setValues(out);
}

function xoaKhachTraiNghiemDaTich() {
  const ss = SpreadsheetApp.getActiveSpreadsheet();
  const kh = ss.getSheetByName(TRIAL_CLIENT_TAB);
  if (!kh || kh.getLastRow() < 2) return;
  const shared = _trialSharedFolder();
  const data = kh.getRange(2, 1, kh.getLastRow() - 1, 7).getValues();
  for (let i = data.length - 1; i >= 0; i--) {
    if (data[i][TRIAL_DEL_COL - 1] === true) {
      try { shared.removeViewer(String(data[i][1])); } catch (e) {}
      kh.deleteRow(i + 2);
      ghiLog('Xóa khách trải nghiệm', data[i][0] + ' - ' + data[i][1]);
    }
  }
}

function xoaTaiLieuTraiNghiemDaTich() {
  const ss = SpreadsheetApp.getActiveSpreadsheet();
  const tl = ss.getSheetByName(TRIAL_DOC_TAB);
  if (!tl || tl.getLastRow() < 2) return;
  const shared = _trialSharedFolder();
  const data = tl.getRange(2, 1, tl.getLastRow() - 1, 3).getValues();
  for (let i = data.length - 1; i >= 0; i--) {
    if (data[i][TRIAL_DOC_DEL_COL - 1] === true) {
      const fs = shared.getFilesByName(String(data[i][0]));
      while (fs.hasNext()) fs.next().setTrashed(true);
      tl.deleteRow(i + 2);
      ghiLog('Xóa tài liệu trải nghiệm', data[i][0]);
    }
  }
}

// Xóa CẢ chương trình: trash mọi file folder chung + gỡ mọi khách + clear 2 tab.
function xoaChuongTrinhTraiNghiem() {
  const ui = SpreadsheetApp.getUi();
  const resp = ui.alert('Xóa CẢ chương trình trải nghiệm?',
    'Sẽ xóa MỌI tài liệu trong folder chung, gỡ quyền MỌI khách trải nghiệm, và làm trống 2 tab. Không hoàn tác.',
    ui.ButtonSet.YES_NO);
  if (resp !== ui.Button.YES) return;
  const ss = SpreadsheetApp.getActiveSpreadsheet();
  const shared = _trialSharedFolder();
  // gỡ mọi khách
  const kh = ss.getSheetByName(TRIAL_CLIENT_TAB);
  if (kh && kh.getLastRow() > 1) {
    const emails = kh.getRange(2, 2, kh.getLastRow() - 1, 1).getValues();
    emails.forEach(r => { if (r[0]) { try { shared.removeViewer(String(r[0])); } catch (e) {} } });
    kh.getRange(2, 1, kh.getLastRow() - 1, 7).clearContent();
  }
  // trash mọi file
  const files = shared.getFiles();
  while (files.hasNext()) files.next().setTrashed(true);
  // clear tab tài liệu
  const tl = ss.getSheetByName(TRIAL_DOC_TAB);
  if (tl && tl.getLastRow() > 1) tl.getRange(2, 1, tl.getLastRow() - 1, 3).clearContent();
  ghiLog('XÓA CẢ CHƯƠNG TRÌNH trải nghiệm', 'đã trash tài liệu + gỡ mọi khách');
  ui.alert('Đã xóa cả chương trình trải nghiệm.');
}
```

- [ ] **Step 2:** Tích hợp vào `hvhnTuDongHoa` (trigger 5'): thêm 2 dòng cạnh các bước tự động khác:

```javascript
    kiemTraHetHanTraiNghiem();   // trải nghiệm quá 72h -> gỡ quyền
    capNhatTaiLieuTraiNghiem();  // đồng bộ tab tài liệu trải nghiệm
```

(Đặt trong khối try/hàm `hvhnTuDongHoa` hiện có, sau `kiemTraHetHan()`.)

- [ ] **Step 3:** Kiểm cú pháp toàn file bằng mắt (ngoặc/đóng hàm), mọi tên hàm menu (Task 2) + handler form (Task 3) đã có định nghĩa. Commit `git add phanphoi.gs; git commit -m "Trial program: sync, expiry, deletion, and trigger wiring"`.

---

## Self-Review

**Spec coverage:** render cố định + watcher (T1); tab + folder + menu (T2); form riêng + cấp quyền (T3); cập nhật/hết hạn 72h gỡ riêng + xóa chương trình + trigger (T4). ✔
**Placeholder scan:** không TBD; code Apps Script + Python đầy đủ.
**Type consistency:** `render_trial(doc_path,out_folder,*,name,email)->str`; hằng `TRIAL_*`, `TRIAL_CLIENT_TAB`/`TRIAL_DOC_TAB`, cột `TRIAL_DEL_COL=7`/`TRIAL_DOC_DEL_COL=3`; tên hàm menu (T2) khớp định nghĩa (T3/T4).
**Lưu ý:** Apps Script không test máy → review đọc kỹ (ngoặc, tên hàm, cột) + chủ deploy/test bản sao Sheet. Cần bật Advanced Drive Service (đã có). Câu upload PDF thêm tay.
