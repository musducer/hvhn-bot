# Handoff — Quy trình khách HVHN: Phase 2 & 3

Prompt cho AI kế tiếp. Phase 0 và 1 đã xong (xem cuối file). Nhiệm vụ: làm Phase 2 (onboarding tự
động bằng invite-1-lần + modal) và Phase 3 (tự nhận chuyển khoản). Đọc kỹ phần "Bối cảnh" trước khi code.

---

## Bối cảnh kiến trúc (bắt buộc nắm)

- Repo: bot Discord "Then" cho Nhóm học tập HVHN. Chính: `cogs/`, `bot.py`. Test: `tests/` chạy bằng
  `python -m pytest` (dùng interpreter có `discord`/`asyncpg`). Chủ tự commit + push (Render auto-deploy).
- **Hai hệ TÁCH RỜI:**
  1. **Discord** (bot chạy trên Render, luôn online, tức thời): cộng đồng + bot Then + vòng đời khách.
  2. **Kho tài liệu** (watcher `watcher.py` chạy trên PC của chủ, CHỈ khi PC bật; qua Google Drive +
     Apps Script + Google Sheet): watermark + mã hoá PDF (`combined_pipeline.py`), phân phối **theo EMAIL**.
- Lệnh Discord KHÔNG làm việc nặng trực tiếp — chúng **xếp job** vào bảng `hvhn_doc_jobs`
  (`INSERT INTO hvhn_doc_jobs (job_type, text_payload, requested_by)`), watcher đọc và thực thi khi PC bật.
  - `add_client` payload = `"{tên}\t{email}"`; `remove_client` = `"{email}"`; `renew_client` = `"{email}\t{số}\t{đơn_vị}"` (đơn_vị: `ngay`/`gio`).
- Sheet phân phối hiện tại (khách + tài liệu, watcher/Apps Script sync):
  https://docs.google.com/spreadsheets/d/1KwCP7JcKCAR_GGlIPLUXYMk8_tdQu2Wo-E-nD5nRf6Y/edit
  (dữ liệu KHÁCH thật — không public, không log ra ngoài).
- **Hệ quả quan trọng:** cấp/thu hồi TÀI LIỆU là bất đồng bộ (chờ watcher). Vào Discord + cấp role là
  tức thời. Đừng hứa "vào phát có tài liệu ngay"; để câu chờ hoặc bật watcher trong khung onboard.

## Đã có sẵn sau Phase 0+1 (ĐỪNG làm lại — hãy TÁI SỬ DỤNG)

- Bảng `hvhn_members` (định nghĩa trong `bot.py` SCHEMA):
  `id, discord_id, email, name, invite_code, duration_days, granted_at, expires_at, status,
   notified_expiry, created_by, created_at`. `status ∈ {active, expired, kicked}` (Phase 2 sẽ thêm
  `pending`, `joined`). Cột `invite_code` đã có sẵn CHỜ Phase 2 dùng.
- `cogs/membership.py`:
  - Hàm thuần đã test: `compute_new_expiry(now, current_expires, days)` (gia hạn cộng dồn),
    `is_expired`, `kick_due(expires_at, now, grace_days)`.
  - `Membership._register(discord_id, name, email, days, created_by)` → upsert active + tính hạn.
  - `Membership._grant_roles/_revoke_roles`, `_enqueue(job_type, text_payload, requested_by)`,
    `_guild()`, `_is_admin/_require_admin`.
  - Task `expiry_loop` (mỗi giờ) → `_run_expiry_tick()`: hết hạn → gỡ role + DM + enqueue `remove_client`;
    quá ân hạn (`GRACE_DAYS`, env `HVHN_KHACH_GRACE_DAYS`=3) → kick.
  - Lệnh admin: `/hvhn_capkhach`, `/hvhn_giahankhach`, `/hvhn_huykhach`, `/hvhn_khach_ds`, `/hvhn_khach_check`.
  - Env: `HVHN_KHACH_ROLES` (mặc định "Dân làng Hua Tát"), `HVHN_GUILD_ID`, `HVHN_KHACH_DURATION_DAYS`.
- Role gate chung: `bot.py::can_use_bot` + `GatedCommandTree`. Intents đã bật `members=True`.
- `intents.invites` CHƯA bật — Phase 2 cần thêm nếu muốn nhận event invite; hoặc chỉ cần fetch
  `await guild.invites()` theo yêu cầu (bot cần quyền Manage Guild — đã là admin).

---

## PHASE 2 — Onboarding tự động (invite-1-lần + modal điền Họ tên/Email)

