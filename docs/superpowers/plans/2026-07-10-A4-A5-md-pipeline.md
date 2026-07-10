# A4 + A5 — .md ingestion pipeline + gỡ kho PDF Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:subagent-driven-development. Steps use `- [ ]`. Worktree D:\Bothvhn-A (branch feat/kho-md).

**Goal:** Hoàn tất nhóm A — watcher nạp .md vào kho tri thức AI (A4); gỡ kho PDF cũ + command Discord nạp PDF + script wipe (A5). Apps Script Form .md: thêm code, chủ deploy tay.

**Architecture:** .md đi Google Form → folder `_don_them_tai_lieu_bot_md` (mirror) → watcher `xu_ly_don_them_md` → `index_md_path`. Bỏ mọi đường index PDF vào AI. Wipe là SCRIPT chủ chạy (không tự chạy).

**Tech Stack:** Python, asyncpg, Apps Script, unittest.

## Global Constraints

- Làm trong D:\Bothvhn-A. Test: `python -m unittest tests.<mod> -v`.
- KHÔNG tự chạy wipe/xoá dữ liệu thật. A5 chỉ TẠO script + gỡ code.
- Apps Script không test được ở máy → chủ deploy+test.
- Giữ hệ phân phối watermark cho KHÁCH (client) nguyên vẹn; chỉ gỡ phần index PDF vào AI.

---

## A4 — Thêm pipeline .md

### Task 1: `index_md_path` trong md_knowledge

**Files:** Modify `md_knowledge.py`; Test `tests/test_md_knowledge.py`.
**Interfaces:** `async index_md_path(database_url: str, path) -> dict` — mirror `pdf_knowledge.index_pdf_path` (đọc `pdf_knowledge.py:373-381` để bám): mở connection asyncpg, đọc bytes file, gọi `index_md_bytes`, đóng connection. `source`/`title` suy từ tên file.

- [ ] **Step 1: Test** — thêm vào `tests/test_md_knowledge.py`:

```python
import inspect
from md_knowledge import index_md_path


class IndexMdPathTest(unittest.TestCase):
    def test_index_md_path_is_async_and_reads_file(self):
        src = inspect.getsource(index_md_path)
        self.assertIn("index_md_bytes", src)
        self.assertIn("connect", src)
```

- [ ] **Step 2: Run — FAIL** (`ImportError: index_md_path`). `python -m unittest tests.test_md_knowledge -v`

- [ ] **Step 3: Đọc `pdf_knowledge.index_pdf_path` rồi thêm vào `md_knowledge.py`:**

```python
import asyncpg
import os as _os


async def index_md_path(database_url: str, path) -> dict:
    with open(path, "rb") as f:
        data = f.read()
    title = _os.path.splitext(_os.path.basename(str(path)))[0]
    conn = await asyncpg.connect(database_url)
    try:
        return await index_md_bytes(conn, title, data, source=str(path))
    finally:
        await conn.close()
```

- [ ] **Step 4: Run — PASS.** `python -m unittest tests.test_md_knowledge -v`
- [ ] **Step 5: Commit** `git add md_knowledge.py tests/test_md_knowledge.py; git commit -m "Add index_md_path for watcher ingestion"`

### Task 2: Watcher nạp .md + schema

**Files:** Modify `watcher.py`, `bot.py`.
**Interfaces:** folder `INCOMING_BOT_MD`; `async xu_ly_don_them_md()`; watcher schema có `MD_KNOWLEDGE_SCHEMA`.

- [ ] **Step 1: Test tĩnh** — `tests/test_watcher_md.py`:

```python
import inspect, unittest, watcher


class WatcherMdTest(unittest.TestCase):
    def test_has_md_handler_and_folder(self):
        self.assertTrue(hasattr(watcher, "xu_ly_don_them_md"))
        self.assertTrue(hasattr(watcher, "INCOMING_BOT_MD"))

    def test_main_loop_calls_md_handler(self):
        self.assertIn("xu_ly_don_them_md", inspect.getsource(watcher.main_async))
```

- [ ] **Step 2: Run — FAIL.** `python -m unittest tests.test_watcher_md -v`

- [ ] **Step 3: Sửa `watcher.py`:**
  - Import: đổi dòng `from md_knowledge import ...` (thêm nếu chưa): `from md_knowledge import MD_KNOWLEDGE_SCHEMA, index_md_path`.
  - Cạnh `INCOMING_BOT_DOCS` (dòng 36) thêm: `INCOMING_BOT_MD = os.path.join(MIRROR_PARENT, "_don_them_tai_lieu_bot_md")` và `PROCESSED_MD = os.path.join(MIRROR_PARENT, "_da_xu_ly_tai_lieu_bot_md")`.
  - Sau `DOC_JOB_SCHEMA += PDF_KNOWLEDGE_SCHEMA` (dòng 270) thêm: `DOC_JOB_SCHEMA += MD_KNOWLEDGE_SCHEMA`.
  - Thêm hàm (cạnh `xu_ly_don_them_tai_lieu_bot`):

