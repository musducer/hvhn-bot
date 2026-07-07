# MEMORY.md — Hệ thống bảo mật & phân phối tài liệu HVHN

> File này mô tả TOÀN BỘ dự án cho AI/người tiếp nhận sau. **Cập nhật file này mỗi khi có thay đổi.**
> Chủ sở hữu: **minhlinhvi2010@gmail.com** (Google account chạy Drive/Sheet/Form).
> Thư mục code trên PC: `D:\Bothvhn`.

---

## 1. Mục tiêu

Phân phối tài liệu (đề/tài liệu ôn thi Ngữ Văn) cho học viên theo **gói 1 tháng**, chống sao chép:
- Mỗi tài liệu được **đóng dấu watermark riêng tên + email từng người nhận** rồi **rasterize thành PDF ảnh** (không copy/OCR/bôi đen chữ được).
- Mỗi học viên nhận **link Google Drive riêng**, chỉ email họ xem được, **khoá tải/in/copy**.
- Hết 30 ngày **tự gỡ quyền + xoá file**; có thể **gia hạn**.
- 3 quản lý thao tác **100% từ điện thoại** (thêm khách, thêm tài liệu) qua Google Form; xem/gia hạn/xoá qua app Google Sheets.

## 2. Ràng buộc cốt lõi (đọc kỹ trước khi sửa)

- **KHÔNG có thẻ tín dụng** → không dùng được Google Cloud Console / API service account. Mọi tự động hoá phía Google chạy bằng **Google Apps Script** (miễn phí) gắn với 1 Google Sheet.
- **Watermark + rasterize BẮT BUỘC chạy bằng Python trên PC** (thư viện PyMuPDF/pikepdf/img2pdf). Điện thoại/cloud không làm được → PC của chủ là "máy render". Điều kiện: **PC bật** (không cần 24/7; đơn xếp hàng, bật máy là xử).
- Cầu nối PC ↔ Google: **Google Drive for Desktop (chế độ MIRROR)** đồng bộ 2 chiều folder Drive ↔ ổ đĩa local. KHÔNG dùng API. Vị trí mirror trên máy: `D:\Mirror Files Drive` (do lúc cài chọn lưu ở đó; "My Drive" trong ổ G: chỉ là shortcut trỏ về đây).
- Giới hạn Apps Script cần nhớ:
  - **`onEdit` (simple trigger) KHÔNG được gọi DriveApp** → mọi thao tác đụng Drive phải qua menu (chạy tay, đủ quyền) hoặc **installable trigger** (time-driven, onFormSubmit).
  - **`FormApp.addFileUploadItem()` KHÔNG tồn tại** → câu hỏi upload file phải thêm TAY 1 lần trong giao diện Form.
  - MCP connector Google Drive của Claude chỉ đọc/tạo/copy, **không xoá, không upload file nặng** (>~1MB base64 quá lớn).

## 3. Kiến trúc & luồng dữ liệu

```
[Điện thoại quản lý]                 [Google (Sheet + Apps Script + Drive)]              [PC chủ - bật máy]
  Form ① Thêm khách  ──submit──►  onFormSubmit: ghi đơn .txt vào  _don_them_khach  ──mirror──►  watcher.py
  Form ② Thêm tài liệu ─submit─►  onFormSubmit: copy PDF vào       _don_them_tai_lieu ─mirror──►  watcher.py
                                                                                                    │
                                             render watermark (combined_pipeline) ◄──────────────────┘
                                                                                                    │
   folder SOURCE (mirror) ◄── ghi PDF đã đóng dấu + new_rows_*.csv ──────────────────────────────────┘
        │
        └─ trigger tuDongXuLyFileMoi (5') ─► phanPhoi: copy sang folder từng khách + share email + khoá tải
                                                    │
                                              tab khách + tab "Khách hàng" (hạn dùng) + Dashboard
   trigger kiemTraHetHan (hằng ngày) ─► quá 30 ngày: gỡ quyền + xoá file
```

Đơn XOÁ (từ menu Sheet) đi ngược: Apps Script ghi `_don_xoa_khach` / `_don_xoa_tai_lieu` → watcher gỡ khỏi `clients.csv` / `docs/`.

## 4. Google Drive — cấu trúc & ID

Folder cha: **TÀI LIỆU ĐỘC QUYỀN HVHN** = `10RjJY_DVmI8Ys-tV1k_HzMLIIFCvbRWs`
(local mirror = `D:\Mirror Files Drive\TÀI LIỆU ĐỘC QUYỀN HVHN`). Bên trong:

