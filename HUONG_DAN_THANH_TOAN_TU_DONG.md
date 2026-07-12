# Hướng dẫn bật "tự nhận tiền → tự gửi link Discord" (Phase 3)

Dành cho chủ HVHN. Không cần biết lập trình — chỉ chép-dán và bấm nút theo thứ tự.
Phần con bot đã làm sẵn; bạn chỉ cần làm 3 việc: **A) đặt mật khẩu cho bot**, **B) dán code vào Google
Sheet**, **C) nối SePay**.

---

## Bức tranh tổng thể

```
Khách điền Form (tên+email)
      │  (Apps Script tự gửi mail: "CK ghi nội dung = MÃ ĐƠN")
      ▼
Khách chuyển khoản VCB/MB, ghi mã đơn vào nội dung
      ▼
SePay thấy tiền về  ──►  Apps Script (bộ não): khớp mã + đủ tiền?
      │                        │  có
      │                        ▼
      │                  gọi Bot xin link mời  ──►  Bot tạo link 1 lần
      │                        │
      │                        ▼
      │                  Apps Script tự gửi email link Discord cho khách
      ▼
Khách bấm link vào Discord → bấm "Kích hoạt" → nhận tài liệu
```

Bạn chỉ setup 1 lần. Sau đó chạy tự động.

---

## VIỆC A — Đặt "mật khẩu" cho bot (trên Render)

Mật khẩu này để chỉ Apps Script của bạn được phép nhờ bot tạo link (người lạ không gọi được).

1. Vào **render.com** → mở dịch vụ bot HVHN → tab **Environment**.
2. Bấm **Add Environment Variable**, thêm:
   - **Key**: `HVHN_MINT_SECRET`
   - **Value**: một chuỗi ngẫu nhiên dài, ví dụ `hvhn_9f3K7pQzR2xLm8ValonE` (bạn tự bịa, càng dài càng tốt).
3. (Tuỳ chọn) thêm luôn:
   - `HVHN_KHACH_INVITE_CHANNEL_ID` = ID kênh để tạo link mời (bấm chuột phải vào kênh trong Discord →
     Copy Channel ID; cần bật Developer Mode trong Discord). Bỏ trống cũng được, bot tự chọn kênh chào.
   - `HVHN_KHACH_INVITE_HOURS` = số giờ link mời còn hiệu lực (mặc định 72).
4. **Save Changes** → Render tự khởi động lại bot.

> ✍️ Ghi lại 2 thứ để lát dùng: **địa chỉ bot** (dạng `https://ten-cua-ban.onrender.com`) và
> **mật khẩu** `HVHN_MINT_SECRET` vừa đặt.

---

## VIỆC B — Dán "bộ não" vào Google Sheet (Apps Script)

Đây là phần làm thay bạn: sinh mã đơn, gửi hướng dẫn CK, khớp tiền, gọi bot, gửi link.

### B1. Mở trình soạn code
1. Mở **Google Sheet phân phối** của bạn.
2. Menu **Tiện ích mở rộng (Extensions)** → **Apps Script**.
3. Xoá code mẫu có sẵn, **dán toàn bộ** đoạn dưới đây vào.

### B2. Dán code (sửa 6 dòng CẤU HÌNH ở đầu cho đúng của bạn)

```javascript
// ====== CẤU HÌNH — SỬA 6 DÒNG NÀY ======
const BOT_MINT_URL = "https://ten-cua-ban.onrender.com/mint-invite"; // địa chỉ bot + /mint-invite
const MINT_SECRET  = "dán-đúng-mật-khẩu-đã-đặt-trên-Render";          // giống hệt HVHN_MINT_SECRET
const GOI_SO_NGAY  = 30;          // mỗi gói bao nhiêu ngày
const GIA_GOI      = 99000;       // giá gói (VND) — tiền về phải >= số này mới cấp
const TEN_SHEET    = "DonHang";   // tên tab sheet lưu đơn (tự tạo tab tên này nếu chưa có)
const NGAN_HANG    = "VCB - STK 0123456789 - Chủ TK: NGUYEN VAN A"; // thông tin CK gửi cho khách
// ==========================================

// (1) Khi khách NỘP FORM: sinh mã đơn + gửi email hướng dẫn chuyển khoản
function onFormSubmit(e) {
  const sheet = SpreadsheetApp.getActiveSpreadsheet().getSheetByName(TEN_SHEET);
  const v = e.namedValues;
  // Sửa "Họ tên" / "Email" cho khớp ĐÚNG tên câu hỏi trong Form của bạn:
  const hoTen = (v["Họ tên"] || v["Ho ten"] || [""])[0];
  const email = (v["Email"] || [""])[0];
  const maDon = "HVHN" + Math.random().toString(36).substring(2, 8).toUpperCase();
  sheet.appendRow([new Date(), maDon, hoTen, email, "cho_thanh_toan"]);
  MailApp.sendEmail(email, "Hướng dẫn thanh toán HVHN",
    "Chào " + hoTen + ",\n\n" +
    "Vui lòng chuyển khoản:\n" +
    "  " + NGAN_HANG + "\n" +
    "  Số tiền: " + GIA_GOI + " VND\n" +
    "  NỘI DUNG CHUYỂN KHOẢN (ghi ĐÚNG): " + maDon + "\n\n" +
    "Sau khi chuyển xong, bạn sẽ nhận link vào Discord qua chính email này.");
}

// (2) Khi SEPAY báo có tiền về: khớp mã đơn -> xin link từ bot -> gửi khách
function doPost(e) {
  const data = JSON.parse(e.postData.contents);
  const noiDung = String(data.content || data.description || "").toUpperCase(); // memo giao dịch
  const soTien  = Number(data.transferAmount || data.amount || 0);
  const sheet = SpreadsheetApp.getActiveSpreadsheet().getSheetByName(TEN_SHEET);
  const rows = sheet.getDataRange().getValues();
  for (let i = 1; i < rows.length; i++) {
    const maDon = rows[i][1], hoTen = rows[i][2], email = rows[i][3], trangThai = rows[i][4];
    if (!maDon) continue;
    if (noiDung.indexOf(String(maDon).toUpperCase()) === -1) continue; // memo không chứa mã này
    if (trangThai === "da_xu_ly") return ContentService.createTextOutput("da_xu_ly"); // chống trùng
    if (soTien < GIA_GOI) return ContentService.createTextOutput("thieu_tien");
    const res = UrlFetchApp.fetch(BOT_MINT_URL, {
      method: "post", contentType: "application/json",
      headers: { "X-HVHN-Secret": MINT_SECRET },
      payload: JSON.stringify({ order_code: maDon, name: hoTen, email: email, duration_days: GOI_SO_NGAY }),
      muteHttpExceptions: true
    });
    const out = JSON.parse(res.getContentText() || "{}");
    if (!out.invite_url) return ContentService.createTextOutput("mint_loi");
    MailApp.sendEmail(email, "Link tham gia Discord HVHN",
      "Chào " + hoTen + ",\n\nThanh toán thành công! Bấm link sau để vào Discord:\n" +
      out.invite_url + "\n\nVào xong nhớ bấm nút \"Kích hoạt trải nghiệm\" để nhận tài liệu nhé.");
    sheet.getRange(i + 1, 5).setValue("da_xu_ly"); // đánh dấu để không cấp trùng
    return ContentService.createTextOutput("ok");
  }
  return ContentService.createTextOutput("khong_khop");
}
```

