# Phase 3 — Nhật ký & trạng thái bàn giao (tự nhận chuyển khoản → tự gửi link Discord)

> **Cập nhật 2026-07-13 — phương án SePay bên dưới đã được thay thế.**
>
> Luồng hiện hành là **PayOS QR riêng từng đơn → webhook HMAC → bot `/mint-invite` → email Discord**.
> Giá được khóa cứng **60.000đ**. Không đối chiếu nội dung chuyển khoản, nên không bị lỗi khi ngân hàng/ví
> chèn mã hệ thống vào memo. Hướng dẫn triển khai và vận hành duy nhất: `HUONG_DAN_PAYOS_QR_TU_DONG.md`.
> Phần lịch sử SePay được giữ lại ở đây chỉ để biết vì sao kiến trúc cũ đã bị loại.
>
> **Bổ sung 2026-07-13 — khách pre-order:** menu `HVHN → 🎟️ Khách pre-order` tạo/lấy lại một Google
> Form dùng chung cho allowlist email. Mỗi email hợp lệ nhận một invite Discord riêng qua bot `/mint-invite`,
> rồi tiếp tục bước **Kích hoạt quyền truy cập tài liệu** trong kênh `#truy-cập-tài-liệu` và watcher như khách PayOS. Hướng dẫn vận hành ở mục 9 của
> `HUONG_DAN_PAYOS_QR_TU_DONG.md`.

Tài liệu này ghi lại MỌI thứ đã làm cho Phase 3 tính đến 2026-07-12, để AI/người kế tiếp tiếp quản
không phải dò lại. Đọc kèm: `PHASE_2_3_HANDOFF.md` (bối cảnh kiến trúc tổng) và
`HUONG_DAN_THANH_TOAN_TU_DONG.md` (hướng dẫn chủ tự cấu hình, ngôn ngữ thường).

---

## 1. Mục tiêu Phase 3

Tự động hoá từ lúc khách trả tiền tới lúc khách vào được Discord, KHÔNG thao tác tay:

```
Khách điền Google Form (Họ tên + Email)
  → Apps Script sinh MÃ ĐƠN + gửi email hướng dẫn chuyển khoản (memo = mã đơn)
  → Khách CK qua VCB/MB, ghi mã đơn vào nội dung
  → SePay đọc biến động số dư → gọi webhook (Apps Script doPost)
  → Apps Script khớp mã đơn trong Sheet + kiểm đủ tiền + chống trùng
  → gọi BOT endpoint /mint-invite → bot tạo invite-1-lần + ghi hvhn_members(pending)
  → Apps Script tự gửi email chứa link Discord cho khách
  → Khách bấm link vào Discord → bấm "Kích hoạt" (modal Phase 2, prefill sẵn tên/email)
  → active + role + enqueue add_client (watcher cấp tài liệu theo email)
```

Kiến trúc đã CHỐT là **"Cách A": Apps Script là bộ não, bot chỉ hở 1 endpoint cấp invite.**
(Chủ chọn Cách A thay vì cho SePay trỏ thẳng vào bot.) Kênh liên lạc lại với khách = **email** (vì ai
cũng có email, và trùng luôn email nhận tài liệu của watcher). Không dùng Zalo/Messenger.

---

## 2. Đã làm — PHÍA BOT (repo Python, Render). ĐÃ XONG, đã test, đã push.

### 2.1. `keep_alive.py` — thêm endpoint webhook
- `POST /mint-invite` (Flask, chạy sẵn cho Render web service).
- Bảo vệ bằng header `X-HVHN-Secret` khớp env **`HVHN_MINT_SECRET`** (env trống → 503, endpoint tắt).
- Body JSON `{order_code, name, email, duration_days}` → trả `{invite_url, order_code, reused, ...}`.
- Flask ở thread riêng, bot ở event loop chính → nối bằng `asyncio.run_coroutine_threadsafe`.
- `keep_alive(bot)` giờ nhận `bot`; `bot.py::main()` gọi `keep_alive(bot)` SAU khi tạo bot.
- Env phụ: `HVHN_MINT_TIMEOUT` (mặc định 30s).

### 2.2. `cogs/membership.py` — hàm mint + prefill
- `Membership.mint_invite_for_order(order_code, name, email, days) -> dict`:
  - Validate (email hợp lệ, days 1–3650); tạo invite-1-lần (`_pick_invite_channel(guild)` — bản không
    cần interaction); INSERT `hvhn_members` dòng `status='pending'` gắn `order_code` + prefill name/email.
  - **Idempotent theo `order_code`**: nếu đơn đã có → trả lại link cũ (`reused: True`), KHÔNG tạo mới →
    chống double-credit khi SePay bắn webhook lặp.
- `_create_pending_order(...)` — INSERT dòng pending có order_code/name/email.
- `_pick_invite_channel(guild, prefer=None)` — tách từ `_invite_channel` cũ để webhook dùng được.
- `_prefill_for(discord_id)` — lấy name/email đã lưu để **điền sẵn modal Phase 2** (khách chỉ xác nhận).
- `CustomerActivationModal` nhận `default_name/default_email`; nút "Kích hoạt" gọi `_prefill_for`.