```python
async def _index_md_for_ai(path):
    if not DATABASE_URL:
        return "db_failed"
    try:
        result = await index_md_path(DATABASE_URL, path)
        print(f"[AI MD] {os.path.basename(path)} -> {result.get('passages', 0)} passage", flush=True)
        await _set_runtime_status("ai_md_last_indexed", f"{result.get('title')} ({result.get('passages', 0)} passage)")
        return "indexed"
    except Exception as exc:
        print(f"[AI MD] index_failed file={os.path.basename(path)} err={type(exc).__name__}: {exc}", flush=True)
        traceback.print_exc()
        return "failed"


async def xu_ly_don_them_md():
    if not os.path.isdir(INCOMING_BOT_MD):
        return
    os.makedirs(PROCESSED_MD, exist_ok=True)
    files = [f for f in os.listdir(INCOMING_BOT_MD) if f.lower().endswith(".md")]
    for name in files:
        path = os.path.join(INCOMING_BOT_MD, name)
        if not _stable(path):
            continue
        await _index_md_for_ai(path)
        try:
            dest = _unique_path(PROCESSED_MD, name)
            os.replace(path, dest)
        except Exception:
            traceback.print_exc()
```

  - Trong `main_async` loop, sau `await xu_ly_don_them_tai_lieu_bot()` (dòng 918) thêm: `await xu_ly_don_them_md()`.
  - `bot.py`: sau `from pdf_knowledge import PDF_KNOWLEDGE_SCHEMA` thêm `from md_knowledge import MD_KNOWLEDGE_SCHEMA`; sau `SCHEMA += PDF_KNOWLEDGE_SCHEMA` (dòng 142) thêm `SCHEMA += MD_KNOWLEDGE_SCHEMA`.

- [ ] **Step 4: Run — PASS** `python -m unittest tests.test_watcher_md -v`; và `python -c "import watcher, bot"` sạch.
- [ ] **Step 5: Commit** `git add watcher.py bot.py tests/test_watcher_md.py; git commit -m "Watcher ingests markdown docs into AI knowledge"`

### Task 3: Apps Script Form .md (chủ deploy)

**Files:** Modify `phanphoi.gs`.
**Interfaces:** hằng tên folder `INCOMING_BOT_MD_NAME`; hàm `taoLaiFormMd()` (tạo Form + trigger); handler `xuLyFormMd(e)` copy .md vào folder; menu item.

- [ ] **Step 1:** Đọc trong `phanphoi.gs` mẫu `taoLaiFormBot`/`xuLyFormTaiLieu` (Form nạp PDF cho bot) để nhái y hệt cho .md. Thêm:
  - Hằng: `const INCOMING_BOT_MD_NAME = '_don_them_tai_lieu_bot_md';`
  - `taoLaiFormMd()`: tạo Form "Nạp tài liệu .md cho bot" (title + mô tả nhắc chủ dùng quy ước: heading phân đoạn, `> "…" — Tác giả`), tạo trigger onFormSubmit `xuLyFormMd`. (GHI CHÚ trong code: câu hỏi upload file .md phải THÊM TAY 1 lần trong giao diện Form — `addFileUploadItem` không tồn tại; xem MEMORY.md mục 2.)
  - `xuLyFormMd(e)`: lấy file upload từ response, copy vào folder `INCOMING_BOT_MD_NAME` (getOrCreateFolder dưới HVHN parent), ghiLog.
  - Menu (`onOpen`): thêm `.addItem('📱 Tạo lại RIÊNG Form nạp .md cho bot', 'taoLaiFormMd')` cạnh item Form bot hiện có.
- [ ] **Step 2:** Không test máy được. Chỉ kiểm cú pháp bằng mắt + đảm bảo tên hàm khớp menu. Commit `git add phanphoi.gs; git commit -m "Add Google Form for markdown bot docs (Apps Script)"`.

---

## A5 — Gỡ kho PDF + wipe script

### Task 4: Gỡ command Discord nạp PDF cho bot + dead import

**Files:** Modify `cogs/doc_storage.py`, `cogs/ai.py`.

