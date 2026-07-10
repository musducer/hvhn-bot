# Spec — Nhóm D: Chương trình trải nghiệm

Ngày: 2026-07-10
Repo: `D:\Bothvhn` — hệ phân phối tài liệu HVHN
File lõi: `phanphoi.gs` (Apps Script), `watcher.py`, `hvhn_batch.py`.

## 1. Mục tiêu

Một "chương trình trải nghiệm" song song với hệ phân phối chính, cho khách dùng thử tài liệu 72h:
- Tài liệu watermark bằng **placeholder cố định "Nguyễn Văn A" / nguyenvana@gmail.com** (không truy vết cá nhân — chấp nhận vì là demo).
- Phân phối đơn giản: **một folder chung** cho tất cả khách trải nghiệm cùng xem (không tạo folder riêng từng khách).
- Khách trải nghiệm mặc định **72 giờ**; hết hạn → **chỉ gỡ quyền xem của khách đó** (tài liệu vẫn còn cho khách khác).
- **Nút "Xóa chương trình"**: bay hết mọi tài liệu + gỡ quyền mọi khách + xóa 2 tab.
- **Form riêng** thêm khách trải nghiệm và thêm tài liệu trải nghiệm, tách hẳn form chính → **tab danh sách riêng**.

## 2. Ràng buộc (kế thừa MEMORY.md)

- Watermark + rasterize BẮT BUỘC chạy Python trên PC (combined_pipeline). Trải nghiệm cũng render trên PC nhưng recipient cố định.
- `onEdit` simple trigger KHÔNG gọi được DriveApp → thao tác Drive qua menu (chạy tay) hoặc installable trigger (onFormSubmit, time-driven).
- `FormApp.addFileUploadItem()` không tồn tại → câu hỏi upload PDF phải thêm TAY 1 lần trong Form.
- Hệ hạn dùng theo GIỜ (nhóm E đã có `_addHours`, `_hoursBetween`, `_fmtRemaining`, `SUB_HOURS`).

## 3. Kiến trúc

### 3.1 Drive (dưới folder cha HVHN)
- `TÀI LIỆU TRẢI NGHIỆM` — folder CHUNG; chứa bản PDF đã watermark "Nguyễn Văn A"; mọi khách trải nghiệm được cấp quyền xem (viewer) folder này; mỗi file khóa tải (`copyRequiresWriterPermission`).
- `_don_them_tai_lieu_trai_nghiem` — hộp PDF trải nghiệm từ Form → watcher đọc, render, rồi xoá đơn gốc.

### 3.2 Sheet — 2 tab hệ thống mới (thêm vào isSystemTab)
- **`Khách trải nghiệm`** (cột A-G): Tên | Email | Ngày cấp | Ngày hết hạn | Còn lại | Trạng thái | ☑Xóa. Mặc định hết hạn = cấp + 72h (`TRIAL_HOURS = 72`).
- **`Tài liệu trải nghiệm`** (cột A-C): Tên tài liệu | Trạng thái | ☑Xóa.

### 3.3 Forms (tách khỏi form chính)
- **Form "Thêm khách trải nghiệm"** (Tên, Email) → onFormSubmit `xuLyFormKhachTraiNghiem`: thêm dòng vào tab `Khách trải nghiệm` (hạn = now + 72h) + `addViewer(email)` lên folder chung. KHÔNG qua watcher (không render, chỉ cấp quyền).
- **Form "Thêm tài liệu trải nghiệm"** (upload PDF) → onFormSubmit `xuLyFormTaiLieuTraiNghiem`: copy file vào folder `_don_them_tai_lieu_trai_nghiem`. (Câu hỏi upload thêm tay.)