### 2.3. `bot.py` — schema
- Thêm cột `hvhn_members.order_code` + index `idx_hvhn_members_order_code`.

### 2.4. Test — `tests/test_membership.py::MintInviteTest`
- Tạo dòng pending đúng (chuẩn hoá email lowercase), idempotent theo order_code (không tạo invite/row
  thứ 2), chặn email sai, chặn duration sai. **Toàn suite: 177 passed.**

### 2.5. Commit liên quan (nhánh main, đã push)
- `Phase 3: /mint-invite webhook for auto payment onboarding`
- (các commit tài liệu kèm theo)

> Lưu ý phía bot: cấp/thu hồi TÀI LIỆU vẫn bất đồng bộ (chờ watcher trên PC). Discord (role/kick/invite)
> là tức thời. Bot chỉ enqueue job vào `hvhn_doc_jobs`.

---

## 3. Đã làm — PHÍA GOOGLE (Apps Script `phanphoi.gs`). ĐÃ XONG code, CHƯA cấu hình chạy thật.

`phanphoi.gs` là Apps Script gắn với Google Sheet phân phối (hệ tài liệu email-centric, có sẵn từ trước:
phân phối PDF theo email qua Drive, trigger 5 phút, chương trình trải nghiệm…). Phase 3 được **cắm thêm**
vào cuối file, tái dùng `ghiLog`, `getOrCreateFolder`, pattern form/trigger sẵn có. KHÔNG có `doPost`/
`onFormSubmit` toàn cục trước đó → không xung đột.

### 3.1. Thành phần thêm vào (khối "PHASE 3" cuối file)
- Menu mới: **HVHN → 💳 Thanh toán tự động** với 3 mục:
  - `caiDatThanhToanTuDong()` — hộp thoại 6 bước, LƯU VÀO ScriptProperties (không nằm trong code, không
    lộ lên GitHub): `PMT_BOT_URL`, `PMT_SECRET`, `PMT_BANK`, `PMT_PRICE`, `PMT_DAYS`, `PMT_WEBHOOK_TOKEN`
    (bước 6 tự sinh token nếu để trống).
  - `xemCaiDatThanhToan()` — xem lại cấu hình (mật khẩu chỉ hiện "(đã đặt)", có hiện token).
  - `taoLaiFormDatMua()` — tạo Google Form đặt mua (khách tự điền Họ tên+Email) + gắn trigger
    `onFormSubmit → xuLyFormDatMua`, lưu `FORM_DATMUA_ID`.
- `xuLyFormDatMua(e)` — khách nộp form: sinh mã đơn `HVHN` + 6 ký tự, ghi tab `_don_dat_mua`
  (cột: Thời gian | Mã đơn | Tên | Email | Số tiền | Trạng thái), gửi email hướng dẫn CK.
- `doPost(e)` — webhook SePay:
  - Kiểm **token** trong URL (`e.parameter.token` khớp `PMT_WEBHOOK_TOKEN`) — vì Apps Script KHÔNG đọc
    được header nên xác thực bằng query `?token=`. Sai token → `unauthorized`.
  - Bỏ qua giao dịch tiền RA (`transferType` chứa "out").
  - Đọc `content/description/transferContent/addInfo` làm memo, `transferAmount/amount/amountIn` làm số tiền.
  - Khớp memo chứa mã đơn trong `_don_dat_mua`; nếu `da_xu_ly` → chống trùng; nếu thiếu tiền → `thieu_tien`.
  - Gọi `PMT_BOT_URL + /mint-invite` với header `X-HVHN-Secret: PMT_SECRET`, body order_code/name/email/days.
  - Có `invite_url` → gửi email link Discord cho khách, đánh dấu dòng `da_xu_ly`, ghiLog "Đã cấp link Discord".
- Helper: `_pmtProp`, `_pmtOut`, `_pmtRandCode`, `_pmtOrderSheet`. Hằng `PMT_ORDER_TAB='_don_dat_mua'`
  (đã thêm vào `isSystemTab` để không bị nhầm là tab khách).
- Đã kiểm cú pháp bằng `node --check` (OK).

### 3.2. Commit liên quan
- `Phase 3 Apps Script: order form + SePay webhook -> mint invite -> email`
- `Phase 3: URL-token guard for SePay webhook (headers unreadable in Apps Script)`

---

## 4. QUYẾT ĐỊNH KỸ THUẬT quan trọng (đừng lật lại nếu không có lý do)

1. **Apps Script không đọc được HTTP header.** → Không dùng API Key/HMAC/OAuth của SePay để xác thực
   webhook (chọn "Không xác thực" trong SePay). Thay bằng **token trong query `?token=`** mà doPost đọc được.
2. **Bí mật để trong ScriptProperties, không hardcode trong `phanphoi.gs`** (file này nằm trong git repo
   public → hardcode secret sẽ lộ). Chủ nhập qua hộp thoại menu.