| Folder | ID / tên | Vai trò |
|---|---|---|
| SOURCE (file đã watermark, chưa phân phối) | `15Ipn2p7b3_J-_pszxSh05vSMET2rf9Dl` — "TÀI LIỆU ĐÃ WATERMARK CHƯA PHÂN PHỐI" | PC ghi PDF + new_rows_*.csv vào; trigger đọc |
| DEST (phân phối chính thức) | `1Afa6oP-vRcpjA1ooSpjXJDRdhiZbCQhB` — "TÀI LIỆU PHÂN PHỐI CHÍNH THỨC" | mỗi khách 1 subfolder chứa bản copy đã share |
| `_don_them_khach` | tạo bởi Apps Script | đơn thêm khách (.txt: `tên<TAB>email`) |
| `_don_them_tai_lieu` | tạo bởi Apps Script | PDF tài liệu mới upload từ Form ② |
| `_da_xu_ly_tai_lieu` | tạo bởi watcher | lưu trữ PDF gốc đã xử lý |
| `_don_xoa_khach` | tạo khi có lệnh xoá | .txt chứa email khách cần gỡ khỏi clients.csv |
| `_don_xoa_tai_lieu` | tạo khi có lệnh xoá | .txt chứa tên tài liệu gốc cần gỡ khỏi docs/ |

## 5. File code trên PC (`D:\Bothvhn`)

| File | Vai trò |
|---|---|
| `combined_pipeline.py` | Lõi: `convert_to_secure_image_pdf(input, output, recipient_name, recipient_email, warning_text)`. Render từng trang → ảnh (LUÔN rasterize, kể cả PDF chữ/OCR → mất lớp text) → chèn watermark LỚN "HỒN VĂN - HỒN NGƯỜI" chéo giữa + watermark NHỎ tên/email chéo lệch trên-dưới + header/footer cảnh báo bản quyền (có prompt injection chống AI) + dòng "Tài liệu được phân phối cho: …". Mã hoá pikepdf R6, owner password ngẫu nhiên/file, cấm extract/print. Temp dir riêng/job (an toàn chạy song song), dọn trong `finally`. |
| `hvhn_batch.py` | Module chung. Hằng: `CLIENTS_CSV`, `DOCS_DIR=docs/`, `MIRROR_SOURCE`, `OUT_ROOT` (=MIRROR_SOURCE nếu mirror sẵn sàng, else `./output`), `NEW_ROWS_CSV`. Hàm: `load_clients`, `append_client`, `list_docs`, `render_batch` (ProcessPool song song), `write_new_rows_csv(rows, filename=)`, `remove_client(email)`, `remove_doc(doc_base)`. |
| `watcher.py` | Vòng lặp mỗi `POLL_SECONDS=30`: xử `_don_them_khach`, `_don_them_tai_lieu`, `_don_xoa_khach`, `_don_xoa_tai_lieu`. `_stable()` đợi file đồng bộ xong mới xử. Xử xong xoá/di chuyển đơn. |
| `clients.csv` | Nguồn chân lý danh sách khách (`name,email`) trên PC. |
| `docs/` | Kho tài liệu gốc (PDF chưa watermark) — dùng để render cho khách mới sau này. |
| `run_watcher.bat` | Chạy watcher, tự khởi động lại nếu crash. Đã tạo shortcut auto-start ở Startup folder Windows (`HVHN Watcher.lnk`, chạy minimized khi mở máy). |
| `add_client.py`, `add_doc.py`, `batch_run.py` | Script chạy tay (CLI) — ít dùng vì đã có Form. |
| `phanphoi.gs` | TOÀN BỘ Apps Script (dán vào Sheet > Extensions > Apps Script). Xem mục 6. |
| `bot.py` + `cogs/doc_storage.py` | Discord bot HVHN chạy được trên Render. Cog `doc_storage` thêm slash command quản lý tài liệu từ Discord; bot ghi đơn vào bảng Postgres `hvhn_doc_jobs`, KHÔNG gọi Google Drive/API trực tiếp và KHÔNG cần thấy Drive mirror. |

## 6. Google Sheet + Apps Script (`phanphoi.gs`)

Sheet: **"Phân phối - HVHN"** = `1KwCP7JcKCAR_GGlIPLUXYMk8_tdQu2Wo-E-nD5nRf6Y`.

**Tab hệ thống** (isSystemTab, bỏ qua khi quét khách): `Dashboard`, `Nhập mới`, `Khách hàng`, `Tài liệu`, `Nhật ký`.
**Tab khách**: mỗi khách 1 tab, header `TenNguoiNhan | Email | TenFile | TrangThai`. TrangThai = "Xong: <url>" khi phân phối OK.

