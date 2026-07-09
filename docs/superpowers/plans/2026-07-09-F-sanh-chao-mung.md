# Sảnh Chào Mừng + Gate Dùng Bot (Nhóm F) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Thêm chào mừng tự động khi có người mới, kênh hướng dẫn dùng bot + role "Dân làng Hua Tát" gate toàn bộ lệnh bot, và cho tên kênh trong embed tự trỏ.

**Architecture:** Tách phần logic thuần (kiểm tra quyền, dựng embed) thành hàm có thể unit-test; phần wiring Discord (tree check, listener, persistent view) mỏng, gọi vào các hàm thuần đó. Gate là một `CommandTree` con override `interaction_check`.

**Tech Stack:** Python, discord.py, unittest.

## Global Constraints

- Text hướng tới người dùng: tiếng Việt có dấu.
- Không thêm dependency mới; discord.py đã có sẵn. Test bằng `unittest`, chạy: `python -m unittest tests.<module> -v` từ d:\Bothvhn.
- Role gate bot: đúng tên `"Dân làng Hua Tát"`. Role mở kênh cũ: `"Thành viên"` (giữ nguyên).
- Kênh mới: đúng tên `"hướng-dẫn-dùng-bot"`. Tra role/kênh theo tên.
- `intents.members` đã bật ở `bot.py:148` — không cần đổi; chỉ ghi chú cần bật Server Members Intent trên Developer Portal.
- Idempotent: `/setup` chạy lại không tạo trùng role/kênh/message.

---

### Task 1: Gate lệnh bot — `can_use_bot` + GatedCommandTree

**Files:**
- Modify: `bot.py` (thêm hằng, hàm `can_use_bot`, class `GatedCommandTree`, truyền `tree_cls` vào bot)
- Test: `tests/test_bot_gate.py` (tạo mới)

**Interfaces:**
- Produces: `bot.DAN_LANG_ROLE: str = "Dân làng Hua Tát"`; `bot.can_use_bot(user) -> bool` (True nếu user có `guild_permissions.administrator` HOẶC có role tên `DAN_LANG_ROLE`); `bot.GatedCommandTree(app_commands.CommandTree)`.

- [ ] **Step 1: Viết test**

Tạo `tests/test_bot_gate.py`:

```python
import unittest
from bot import can_use_bot, DAN_LANG_ROLE


class _Perms:
    def __init__(self, administrator): self.administrator = administrator


class _Role:
    def __init__(self, name): self.name = name


class _User:
    def __init__(self, administrator=False, roles=()):
        self.guild_permissions = _Perms(administrator)
        self.roles = list(roles)


class BotGateTest(unittest.TestCase):
    def test_admin_allowed_without_role(self):
        self.assertTrue(can_use_bot(_User(administrator=True)))

    def test_role_allowed_without_admin(self):
        self.assertTrue(can_use_bot(_User(roles=[_Role(DAN_LANG_ROLE)])))

    def test_neither_denied(self):
        self.assertFalse(can_use_bot(_User(roles=[_Role("Thành viên")])))

    def test_dm_user_without_guild_perms_denied(self):
        class _Bare:  # giống discord.User trong DM: khong co guild_permissions/roles
            pass
        self.assertFalse(can_use_bot(_Bare()))


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Chạy test — phải fail**

Run: `python -m unittest tests.test_bot_gate -v`
Expected: FAIL (`ImportError: cannot import name 'can_use_bot'`).

- [ ] **Step 3: Thêm hàm + tree vào bot.py**

Trong `bot.py`, sau dòng `from discord.ext import commands` thêm import:

```python
from discord import app_commands
```

Trước `class HVHNBot`, thêm:

```python
DAN_LANG_ROLE = "Dân làng Hua Tát"


def can_use_bot(user) -> bool:
    perms = getattr(user, "guild_permissions", None)
    if perms is not None and getattr(perms, "administrator", False):
        return True
    roles = getattr(user, "roles", None) or []
    return any(getattr(role, "name", None) == DAN_LANG_ROLE for role in roles)


class GatedCommandTree(app_commands.CommandTree):
    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if can_use_bot(interaction.user):
            return True
        guide = None
        if interaction.guild is not None:
            guide = discord.utils.get(interaction.guild.text_channels, name="hướng-dẫn-dùng-bot")
        where = guide.mention if guide else "#hướng-dẫn-dùng-bot"
        try:
            await interaction.response.send_message(
                f"Bạn cần đọc {where} và bấm xác nhận để nhận vai trò \"{DAN_LANG_ROLE}\" trước khi dùng bot.",
                ephemeral=True,
            )
        except discord.InteractionResponded:
            pass
        return False

    async def on_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError) -> None:
        if isinstance(error, app_commands.CheckFailure):
            return
        await super().on_error(interaction, error)