- [ ] **Step 1:** Trong `cogs/doc_storage.py` XOÁ các command nạp PDF cho BOT (giữ command KHÁCH/phân phối): `hvhn_themtailieu` (add_document), `hvhn_nap_link` (add_bot_document_link), `hvhn_nap_tailieu` (add nhiều PDF bot). Gỡ `index_pdf_bytes` khỏi mọi đường (AI không index PDF nữa) — nếu `_enqueue_and_index_pdf`/`_enqueue_pdf_url` chỉ còn phục vụ bot-doc thì xoá; nếu client-doc còn dùng thì bỏ nhánh `index_pdf_bytes` (chỉ enqueue job watermark, không index AI). Gỡ import `from pdf_knowledge import index_pdf_bytes, pdf_knowledge_stats` nếu không còn dùng (giữ `pdf_knowledge_stats` nếu report còn cần).
- [ ] **Step 2:** Trong `cogs/ai.py` xoá dòng dead import `from pdf_knowledge import retrieve_pdf_knowledge, search_pdf_knowledge` (A2 đã chuyển sang md, không còn call site).
- [ ] **Step 3:** `python -c "import cogs.doc_storage, cogs.ai"` sạch; `python -m unittest discover -s tests -v` không hồi quy (trừ 3 test watcher/pdf môi-trường-worktree đã biết).
- [ ] **Step 4: Commit** `git add cogs/doc_storage.py cogs/ai.py; git commit -m "Remove PDF bot-doc commands and dead PDF imports"`

### Task 5: Script wipe kho PDF (chủ chạy tay)

**Files:** Create `wipe_pdf_store.py`.

- [ ] **Step 1:** Tạo `wipe_pdf_store.py` — script standalone, in cảnh báo + yêu cầu gõ `WIPE` xác nhận (argv `--yes` để bỏ prompt), rồi: `TRUNCATE ai_pdf_documents, ai_pdf_chunks` (asyncpg từ `DATABASE_URL`) và xoá `bot_docs/*`. KHÔNG chạy trong test/CI. Có `if __name__ == "__main__"`.

```python
import asyncio, os, sys, shutil, glob
import asyncpg
from dotenv import load_dotenv

load_dotenv()
BOT_DOCS_DIR = os.getenv("HVHN_BOT_DOCS_DIR", os.path.join(os.path.dirname(os.path.abspath(__file__)), "bot_docs"))


async def _wipe_db():
    url = os.getenv("DATABASE_URL")
    if not url:
        print("Thieu DATABASE_URL"); return
    conn = await asyncpg.connect(url)
    try:
        await conn.execute("TRUNCATE ai_pdf_documents, ai_pdf_chunks")
        print("Da TRUNCATE ai_pdf_documents, ai_pdf_chunks")
    finally:
        await conn.close()


def _wipe_files():
    n = 0
    for p in glob.glob(os.path.join(BOT_DOCS_DIR, "*")):
        try:
            if os.path.isfile(p): os.remove(p)
            else: shutil.rmtree(p)
            n += 1
        except Exception as e:
            print(f"Loi xoa {p}: {e}")
    print(f"Da xoa {n} muc trong {BOT_DOCS_DIR}")


def main():
    if "--yes" not in sys.argv:
        print("CANH BAO: se XOA SACH kho PDF cu (bang ai_pdf_* + bot_docs/). Khong the hoan tac.")
        if input("Go 'WIPE' de xac nhan: ").strip() != "WIPE":
            print("Huy."); return
    asyncio.run(_wipe_db())
    _wipe_files()
    print("Hoan tat wipe kho PDF. AI gio chi doc kho .md.")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2:** `python -c "import ast; ast.parse(open('wipe_pdf_store.py',encoding='utf-8').read())"` OK (không chạy script). Commit `git add wipe_pdf_store.py; git commit -m "Add manual wipe script for legacy PDF store"`.

---

## Self-Review

**Spec coverage:** A4 — index_md_path (T1), watcher .md + schema (T2), Apps Script Form (T3); A5 — gỡ command+import (T4), wipe script (T5). ✔
**Placeholder scan:** không TBD; code cụ thể. Apps Script T3 mô tả bám mẫu hàm sẵn có (subagent đọc `taoLaiFormBot`/`xuLyFormTaiLieu`).
**An toàn:** wipe KHÔNG auto-chạy (prompt/`--yes`); watcher .md additive; A5 gỡ chỉ đụng bot-doc, giữ client watermark.
**Lưu ý:** nhóm A vẫn KHÔNG merge tới khi chủ deploy Form, nạp .md thật, chạy wipe. Sau đó mới merge branch feat/kho-md vào main.