**Tab "Khách hàng"** (registry, cột A-H): Tên | Email | Ngày cấp | Ngày hết hạn | Còn lại (ngày) | Trạng thái | ☑Gia hạn+1 tháng (cột G, tick tự gia hạn ngay) | ☑Xóa khách (cột H, tick rồi chạy menu).
**Tab "Tài liệu"**: Tên tài liệu | Số khách đang có | ☑Xóa tài liệu. Tên tài liệu suy từ file `{tên}__{tàiliệu}.pdf` (tách theo `__`).
**Tab "Nhật ký"**: Thời gian | Hành động | Chi tiết (audit log, dòng mới chèn trên cùng).

**Hàm chính:**
- `onOpen` tạo menu **HVHN** + đảm bảo các tab.
- `onEdit`: ô tìm kiếm Dashboard (B1) → lọc; tick cột G tab Khách hàng → `giaHanMotDong(...,false)` (chỉ sửa sheet, để trigger phân phối lại nếu cần).
- `phanPhoi()`: quét mọi tab khách, copy file từ SOURCE→DEST **idempotent** (đã có thì dùng lại, KHÔNG đẻ trùng), chỉ `addViewer` nếu chưa có quyền (tránh spam mail), `Drive.Files.update copyRequiresWriterPermission` bọc try riêng (thiếu Drive service vẫn không kẹt). Cuối gọi `dongBoKhachHang` + `capNhatDashboard`.
- `tuDongXuLyFileMoi()`: (trigger 5') quét mọi `new_rows*.csv` trong SOURCE → merge vào tab khách → `phanPhoi()`.
- `hvhnTuDongHoa()`: trigger tổng chạy mỗi 5 phút, gom toàn bộ cập nhật tự động: quét `new_rows*.csv`, phân phối, xử lý tick gia hạn, kiểm tra hết hạn, xử lý tick xoá khách/tài liệu, cập nhật tab Tài liệu + Dashboard.
- `caiDatTuDongHoa()`: chạy 1 lần sau khi dán code Apps Script để xoá trigger cũ trùng và tạo trigger `hvhnTuDongHoa` mỗi 5 phút + `kiemTraHetHan` hằng ngày.
- `dongBoKhachHang()`: khách mới vào tab "Khách hàng", hạn = hôm nay + 30 ngày.
- `kiemTraHetHan()`: (trigger hằng ngày) quá hạn → xoá file DEST + gỡ share → trạng thái "Đã gỡ quyền".
- `giaHanMotDong / xuLyGiaHan`: +30 ngày; nếu đã gỡ thì xoá trạng thái các dòng để phanPhoi copy lại.
- `xoaKhachDaTich / xoaTatCaKhach`: xoá file+folder+tab+dòng registry, ghi đơn `_don_xoa_khach` (email) cho watcher gỡ clients.csv.
- `capNhatTaiLieu`: dựng tab "Tài liệu". `xoaTaiLieuDaTich`: xoá tài liệu khỏi mọi khách (dòng tab + file DEST + file SOURCE) + ghi đơn `_don_xoa_tai_lieu`.
- `donFileTrung`: dọn file trùng trong DEST (kể cả bản Drive tự đổi tên "(1)").
- `caiDatForm`: tạo 2 Form + folder đơn + trigger onFormSubmit. `taoLaiFormKhach`: tạo lại riêng Form khách. Handler `xuLyFormKhach` (ghi .txt đơn khách), `xuLyFormTaiLieu` (copy PDF vào `_don_them_tai_lieu`).
- `ghiLog(action, detail)`: ghi tab Nhật ký.

**Cấu hình đầu file**: `SOURCE_FOLDER_ID`, `DEST_ROOT_FOLDER_ID`, `HVHN_PARENT_FOLDER_ID(_EARLY)`, `SUB_DAYS=30`, `WARN_DAYS=3`, tên cột/tab.

## 7. Triggers cần có (Apps Script > ⏰ Triggers)

1. `tuDongXuLyFileMoi` — Time-driven, Minutes, **every 5 minutes**.
2. `kiemTraHetHan` — Time-driven, **Day timer**, 1-2 AM.
3. (tự tạo bởi `caiDatForm`) `xuLyFormKhach`, `xuLyFormTaiLieu` — onFormSubmit.

**Advanced Service**: bật **Drive API** (Services > +) để `Drive.Files.update` khoá tải hoạt động. (Đây là Advanced Service của Apps Script, KHÁC Cloud Console, không cần thẻ.)

## 8. Quy trình vận hành hằng ngày

- **Thêm khách**: quản lý điền Form ① (link published) → tối đa ~5-8 phút sau khách có tài liệu. (Chuỗi: Form→đơn→mirror→watcher render→SOURCE→trigger 5' phân phối.)
- **Thêm tài liệu**: quản lý điền Form ② (upload PDF) → render cho TẤT CẢ khách → phân phối. Tài liệu tự thành PDF ảnh dù up lên là PDF chữ.
- **Qua Discord bot**: quản lý có role `HVHN Admin` hoặc quyền Manage Server dùng `/hvhn_themkhach`, `/hvhn_themtailieu`, `/hvhn_xoakhach`, `/hvhn_xoatailieu`, `/hvhn_trangthai`. Bot trên Render ghi đơn vào Postgres `hvhn_doc_jobs`; watcher trên PC đọc DB mỗi vòng. Thêm khách/tài liệu đi qua `_don_them_*`; xoá khách/tài liệu phải đi 2 nhánh: gỡ local `clients.csv`/`docs/` qua `_don_xoa_*` và báo Apps Script xoá Sheet/Drive qua `_don_sheet_xoa_khach` / `_don_sheet_xoa_tai_lieu`.
- **Gia hạn**: mở app Sheets → tab Khách hàng → tick cột G. Trigger `hvhnTuDongHoa` tự xử lý trong tối đa ~5 phút.
- **Xoá khách**: tick cột H. Trigger `hvhnTuDongHoa` tự xoá file/folder/tab/dòng registry và ghi đơn `_don_xoa_khach` trong tối đa ~5 phút. Menu xoá vẫn còn để dùng khẩn cấp nhưng không bắt buộc.
- **Xoá tài liệu**: tab Tài liệu được cập nhật tự động; tick cột Xóa tài liệu. Trigger `hvhnTuDongHoa` tự xoá khỏi mọi khách và ghi đơn `_don_xoa_tai_lieu` trong tối đa ~5 phút.
- Điều kiện chung: **PC bật + watcher chạy** (auto khi mở máy, hoặc chạy `run_watcher.bat`).

## 9. Lỗi đã gặp & cách xử (đừng lặp lại)

- **File phân phối bị trùng / spam mail mỗi 5':** do phanPhoi cũ `makeCopy` + `addViewer` mỗi lần chạy. Đã fix idempotent + chỉ share khi chưa có quyền + tách try cho Drive.Files.update. Dọn bằng `donFileTrung`.
- **Form không nhận phản hồi:** `setAcceptingResponses(true)`. Có `taoLaiFormKhach` + `_openFormIfAlive` (bỏ qua form đã xoá/thùng rác).
- **`addFileUploadItem is not a function`:** Apps Script không tạo được câu hỏi upload → thêm tay 1 lần trong Form ②.
- **Mirror mới bật còn trống:** đổi Stream→Mirror phải chờ đồng bộ; folder về máy sau vài phút.
- **Bot trên Render không thấy ổ D:** đúng thiết kế. Bot chỉ cần `DATABASE_URL`; watcher trên PC cũng phải có cùng `DATABASE_URL` trong `.env` để kéo đơn từ bảng `hvhn_doc_jobs` về folder `_don_*`. Quyền Discord mặc định: role `HVHN Admin` hoặc Manage Server; có thể đổi tên role bằng biến `HVHN_ADMIN_ROLE`.
- **Discord xoá khách/tài liệu báo done nhưng Sheet không đổi:** nguyên nhân cũ là watcher chỉ gỡ `clients.csv`/`docs/`, chưa gửi lệnh cho Apps Script xoá Sheet/Drive. Đã fix bằng folder `_don_sheet_xoa_khach` và `_don_sheet_xoa_tai_lieu`; `hvhnTuDongHoa()` đọc các folder này rồi xoá thật trên Sheet/Drive.

## 10. Muốn mở rộng?

- Đổi độ dài gói: sửa `SUB_DAYS`.
- Watermark: sửa `combined_pipeline.py` (`_add_watermark_to_page`, `BRAND_WATERMARK_TEXT`, opacity/vị trí).
- Thêm loại đơn từ điện thoại: tạo folder `_don_*` + handler watcher tương ứng + (nếu cần) Form/menu Apps Script ghi đơn.
- Thêm quản lý: chỉ cần gửi 2 link Form; không giới hạn số người điền.

---
*Cập nhật gần nhất: 2026-07-05 — thêm xoá khách/tài liệu thủ công, tab Tài liệu, tab Nhật ký (audit log).*