3. **Idempotency 2 lớp**: bot chặn trùng theo `order_code`; Apps Script đánh dấu dòng `da_xu_ly`.
4. **Email là "return channel"** đã thu ở form → cũng dùng làm email nhận tài liệu (một công đôi việc).
   Vì vậy modal Phase 2 chỉ cần xác nhận (đã prefill), không bắt nhập lại.
5. **Cấp tài liệu vẫn qua watcher** (bất đồng bộ), độc lập với việc gửi link Discord.

---

## 5. CÒN LẠI — CHỦ TỰ LÀM bên ngoài repo (chưa xong)

1. **Render**: đặt env `HVHN_MINT_SECRET` (bắt buộc). Tuỳ chọn `HVHN_KHACH_INVITE_CHANNEL_ID`,
   `HVHN_KHACH_INVITE_HOURS`, `HVHN_MINT_TIMEOUT`.
2. **Apps Script**: chép `phanphoi.gs` mới đè bản cũ → chạy **⚙️ Cài đặt…** (6 bước) → **Tạo Form đặt mua**
   → **Deploy → Web app → Anyone** → lấy Web app URL, ghép `?token=<PMT_WEBHOOK_TOKEN>`.
3. **SePay** (`my.sepay.vn`): tạo webhook, **Bảo mật = Không xác thực**, dán URL-có-token, liên kết
   tài khoản VCB/MB.
4. **Kiểm thử**: đặt tạm giá 1000đ → điền form bằng email phụ → CK → nhận link → join → Kích hoạt →
   kiểm tab `_don_dat_mua` chuyển `da_xu_ly` + tab Nhật ký. Xong đổi giá về thật.

### Trạng thái tại thời điểm ghi (2026-07-12, ~21:44)
Chủ đang ở màn hình SePay bước 3 "Bảo mật". Được hướng dẫn chọn **Không xác thực**. Chưa Deploy Web app,
chưa chạy ⚙️ Cài đặt, chưa đặt env Render. Nói cách khác: **CODE xong hết, CẤU HÌNH chạy thật chưa bắt đầu.**

---

## 6. Việc nên làm tiếp / cải tiến khả dĩ (cho AI kế tiếp)

- **Chế độ bán tự động**: thêm nhánh trong `doPost` chỉ ghi `cho_duyet` + nút admin duyệt trước khi gửi link
  (giảm rủi ro giai đoạn đầu). Hiện đang full-auto.
- **Đối soát số tiền chặt hơn**: hiện chỉ chặn `soTien < gia`. Có thể ghi lại số tiền thực nhận, cảnh báo nếu
  dư nhiều (khách CK nhầm gói).
- **Dọn đơn treo**: đơn `cho_thanh_toan` quá N ngày chưa CK → tự đánh dấu huỷ (song song với
  `_cleanup_stale_onboarding` phía bot dọn `pending/joined` treo).
- **Xác thực mạnh hơn** nếu chuyển webhook về thẳng bot (bỏ Cách A): khi đó đọc được header, có thể verify
  chữ ký SePay. Hiện KHÔNG làm vì đã chốt Cách A.
- **Test phía Apps Script**: không unit-test được trực tiếp; phải test trên Sheet thật. Tách logic thuần
  (parse mã đơn từ memo, so khớp) nếu muốn test.

---

## 7. Bản đồ file liên quan

| File | Vai trò |
|---|---|
| `keep_alive.py` | Endpoint `/mint-invite` (webhook bridge Apps Script → bot) |
| `cogs/membership.py` | `mint_invite_for_order`, prefill modal, vòng đời khách (Phase 0–2) |
| `bot.py` | Schema `hvhn_members` (+ order_code), khởi động, `keep_alive(bot)` |
| `phanphoi.gs` | Apps Script: Form đặt mua + `doPost` webhook + gửi email (Phase 3 bộ não) |
| `tests/test_membership.py` | Test mint + vòng đời |
| `PHASE_2_3_HANDOFF.md` | Bối cảnh kiến trúc tổng + chi tiết Phase 2/3 |
| `HUONG_DAN_THANH_TOAN_TU_DONG.md` | Hướng dẫn chủ tự cấu hình (ngôn ngữ thường) |
| `PHASE_3_STATUS.md` | (file này) nhật ký + trạng thái bàn giao Phase 3 |

Env liên quan: `HVHN_MINT_SECRET`, `HVHN_MINT_TIMEOUT`, `HVHN_KHACH_INVITE_HOURS`,
`HVHN_KHACH_INVITE_CHANNEL_ID`, `HVHN_GUILD_ID`, `HVHN_KHACH_ROLES`, `HVHN_KHACH_GRACE_DAYS`.
ScriptProperties (Apps Script): `PMT_BOT_URL`, `PMT_SECRET`, `PMT_BANK`, `PMT_PRICE`, `PMT_DAYS`,
`PMT_WEBHOOK_TOKEN`, `FORM_DATMUA_ID`.
