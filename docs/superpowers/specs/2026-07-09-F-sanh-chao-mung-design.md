# Spec — Nhóm F: Sảnh chào mừng + gate dùng bot ("Dân làng Hua Tát")

Ngày: 2026-07-09
Repo: `D:\Bothvhn` — bot Discord HVHN
File lõi: `cogs/setup.py`, `bot.py`.

## 1. Vấn đề

- **Sảnh chào mừng không thông báo khi có người mới:** không tồn tại listener `on_member_join` nào → không có gì gửi vào kênh `sảnh-chào-mừng`.
- **Tên kênh trong embed không tự trỏ:** các embed (vd `rules_embed` trong `cogs/setup.py`) viết tên kênh dạng chữ thường (`hỏi-đáp-bài-tập`...) thay vì mention `<#id>` → không click được.
- **Thiếu gate dùng bot:** hiện chỉ có gate `cổng-xác-nhận` → role "Thành viên" mở khoá kênh. Chưa có yêu cầu người dùng đọc hướng dẫn dùng bot trước khi được dùng bot Then.

## 2. Mục tiêu

Người mới vào server được chào tự động và dẫn qua **2 gate tách biệt**:
1. **"Thành viên"** (gate cũ, giữ nguyên): đọc luật ở `cổng-xác-nhận` → mở khoá các KÊNH học thuật.
2. **"Dân làng Hua Tát"** (gate mới): đọc kênh `hướng-dẫn-dùng-bot` → bấm xác nhận → mở khoá quyền **DÙNG BOT** (toàn bộ lệnh bot).

## 3. Thiết kế

### 3.1 Listener `on_member_join` (mới)
- Đặt trong `Setup` cog (`cogs/setup.py`) dưới dạng `@commands.Cog.listener()`.
- Khi member join: tìm kênh `sảnh-chào-mừng` trong guild; gửi embed chào:
  - Tiêu đề chào mừng + `member.mention`.
  - Bước 1: đọc `#luật-lệ` (mention) rồi vào `#cổng-xác-nhận` (mention) nhận "Thành viên" để mở kênh.
  - Bước 2: đọc `#hướng-dẫn-dùng-bot` (mention) rồi bấm nút xác nhận nhận "Dân làng Hua Tát" để dùng bot Then.
- Tất cả tham chiếu kênh dùng `channel.mention` (`<#id>`). Nếu không tìm thấy kênh nào thì bỏ qua an toàn (không crash).
- Yêu cầu intent `members` (Server Members Intent) bật trong `bot.py` — kiểm tra và bật nếu chưa (nếu chưa bật, listener không chạy).

### 3.2 Role + kênh mới trong `/setup`
- Thêm vào `roles_to_create`: `{"name": "Dân làng Hua Tát", "color": <màu>, "hoist": False, "perms": Permissions.none()}`.
- Thêm kênh `hướng-dẫn-dùng-bot` trong category `📌 THÔNG TIN CHUNG` (`info_cat`), overwrites `welcome_perms` (everyone xem, chỉ bot gửi).
- Bot đăng vào kênh này 1 embed hướng dẫn (nội dung §3.4) + `BotGuideView` (nút cấp role). Chỉ đăng nếu chưa có message của bot (idempotent, giống pattern verify hiện tại).

### 3.3 `BotGuideView` (persistent view mới)
- Giống `VerifyView`: `timeout=None`, một nút `custom_id="confirm_bot_guide"`.
- Bấm nút: nếu đã có role "Dân làng Hua Tát" → báo đã có; else `add_roles` role đó + báo mở khoá bot.
- Nếu role không tồn tại → báo lỗi nhờ admin chạy `/setup`.
- Đăng ký ở `async def setup(bot)`: `bot.add_view(BotGuideView())` (cạnh `VerifyView`).

### 3.4 Nội dung embed "hướng-dẫn-dùng-bot" (me soạn đầy đủ)
Các mục:
- **Bot Then làm được gì:** hỏi đáp/phân tích Ngữ Văn, lập dàn ý NLXH/NLVH, gợi ý luận điểm–dẫn chứng, tra nhận định trong kho tài liệu, v.v.
- **Hạn chế (đọc kỹ):** AI có thể sai/ảo giác → luôn kiểm chứng; không chép nguyên văn nếu không có trong tài liệu; không thay thế việc tự làm bài; kiến thức ngoài kho có thể thiếu chính xác.
- **Mẹo đặt prompt khai thác tối đa:** nêu rõ dạng đề (NLXH/NLVH, thường/HSG), yêu cầu cụ thể (dàn ý/viết bài, phân tích khía cạnh nào), cung cấp ngữ liệu/đoạn trích khi cần, hỏi từng bước.
- Cuối: bấm nút để xác nhận đã đọc và nhận quyền dùng bot.

### 3.5 Gate toàn bộ lệnh bot
- Hàm thuần testable: `can_use_bot(member) -> bool` — True nếu member có quyền `administrator` HOẶC có role tên "Dân làng Hua Tát".
- Global app-command check: đăng ký trên `bot.tree` (trong `bot.py`) — gọi `can_use_bot` với `interaction.user`; nếu False → chặn (raise `app_commands.CheckFailure` hoặc trả ephemeral) kèm nhắc vào `#hướng-dẫn-dùng-bot`.
- Check chỉ áp cho app commands; **không** áp cho component interaction (nút) → nút verify/guide vẫn hoạt động để cấp role.
- `/setup` (admin) và mọi hành động của admin không bị chặn nhờ nhánh `administrator`.
- Xử lý `CheckFailure` gọn gàng để không spam traceback.

### 3.6 Auto-link kênh trong embed hiện có
- `rules_embed` (và các embed nhắc tên kênh): thay chuỗi tên kênh bằng `channel.mention` với channel object đã tạo trong `/setup`. Chỉ đổi những chỗ có sẵn channel object; không phá vỡ layout.

## 4. Phạm vi

**Trong:** `cogs/setup.py` (listener, role, kênh, BotGuideView, embed mentions), `bot.py` (members intent, global check, can_use_bot).
**Ngoài:** không đổi logic AI/RAG; không đổi hệ phân phối tài liệu.

## 5. Tiêu chí thành công

- Thành viên mới join → embed chào xuất hiện trong `sảnh-chào-mừng`, các kênh trong embed click ra đúng kênh.
- Kênh `hướng-dẫn-dùng-bot` tồn tại sau `/setup`, có embed + nút; bấm nút cấp "Dân làng Hua Tát".
- Chưa có "Dân làng Hua Tát" (và không phải admin) → gọi bất kỳ lệnh bot nào bị chặn kèm hướng dẫn; có role → dùng bình thường.
- Nút bấm hoạt động cả sau khi bot restart (persistent view).
- `can_use_bot` có unit test cho 3 case: admin không role / có role không admin / không cả hai.

## 6. Rủi ro / giả định

- Tra role/kênh theo **tên**; đổi tên thủ công sẽ hỏng → giữ đúng tên `/setup` tạo.
- Cần bật Server Members Intent (Discord Developer Portal + code) để `on_member_join` chạy — nếu portal chưa bật, listener im lặng; ghi chú vận hành.
- Global check chạy trước mọi lệnh: phải chắc không chặn nhầm nút/`/setup`; test logic qua `can_use_bot`, phần wiring review kỹ (repo chưa có harness test Discord).
