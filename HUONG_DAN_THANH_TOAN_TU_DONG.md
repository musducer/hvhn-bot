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

## VIỆC B — Cài đặt trong Google Sheet (KHÔNG phải sửa code)

Code "bộ não" (sinh mã đơn, gửi hướng dẫn CK, khớp tiền, gọi bot, gửi link) **đã có sẵn** trong
`phanphoi.gs`. Bạn chỉ cần **cập nhật code mới + bấm menu điền thông tin**. Không sửa dòng nào.

### B1. Cập nhật code mới vào Apps Script
1. Mở **Google Sheet phân phối** → menu **Tiện ích mở rộng (Extensions)** → **Apps Script**.
2. Mở file code (thường tên `Code.gs` hoặc `phanphoi`), **chép toàn bộ nội dung file `phanphoi.gs`
   mới nhất** (trong dự án bot) dán đè lên → bấm **Lưu** (biểu tượng đĩa).
   - *Nếu bạn không tự lấy file được, báo mình — mình gửi lại toàn bộ nội dung để chép.*
3. Đóng Apps Script, **tải lại (F5)** trang Google Sheet. Menu **HVHN** sẽ có mục mới **💳 Thanh toán tự động**.

### B2. Điền thông tin bằng hộp thoại (thay cho "sửa code")
1. Trên Google Sheet: menu **HVHN** → **💳 Thanh toán tự động** → **⚙️ Cài đặt…**.
2. Lần lượt hiện 5 ô, bạn gõ vào rồi bấm OK:
   1. **Địa chỉ bot** — dán địa chỉ Render (vd `https://ten-cua-ban.onrender.com`), *không* kèm `/mint-invite`.
   2. **Mật khẩu** — gõ đúng chuỗi `HVHN_MINT_SECRET` bạn đặt ở Việc A.
   3. **Thông tin chuyển khoản** — vd `VCB - 0123456789 - NGUYEN VAN A`.
   4. **Giá 1 gói** (VND) — vd `99000`.
   5. **Số ngày mỗi gói** — vd `30`.
3. Xong hiện "✅ Đã lưu cài đặt". (Mật khẩu lưu an toàn trong Google, **không** nằm trong code.)
   - Muốn kiểm lại: **💳 Thanh toán tự động** → **👀 Xem cài đặt hiện tại**.

### B3. Tạo Form đặt mua cho khách
1. Menu **HVHN** → **💳 Thanh toán tự động** → **📱 Tạo/lấy lại Form đặt mua**.
2. Hộp thoại hiện **link Form** — đây là link bạn **đăng/gửi cho khách** (fanpage, Zalo…).
   Form hỏi Họ tên + Email; khách nộp xong hệ thống tự gửi email hướng dẫn chuyển khoản.
   - (Tab `_don_dat_mua` tự sinh trong Sheet để lưu đơn — không cần đụng tới.)

### B4. Xuất bản (deploy) để SePay gọi được
1. Trong Apps Script, góc trên phải bấm **Deploy** → **New deployment**.
2. Bánh răng ⚙ → chọn **Web app**.
3. **Execute as**: Me. **Who has access**: **Anyone**. Bấm **Deploy**.
4. Lần đầu Google hỏi cấp quyền → chọn tài khoản → **Advanced** → **Allow**.
5. **Copy Web app URL** (dạng `https://script.google.com/macros/s/..../exec`). ✍️ Lưu lại — SePay cần URL này.
   > Mỗi lần sau này sửa code phải vào **Deploy → Manage deployments → ✏️ Edit → Version: New** rồi Deploy lại,
   > nếu không SePay vẫn gọi bản cũ.

---

## VIỆC C — Nối SePay với ngân hàng + webhook

SePay là dịch vụ đọc biến động số dư VCB/MB rồi bắn tín hiệu.

1. Đăng ký **sepay.vn**, liên kết tài khoản **VCB** hoặc **MB** theo hướng dẫn của họ.
2. Trong SePay, phần **Webhook / Tích hợp**, dán **Web app URL kèm token** làm địa chỉ nhận thông báo:
   `https://script.google.com/macros/s/.../exec?token=<PMT_WEBHOOK_TOKEN>`.
   - Xem chuỗi đầy đủ trong Sheet: **HVHN → 💳 Thanh toán tự động → 👀 Xem cài đặt hiện tại**.
   - Nếu thiếu `?token=...`, Apps Script sẽ từ chối webhook và khách sẽ không nhận mail link Discord.
3. Lưu lại. Từ giờ mỗi lần có tiền về, SePay gọi Apps Script tự động.

---

## Kiểm thử trước khi bán thật

1. **Chạy thử nguyên luồng**: mở link Form đặt mua (Việc B3) → tự điền bằng **email phụ** của bạn →
   kiểm hộp thư nhận mail hướng dẫn CK → chuyển 1 khoản đúng mã (mẹo: tạm đặt **Giá 1 gói = 1000** trong
   ⚙️ Cài đặt để test rẻ) → xem có nhận mail link Discord không → bấm link vào → bấm **Kích hoạt**.
2. Xem tab **`_don_dat_mua`** trong Sheet: dòng đó phải chuyển sang `da_xu_ly`.
3. Xem tab **Nhật ký**: có dòng "Đơn đặt mua mới" và "Đã cấp link Discord".
4. Nhớ chỉnh **Giá 1 gói** về giá thật sau khi test xong.

---

## Giai đoạn đầu nên chạy "bán tự động" cho an toàn

Nếu chưa yên tâm để máy tự cấp ngay, cứ **để giá gói cao hơn giao dịch test** hoặc theo dõi tab
`_don_dat_mua` + **Nhật ký** vài ngày đầu. Muốn chế độ "chờ bạn duyệt rồi mới gửi link" thì báo mình,
mình chỉnh `doPost` để chỉ ghi `cho_duyet` và thêm nút duyệt tay.

---

## Sự cố thường gặp (xem tab **Nhật ký** trong Sheet để biết lý do)

- **Khách không nhận được mail** → kiểm hộp Spam; Gmail thường giới hạn ~100 mail/ngày (đủ cho quy mô nhỏ).
- **`mint_loi`** → sai địa chỉ bot hoặc mật khẩu không khớp Render (chạy lại ⚙️ Cài đặt); hoặc bot đang khởi động lại.
- **`chua_cau_hinh`** → chưa chạy ⚙️ Cài đặt (thiếu địa chỉ bot/mật khẩu).
- **`khong_khop`** → khách ghi sai nội dung CK (thiếu mã đơn). Xử lý tay: tìm mã trong tab `_don_dat_mua`.
- **`thieu_tien`** → khách CK thiếu so với giá gói đã cài.
- **SePay gọi mà không thấy gì xảy ra** → quên bước Deploy bản mới (Việc B4): **Manage deployments → Edit → New version**.
- **Cấp link 2 lần** → không xảy ra: bot chặn trùng theo mã đơn, Apps Script cũng đánh dấu `da_xu_ly`.