### 3.4 Watcher (Python)
- Hằng: `INCOMING_TRIAL = MIRROR_PARENT/_don_them_tai_lieu_trai_nghiem`; `TRIAL_SHARED = MIRROR_PARENT/TÀI LIỆU TRẢI NGHIỆM`; `PROCESSED_TRIAL`.
- `xu_ly_don_trai_nghiem()`: guard isdir; mỗi `.pdf` ổn định → `render_trial(path, TRIAL_SHARED)` → chuyển đơn gốc sang PROCESSED_TRIAL. Gọi trong `main_async` loop.
- `hvhn_batch.render_trial(doc_path, out_folder)`: gọi `convert_to_secure_image_pdf` với `recipient_name="Nguyễn Văn A"`, `recipient_email="nguyenvana@gmail.com"`, `warning_text=WARNING_TEXT`; output `Nguyễn Văn A__{doc}.pdf` vào `out_folder`. (Idempotent: bỏ qua nếu file đích đã tồn tại.)

### 3.5 Apps Script — hàm chính (`phanphoi.gs`)
- `ensureTraiNghiem()`: tạo/đảm bảo 2 tab (header + trang trí + checkbox cột Xóa); tạo/lấy folder chung + folder đơn.
- `capNhatTaiLieuTraiNghiem()`: quét folder chung → dựng tab `Tài liệu trải nghiệm` (mỗi file 1 dòng, khóa tải `Drive.Files.update copyRequiresWriterPermission` bọc try riêng).
- `kiemTraHetHanTraiNghiem()`: quét tab `Khách trải nghiệm`; quá hạn (`now > expiry`) và chưa 'Đã gỡ' → `removeViewer(email)` khỏi folder chung, trạng thái = 'Đã gỡ (hết hạn)'. Cập nhật cột Còn lại (`_fmtRemaining`).
- `xoaKhachTraiNghiemDaTich()`: dòng tick cột G → `removeViewer` + xóa dòng.
- `xoaTaiLieuTraiNghiemDaTich()`: dòng tick cột C → trash file trong folder chung + xóa dòng.
- `xoaChuongTrinhTraiNghiem()`: xác nhận → trash MỌI file trong folder chung + `removeViewer` mọi khách + clear 2 tab (giữ header). Ghi log.
- Gộp `kiemTraHetHanTraiNghiem` + `capNhatTaiLieuTraiNghiem` vào `hvhnTuDongHoa` (trigger 5').
- Handler form: `xuLyFormKhachTraiNghiem`, `xuLyFormTaiLieuTraiNghiem`; hàm tạo form `taoLaiFormKhachTraiNghiem`, `taoLaiFormTaiLieuTraiNghiem`.
- Menu: submenu **"🧪 Trải nghiệm"** gom: Cập nhật tài liệu / Kiểm hết hạn ngay / Xóa khách đã tích / Xóa tài liệu đã tích / **Xóa chương trình** / Tạo lại 2 Form.

## 4. Cấu hình đầu file
`TRIAL_HOURS = 72`, `TRIAL_NAME = 'Nguyễn Văn A'`, `TRIAL_EMAIL = 'nguyenvana@gmail.com'`, tên tab/folder trải nghiệm.

## 5. Phạm vi
**Trong:** `phanphoi.gs` (tab/form/phân phối/hết hạn/xóa trải nghiệm), `watcher.py` (handler render trải nghiệm), `hvhn_batch.py` (`render_trial`).
**Ngoài:** không đụng hệ phân phối chính, không đụng kho tri thức .md.

## 6. Tiêu chí thành công
- Thêm khách trải nghiệm qua Form → có dòng trong tab (hạn 72h) + xem được folder chung.
- Thêm tài liệu trải nghiệm qua Form → watcher render Nguyễn Văn A → xuất hiện trong folder chung + tab, khóa tải.
- Khách quá 72h → mất quyền xem folder chung; tài liệu + khách khác không ảnh hưởng.
- Nút "Xóa chương trình" → folder chung rỗng, mọi khách mất quyền, 2 tab trống.
- Watermark mọi bản trải nghiệm = "Nguyễn Văn A".

## 7. Rủi ro / giả định
- Watermark cố định = không truy vết rò rỉ phần trải nghiệm (chấp nhận theo yêu cầu).
- Apps Script không test được ở máy → chủ deploy + test trên bản sao Sheet.
- Câu hỏi upload PDF của Form trải nghiệm phải thêm tay 1 lần.
- Cần bật Advanced Drive Service (đã bật cho hệ chính) để khóa tải hoạt động.
- Folder-level viewer: khách xem được mọi file trong folder chung; khóa tải per-file.
