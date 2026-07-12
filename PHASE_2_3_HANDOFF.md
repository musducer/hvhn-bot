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

## PHASE 3 — Tự nhận chuyển khoản (tuỳ chọn, làm sau)

Vấn đề: chuyển khoản ngân hàng VN không tự biết nếu không qua cổng. Với volume nhỏ, giữ thủ công vẫn ổn.

- Tích hợp **SePay** hoặc **Casso** (đọc biến động số dư qua webhook/API). Khi có giao dịch khớp nội dung
  chuyển khoản (vd mã đơn), tự động gọi luồng Phase 2: tạo invite + gửi cho khách (qua email/Zalo/kênh admin).
- Cần: endpoint webhook (Render là web service? kiểm tra bot có HTTP server chưa — hiện là bot Discord
  thuần, có thể phải thêm `aiohttp.web` route hoặc dùng dịch vụ trung gian). Xác thực chữ ký webhook.
- Đối soát nội dung CK ↔ khách (mã đơn duy nhất sinh lúc báo giá). Ghi log giao dịch, chống double-credit.
- Cân nhắc: bước này nhiều rủi ro tiền bạc — thêm xác nhận admin (bán tự động) trước khi cấp.

---

## Quy ước khi làm
- Thêm test cho phần logic thuần + DB (FakeDB), chạy `pytest` toàn bộ phải xanh trước khi commit.
- Phần Discord trực tiếp (invite/modal/join/task) KHÔNG test unit được đầy đủ — phải test trên server thật;
  ghi rõ giả định trong code + báo chủ những gì cần kiểm thủ công.
- Commit theo pha, message tiếng Anh, cuối message thêm dòng Co-Authored-By.