```

Trong `HVHNBot.__init__`, đổi lời gọi super để dùng tree tùy biến:

```python
        super().__init__(command_prefix="!", intents=intents, tree_cls=GatedCommandTree)
```

- [ ] **Step 4: Chạy test — phải pass**

Run: `python -m unittest tests.test_bot_gate -v`
Expected: PASS 4/4.

- [ ] **Step 5: Commit**

```bash
git add bot.py tests/test_bot_gate.py
git commit -m "Gate all bot commands behind Dan lang Hua Tat role"
```

---

### Task 2: Role + kênh hướng dẫn + BotGuideView

**Files:**
- Modify: `cogs/setup.py` (thêm role vào `roles_to_create`; thêm kênh; thêm `build_guide_embed`; thêm `BotGuideView`; đăng ký view trong `setup()`; đăng embed+view vào kênh)
- Test: `tests/test_bot_guide.py` (tạo mới)

**Interfaces:**
- Consumes: `DAN_LANG_ROLE` (import từ `bot`).
- Produces: `cogs.setup.build_guide_embed() -> discord.Embed`; `cogs.setup.BotGuideView` (persistent, nút `custom_id="confirm_bot_guide"`).

- [ ] **Step 1: Viết test**

Tạo `tests/test_bot_guide.py`:

```python
import unittest
from cogs.setup import build_guide_embed, BotGuideView


class BotGuideTest(unittest.TestCase):
    def test_guide_embed_has_key_sections(self):
        embed = build_guide_embed()
        blob = embed.title + " " + (embed.description or "") + " ".join(
            f.name + " " + f.value for f in embed.fields
        )
        self.assertIn("làm được", blob.lower())
        self.assertIn("hạn chế", blob.lower())
        self.assertIn("prompt", blob.lower())

    def test_guide_view_button_custom_id(self):
        view = BotGuideView()
        ids = [c.custom_id for c in view.children if hasattr(c, "custom_id")]
        self.assertIn("confirm_bot_guide", ids)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Chạy test — phải fail**

Run: `python -m unittest tests.test_bot_guide -v`
Expected: FAIL (`ImportError: cannot import name 'build_guide_embed'`).

- [ ] **Step 3: Thêm import + build_guide_embed + BotGuideView**

Đầu `cogs/setup.py`, sau các import hiện có thêm:

```python
from bot import DAN_LANG_ROLE
```

Thêm hàm thuần (module-level, trước `class VerifyView`):

```python
def build_guide_embed() -> discord.Embed:
    embed = discord.Embed(
        title="📖 HƯỚNG DẪN DÙNG BOT THEN",
        description=(
            "Đọc hết trước khi bấm nút cuối để nhận quyền dùng bot. "
            "Hiểu đúng khả năng và giới hạn của Then giúp bạn khai thác tối đa sức mạnh AI."
        ),
        color=0x1abc9c,
    )
    embed.add_field(
        name="Then làm được gì",
        value=(
            "• Hỏi đáp, phân tích tác phẩm, tác giả, nhận định văn học.\n"
            "• Lập dàn ý chi tiết cho nghị luận xã hội và nghị luận văn học (cả mức HSG).\n"
            "• Gợi ý hệ thống luận điểm, lí lẽ, dẫn chứng và hướng phản biện.\n"
            "• Tra nhận định/trích dẫn trong kho tài liệu đã nạp."
        ),
        inline=False,
    )
    embed.add_field(
        name="Hạn chế — đọc kỹ",
        value=(
            "• AI có thể sai hoặc \"ảo giác\": luôn tự kiểm chứng lại kiến thức trước khi dùng.\n"
            "• Không chép nguyên văn trích dẫn nếu không có trong tài liệu; đừng tin tuyệt đối trí nhớ của AI.\n"
            "• Then hỗ trợ tư duy, KHÔNG làm thay bài của bạn; hãy tự viết dựa trên gợi ý.\n"
            "• Kiến thức ngoài kho tài liệu có thể thiếu chính xác."
        ),
        inline=False,
    )
    embed.add_field(
        name="Mẹo đặt prompt khai thác tối đa",
        value=(
            "• Nêu rõ dạng đề: nghị luận xã hội hay văn học, mức thường hay HSG.\n"
            "• Nói rõ bạn cần gì: dàn ý hay viết bài, phân tích khía cạnh nào.\n"
            "• Cung cấp ngữ liệu/đoạn trích khi hỏi về một văn bản cụ thể.\n"
            "• Hỏi từng bước, đào sâu dần thay vì một câu chung chung."
        ),
        inline=False,
    )
    embed.set_footer(text="Bấm nút bên dưới để xác nhận đã đọc và mở khóa quyền dùng bot.")
    return embed


class BotGuideView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Tôi đã đọc — Nhận quyền dùng bot", style=discord.ButtonStyle.success, emoji="🤖", custom_id="confirm_bot_guide")
    async def confirm_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        role = discord.utils.get(interaction.guild.roles, name=DAN_LANG_ROLE)
        if not role:
            await interaction.response.send_message(f"Lỗi hệ thống: chưa có vai trò \"{DAN_LANG_ROLE}\". Nhờ admin chạy /setup.", ephemeral=True)
            return
        if role in interaction.user.roles:
            await interaction.response.send_message("Bạn đã có quyền dùng bot Then rồi!", ephemeral=True)
        else:
            await interaction.user.add_roles(role)
            await interaction.response.send_message(f"🤖 Đã mở khóa quyền dùng bot Then. Chào mừng \"Dân làng Hua Tát\"!", ephemeral=True)
```