### B3. Tạo tab sheet + gắn bẫy (trigger) cho Form
1. Trong Google Sheet, tạo 1 tab tên **`DonHang`** (đúng như `TEN_SHEET`). Không cần điền gì, code tự ghi.
2. Trong Apps Script, cột trái có biểu tượng **đồng hồ (Triggers)** → **Add Trigger**:
   - Function: `onFormSubmit`
   - Event source: **From spreadsheet**
   - Event type: **On form submit**
   - Save (lần đầu Google hỏi cấp quyền → chọn tài khoản → Advanced → Allow).

### B4. Xuất bản (deploy) để SePay gọi được
1. Góc trên phải bấm **Deploy** → **New deployment**.
2. Bánh răng ⚙ → chọn **Web app**.
3. **Execute as**: Me. **Who has access**: **Anyone**. Bấm **Deploy**.
4. **Copy Web app URL** (dạng `https://script.google.com/macros/s/..../exec`). ✍️ Lưu lại — SePay cần URL này.

---

## VIỆC C — Nối SePay với ngân hàng + webhook

SePay là dịch vụ đọc biến động số dư VCB/MB rồi bắn tín hiệu.

1. Đăng ký **sepay.vn**, liên kết tài khoản **VCB** hoặc **MB** theo hướng dẫn của họ.
2. Trong SePay, phần **Webhook / Tích hợp**, dán **Web app URL** (bước B4) làm địa chỉ nhận thông báo.
3. Lưu lại. Từ giờ mỗi lần có tiền về, SePay gọi Apps Script tự động.

---

## Kiểm thử trước khi bán thật

1. **Thử tay endpoint bot**: nhờ mình hoặc dùng công cụ gửi thử 1 lệnh tới `BOT_MINT_URL` kèm mật khẩu →
   phải nhận về `invite_url`. (Mình có thể hướng dẫn lệnh test riêng.)
2. **Chạy thử nguyên luồng**: tự điền Form bằng email phụ của bạn → nhận mail hướng dẫn CK →
   chuyển 1 khoản nhỏ đúng mã (hoặc tự sửa `GIA_GOI` = 1000 để test) → xem có nhận mail link Discord không →
   join thử → bấm Kích hoạt.
3. Xem tab **DonHang**: dòng đó phải chuyển sang `da_xu_ly`.

---

## Giai đoạn đầu nên chạy "bán tự động" cho an toàn

Nếu chưa yên tâm để máy tự cấp, trong hàm `doPost` bạn có thể **tạm không gửi link ngay** mà chỉ ghi
`cho_duyet`, rồi tự bạn liếc giao dịch và chạy tay. Khi đã tin cậy thì bật full-auto. (Nhờ mình chỉnh giúp
nếu cần.)

---

## Sự cố thường gặp

- **Khách không nhận được mail** → kiểm hộp Spam; Gmail thường giới hạn ~100 mail/ngày (đủ cho quy mô nhỏ).
- **`mint_loi`** → sai `BOT_MINT_URL` hoặc `MINT_SECRET` không khớp Render; hoặc bot đang khởi động lại.
- **`khong_khop`** → khách ghi sai nội dung CK (thiếu mã đơn). Xử lý tay: tìm mã trong tab DonHang.
- **`thieu_tien`** → khách CK thiếu so với `GIA_GOI`.
- **Cấp link 2 lần** → không xảy ra: bot chặn trùng theo mã đơn, Apps Script cũng đánh dấu `da_xu_ly`.
```