Mục tiêu: bỏ hẳn việc admin gõ tay thông tin khách. Luồng CHỦ ĐÃ CHỐT:

1. Admin xác nhận đã nhận chuyển khoản → gõ `/hvhn_moikhach thoi_han:<ngày> [ghi_chu]`:
   - Tạo **invite dùng-1-lần** vào server: `await channel.create_invite(max_uses=1, max_age=<giây>, unique=True)`
     (channel = kênh chào/verify; `max_age` ví dụ 72h qua env `HVHN_KHACH_INVITE_HOURS`).
   - INSERT `hvhn_members` một dòng `status='pending'`, lưu `invite_code=invite.code`, `duration_days=thoi_han`,
     `created_by`. CHƯA có discord_id/email.
   - Trả link cho admin để gửi khách (ephemeral).
2. Khách bấm link → join. Bot bắt `on_member_join`:
   - **Xác định invite nào vừa dùng** bằng cách so cache: giữ `dict[code] -> uses` (nạp ở `on_ready` và
     cache lại sau mỗi join). Khi join, fetch `guild.invites()`, tìm code có `uses` tăng (hoặc biến mất vì
     đã hết 1 lượt) và khớp `hvhn_members.invite_code` với `status='pending'`.
   - Nếu khớp: cập nhật dòng đó `discord_id=member.id, status='joined'`. Rồi **DM cho khách** một nút
     "Kích hoạt trải nghiệm" (persistent `discord.ui.View`, `custom_id` cố định). Nếu DM đóng → fallback:
     nhắn ở một kênh riêng (vd `#kích-hoạt-khách`) tag khách.
   - Nếu KHÔNG khớp invite nào (thành viên cộng đồng thường) → bỏ qua, để luồng cũ (`VerifyView`) xử lý.
3. Khách bấm "Kích hoạt" → mở **modal** (`discord.ui.Modal`) 2 ô: **Họ tên**, **Email** (validate email).
   - On submit (đây là "mốc ghi nhận"): với dòng `joined` của `discord_id`, set `name,email,
     granted_at=now, expires_at=compute_new_expiry(now, None, duration_days), status='active'`.
   - Cấp role (dùng `Membership._grant_roles`), enqueue `add_client` = `"{name}\t{email}"`, DM xác nhận.
   - Tái sử dụng `_register`/logic Phase 1 nếu tiện (nhưng ở đây là chuyển pending→active, không cộng dồn).

### Yêu cầu kỹ thuật Phase 2
- View + Modal phải **persistent** (đăng ký trong `setup()` qua `bot.add_view(...)`, `custom_id` cố định)
  để sống qua restart Render.
- Bật `intents.invites = True` trong `bot.py` NẾU dùng event; hoặc chỉ fetch on-demand (khuyến nghị:
  fetch on-demand để đỡ phụ thuộc event, nhưng vẫn phải cache uses ở `on_ready`).
- Xử lý các biên: join nhưng không kích hoạt (dọn dòng `joined` quá N giờ → huỷ); invite hết hạn chưa dùng
  (cron dọn `pending` quá hạn); rời rồi vào lại; email sai/typo (cho sửa: nút kích hoạt lại hoặc lệnh admin).
- KHÔNG chặn được việc khách bấm nút verify cũ để tự lấy role — CHẤP NHẬN được, vì email (cho tài liệu),
  hạn và auto-kick đều bám `hvhn_members`, độc lập với việc họ có role gì.
- Test được: tách logic "match invite từ diff uses" thành hàm thuần `match_used_invite(before: dict,
  after: list) -> code|None` và test nó; test chuyển pending→active bằng FakeDB như `tests/test_membership.py`.

---

## PHASE 3 — Tự nhận chuyển khoản → tự gửi link (kiến trúc ĐÃ CHỐT: "Cách A")

Bối cảnh nghiệp vụ (chủ đã chốt):
- Khách đến từ nơi bán (fanpage/Zalo) → điền **Google Form** (ĐÃ CÓ) thu **Họ tên + Email (+ SĐT)**.
  Form/Sheet là nơi lưu đơn. **Email là kênh liên lạc lại DUY NHẤT** cho luồng chính (không dùng
  Zalo/Messenger): ai cũng có email, và email này TRÙNG email nhận tài liệu của watcher → một công đôi việc.
- Chuyển khoản VCB/MB **không mang theo thông tin liên lạc** — chỉ có số tiền + **nội dung CK (memo)**.
  Vì vậy phải đối soát bằng **mã đơn duy nhất** sinh lúc đặt hàng, khách ghi vào memo khi CK.