- [ ] **Step 4: Thêm role vào roles_to_create**

Trong `setup_server`, thêm vào list `roles_to_create` (sau dòng "Chiến thần Nghị luận"):

```python
            {"name": "Dân làng Hua Tát", "color": discord.Color.teal(), "hoist": False, "perms": discord.Permissions.none()}
```

- [ ] **Step 5: Tạo kênh + đăng embed/view (idempotent)**

Trong `setup_server`, sau dòng tạo `await get_or_create_text(info_cat, "bảng-tin-thông-báo")` (`cogs/setup.py:114`) thêm:

```python
        guide_channel = await get_or_create_text(info_cat, "hướng-dẫn-dùng-bot", overwrites=welcome_perms)
        guide_history = [msg async for msg in guide_channel.history(limit=5)]
        if not any(msg.author == guild.me for msg in guide_history):
            await guide_channel.send(embed=build_guide_embed(), view=BotGuideView())
```

- [ ] **Step 6: Đăng ký persistent view**

Trong `async def setup(bot)` cuối file, thêm trước `await bot.add_cog(...)`:

```python
    bot.add_view(BotGuideView())
```

- [ ] **Step 7: Chạy test + kiểm import cog**

Run: `python -m unittest tests.test_bot_guide -v`
Expected: PASS 2/2.
Run: `python -c "import cogs.setup"`
Expected: không lỗi import.

- [ ] **Step 8: Commit**

```bash
git add cogs/setup.py tests/test_bot_guide.py
git commit -m "Add bot guide channel, role, and confirm view"
```

---

### Task 3: on_member_join + welcome embed + auto-link kênh

**Files:**
- Modify: `cogs/setup.py` (thêm `build_welcome_embed`; listener `on_member_join`; đổi `rules_embed` dùng mention kênh)
- Test: `tests/test_welcome_embed.py` (tạo mới)

**Interfaces:**
- Produces: `cogs.setup.build_welcome_embed(member_mention: str, rules_mention: str, verify_mention: str, guide_mention: str) -> discord.Embed` — pure, chèn cả 4 chuỗi mention vào nội dung.

- [ ] **Step 1: Viết test**

Tạo `tests/test_welcome_embed.py`:

```python
import unittest
from cogs.setup import build_welcome_embed


class WelcomeEmbedTest(unittest.TestCase):
    def test_all_mentions_present(self):
        embed = build_welcome_embed("<@111>", "<#222>", "<#333>", "<#444>")
        blob = (embed.description or "") + " ".join(f.name + " " + f.value for f in embed.fields)
        for m in ("<@111>", "<#222>", "<#333>", "<#444>"):
            self.assertIn(m, blob)

    def test_mentions_two_gates(self):
        embed = build_welcome_embed("<@1>", "<#2>", "<#3>", "<#4>")
        blob = (embed.description or "") + " ".join(f.name + " " + f.value for f in embed.fields)
        self.assertIn("Thành viên", blob)
        self.assertIn("Dân làng Hua Tát", blob)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Chạy test — phải fail**

Run: `python -m unittest tests.test_welcome_embed -v`
Expected: FAIL (`ImportError: cannot import name 'build_welcome_embed'`).

- [ ] **Step 3: Thêm build_welcome_embed (module-level, cạnh build_guide_embed)**

```python
def build_welcome_embed(member_mention: str, rules_mention: str, verify_mention: str, guide_mention: str) -> discord.Embed:
    embed = discord.Embed(
        title="🎉 Chào mừng đến với Hồn Văn - Hồn Người!",
        description=f"Rất vui được đón {member_mention}. Hoàn thành 2 bước sau để mở khóa đầy đủ:",
        color=0x2ecc71,
    )
    embed.add_field(
        name="Bước 1 — Mở khóa các kênh",
        value=f"Đọc luật ở {rules_mention}, rồi vào {verify_mention} bấm nút để nhận vai trò **Thành viên**.",
        inline=False,
    )
    embed.add_field(
        name="Bước 2 — Mở khóa quyền dùng bot Then",
        value=f"Đọc {guide_mention}, rồi bấm nút xác nhận để nhận vai trò **Dân làng Hua Tát** và bắt đầu dùng bot.",
        inline=False,
    )
    return embed
```

- [ ] **Step 4: Thêm listener on_member_join vào class Setup**

Trong `class Setup`, thêm method:

```python
    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        guild = member.guild
        welcome = discord.utils.get(guild.text_channels, name="sảnh-chào-mừng")
        if welcome is None:
            return
        rules = discord.utils.get(guild.text_channels, name="luật-lệ")
        verify = discord.utils.get(guild.text_channels, name="cổng-xác-nhận")
        guide = discord.utils.get(guild.text_channels, name="hướng-dẫn-dùng-bot")
        embed = build_welcome_embed(
            member.mention,
            rules.mention if rules else "#luật-lệ",
            verify.mention if verify else "#cổng-xác-nhận",
            guide.mention if guide else "#hướng-dẫn-dùng-bot",
        )
        try:
            await welcome.send(content=member.mention, embed=embed)
        except discord.Forbidden:
            pass
```

- [ ] **Step 5: Auto-link kênh trong rules_embed**

Trong `rules_embed`, Chương II (`cogs/setup.py:152-160`) và Chương VII (`:197-201`) đang nhắc tên kênh dạng chữ. Sửa dùng mention của channel object đã tạo. Trước khi dựng `rules_embed`, lấy các channel object (chúng đã được tạo phía trên; lấy lại bằng `discord.utils.get`):

```python
        qa_ch = discord.utils.get(guild.text_channels, name="hỏi-đáp-bài-tập") or discord.utils.get(guild.forums, name="hỏi-đáp-bài-tập")
        share_ch = discord.utils.get(guild.text_channels, name="chia-sẻ-tài-liệu") or discord.utils.get(guild.forums, name="chia-sẻ-tài-liệu")
        discuss_ch = discord.utils.get(guild.text_channels, name="thảo-luận-văn-học")
        news_ch = discord.utils.get(guild.text_channels, name="bảng-tin-thông-báo")
        def _m(ch, fallback):
            return ch.mention if ch else fallback
```

Trong Chương II `value`, thay `hỏi-đáp-bài-tập` → `{_m(qa_ch, 'hỏi-đáp-bài-tập')}`, `chia-sẻ-tài-liệu` → `{_m(share_ch, 'chia-sẻ-tài-liệu')}`, `thảo-luận-văn-học` → `{_m(discuss_ch, 'thảo-luận-văn-học')}` (chuyển chuỗi value thành f-string). Trong Chương VII, `bảng-tin-thông-báo` → `{_m(news_ch, 'bảng-tin-thông-báo')}` (f-string). Giữ nguyên các câu chữ còn lại.

- [ ] **Step 6: Chạy test + kiểm import**

Run: `python -m unittest tests.test_welcome_embed -v`
Expected: PASS 2/2.
Run: `python -c "import cogs.setup"`
Expected: không lỗi.

- [ ] **Step 7: Regression toàn suite**

Run: `python -m unittest discover -s tests -v`
Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add cogs/setup.py tests/test_welcome_embed.py
git commit -m "Add member-join welcome and auto-linked channel mentions"
```

---

## Self-Review

**Spec coverage:**
- Fix không thông báo người mới → Task 3 (`on_member_join`). ✔
- Tên kênh không trỏ → Task 3 (welcome dùng mention) + Task 3 Step 5 (rules_embed mention). ✔
- Kênh hướng dẫn + role + confirm → Task 2. ✔
- Gate toàn bộ lệnh bot, admin miễn → Task 1 (`GatedCommandTree`, `can_use_bot`). ✔
- Nút sống sau restart → Task 2 Step 6 (`bot.add_view(BotGuideView())`). ✔
- 2 gate tách biệt (Thành viên vs Dân làng Hua Tát) → Task 1+2, welcome nêu cả hai. ✔

**Placeholder scan:** không TBD/TODO; mọi step có code/command.

**Type consistency:** `can_use_bot(user)->bool`, `build_guide_embed()->Embed`, `build_welcome_embed(4 str)->Embed`, `BotGuideView` custom_id `"confirm_bot_guide"`, `DAN_LANG_ROLE="Dân làng Hua Tát"` — nhất quán Task 1→2→3.

**Lưu ý reviewer:** (1) `cogs/setup.py` import `from bot import DAN_LANG_ROLE` tạo phụ thuộc cog→bot; đảm bảo `import bot` không chạy side-effect (main() nằm trong `__main__`, load_dotenv vô hại). (2) `GatedCommandTree.interaction_check` chặn app command nhưng KHÔNG chặn nút (component) → confirm/verify vẫn cấp role được — điểm cần verify. (3) forum channel `hỏi-đáp-bài-tập`/`chia-sẻ-tài-liệu` có thể là forum, mention vẫn hợp lệ.