- "Khách chưa từng có Discord" KHÔNG phải rào cản: gửi họ **link invite** qua email, bấm vào Discord
  web/app tự mở + tạo tài khoản tại chỗ. Đây là hành vi chuẩn.

### Kiến trúc "Cách A" — Apps Script là bộ não, bot chỉ cấp invite
Chủ đã chọn Cách A (thay vì để webhook trỏ thẳng về bot). Phân vai:

1. **Apps Script (Web App URL) = webhook target của SePay** và là nơi gửi email.
   - Nhận webhook biến động số dư từ **SePay** (đọc VCB/MB; Casso là phương án thay thế).
   - Đối soát: tách **mã đơn** từ `memo` giao dịch → tra dòng tương ứng trong **Sheet đơn hàng**
     (đã có Họ tên + Email). Chống double-credit: đánh dấu cột "đã xử lý" trên dòng đó, bỏ qua nếu đã set.
   - Gọi **endpoint cấp-invite của bot** (xem dưới) để lấy 1 link invite-1-lần.
   - **Gửi email bằng Gmail của chủ**: `MailApp.sendEmail(email, tiêu_đề, nội_dung_có_link)` —
     MIỄN PHÍ, không cần SendGrid/Mailgun (quota ~100 mail/ngày là quá đủ cho volume này).
2. **Bot (Render, luôn online) hở đúng 1 endpoint HTTP** vì Apps Script KHÔNG tạo được invite Discord:
   - `keep_alive.py` đã có sẵn web server → thêm 1 route, vd `POST /mint-invite`.
   - Body: `{order_code, name, email, duration_days}` + **secret token** (so khớp env `HVHN_MINT_SECRET`;
     Apps Script gửi kèm header). Từ chối nếu sai secret.
   - Xử lý: tạo invite-1-lần (`channel.create_invite(max_uses=1, max_age=…, unique=True)`) + **INSERT
     `hvhn_members` dòng `status='pending'`** với `invite_code, duration_days, email, name` (tái dùng đúng
     luồng Phase 2 — chỉ khác là email/name đã biết trước từ form, nên modal Phase 2 chỉ cần XÁC NHẬN/sửa,
     không bắt nhập mới). Trả JSON `{"invite_url": …}`.
   - **Bot vẫn là nguồn sự thật** cho `hvhn_members`; Apps Script không đụng DB Postgres.

### Yêu cầu kỹ thuật Phase 3
- **Idempotency 2 lớp**: (a) Sheet đánh dấu đơn đã xử lý; (b) bot từ chối tạo trùng nếu đã có dòng
  `pending/joined/active` cho cùng `order_code` (thêm cột `order_code` vào `hvhn_members`, unique-ish).
- **Bảo mật**: endpoint mint phải kiểm secret; log giao dịch (số tiền, memo, mã đơn, thời điểm) để đối soát.
  KHÔNG log PII khách ra ngoài. Xác thực chữ ký/API-key webhook SePay nếu SePay hỗ trợ.
- **Đối soát số tiền**: kiểm tiền nhận ≥ giá gói mới cấp (tránh khách CK thiếu vẫn được link).
- **Bán tự động (khuyến nghị giai đoạn đầu)**: có thể để bot chỉ tạo invite sau khi admin bấm duyệt 1 nút
  (giảm rủi ro tiền bạc), rồi mới bật full-auto khi đã tin cậy.
- **Test được**: tách logic thuần "parse mã đơn từ memo" + "match đơn trong Sheet" và test; endpoint bot
  test bằng FakeDB như `tests/test_membership.py`. Phần SePay/Gmail thật phải kiểm thủ công.

### Luồng tổng (Cách A)
```
Khách điền Form (tên+email) → nhận mã đơn → CK VCB/MB (memo = mã đơn)
   → SePay webhook → Apps Script: khớp memo↔Sheet, chống trùng
   → Apps Script POST /mint-invite (bot) → bot tạo invite + INSERT hvhn_members(pending)
   → Apps Script MailApp.sendEmail(link invite) → khách bấm link → vào Discord
   → (Phase 2) on_member_join khớp invite_code → modal xác nhận email → active + role + add_client
```

---

## Quy ước khi làm
- Thêm test cho phần logic thuần + DB (FakeDB), chạy `pytest` toàn bộ phải xanh trước khi commit.
- Phần Discord trực tiếp (invite/modal/join/task) KHÔNG test unit được đầy đủ — phải test trên server thật;
  ghi rõ giả định trong code + báo chủ những gì cần kiểm thủ công.
- Commit theo pha, message tiếng Anh.
