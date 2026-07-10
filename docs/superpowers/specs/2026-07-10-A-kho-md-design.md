# Spec — Nhóm A: Kho tài liệu bot chuyển sang .md + structured extraction

Ngày: 2026-07-10
Repo: `D:\Bothvhn` — bot AI "Then"
File lõi: `pdf_knowledge.py` (đổi vai), `cogs/ai.py`, `cogs/doc_storage.py`, `watcher.py`, `phanphoi.gs`, `bot.py` (schema).

## 1. Mục tiêu (chốt với chủ)

- **Bot AI chỉ đọc/trích/dùng dữ liệu từ file `.md`.** Xoá sạch kho PDF của bot.
- Nạp .md qua **Google Form** (không qua Discord command nữa).
- Trích tri thức bằng **structured extraction tại ingestion** (không chunk-thuần) — khớp nhóm B: quote→author là fact cố định, không đoán runtime.
- **Quy ước markdown nhẹ + parse thuật toán** (không cần LLM): nhận định ghi dạng `> "trích dẫn" — Tác giả`; heading `#`/`##` phân đoạn.
- **Xoá kho PDF ngay** (wipe `bot_docs/` + bảng `ai_pdf_*`, bỏ index PDF vào AI).
- Kho **"tri thức thủ công" (`ai_knowledge`) giữ riêng** nhưng **sửa retrieval**: nắm từ khoá + suy luận + kết hợp tri thức liên quan, KHÔNG đòi query trùng title, không chép nguyên văn.

## 2. Parser bao dung định dạng (SỬA 2026-07-10 theo file thật của chủ)

KHÔNG bắt người soạn theo quy ước cứng — tài liệu thật đa dạng (danh sách `+`/`-`, thơ nhiều dòng, bản convert pandoc...). Parser tự thích nghi:

- **Passage:** heading `#..######` nếu có; KHÔNG có heading → tự chia theo đoạn văn (block ~1200 ký tự); section quá 1500 ký tự cũng tự cắt (giữ title, đánh "(tiếp n)").
- **Fact nhận định (quote→author), trích khi dòng MỞ ĐẦU bằng nhận định:** `+ "…" (Tác giả)`, `- "…" (Tác giả)`, `> "…" — Tác giả`, `* "…" (Tác giả)`, hoặc ngoặc kép đứng đầu dòng; thơ nhiều dòng với `(Tác giả)` ở dòng dưới cũng bắt được.
- **Chuẩn hoá tác giả:** bỏ danh xưng (Nhà thơ/Nhà văn/Nhà nghiên cứu/GS/TS...), cắt phần tiểu sử sau dấu phẩy/gạch ("Pablo Neruda, nhà thơ..." → "Pablo Neruda"; "Lý Nhuệ - Trung Quốc" → "Lý Nhuệ"); nhận tên phiên âm ("Sê khốp").
- **Chống fact rác:** quote nằm GIỮA câu (vd tên tác phẩm `bài thơ "X" (Tác giả)`) không bị trích thành nhận định; chuỗi không giống tên người bị loại.
- **Tiền xử lý pandoc:** gỡ `\+ \- \"`, span `[x]{.mark}`, `**`.
- Frontmatter YAML tùy chọn (`---\ntitle: ...\n---`) → metadata; không có thì lấy dòng đầu làm title.
- Đo trên kho thật của chủ (`D:\Download 2\new hvhn bot doc (md)`): "nhan dinh van chuong.md" trích 152/153 nhận định có tác giả; file mô hình/tiểu luận không sinh fact rác.

## 3. Kiến trúc

### 3.1 Ingestion .md (`md_knowledge.py` — module mới)
- `parse_markdown(text) -> {passages: [{title, content}], quotes: [{quote, author, passage_title}]}`.
  - Passage: cắt theo heading; gộp nội dung tới heading kế.
  - Quote: regex blockquote có ` — Author` / ` (Author)`; author rỗng nếu không khớp mẫu (KHÔNG đoán).
- `index_md_bytes(db, title, data, source, created_by)`: parse → lưu passages (retrieval) + quotes (facts) vào DB, idempotent theo content_hash (như `index_pdf_bytes`).

### 3.2 DB (bot.py SCHEMA + md_knowledge)
- Bảng mới `ai_md_documents(doc_key, title, source, content_hash, passage_count, updated_at)`.
- `ai_md_passages(doc_key, idx, title, content, source, updated_at)` + FTS/trigram index như ai_pdf_chunks.
- `ai_md_quotes(doc_key, quote, author, passage_title, source)` — fact quote→author.
- Bỏ dùng `ai_pdf_*` cho AI (giữ bảng nhưng ngừng ghi; wipe nội dung).

### 3.3 Retrieval (cogs/ai.py + md_knowledge)
- `retrieve_md_knowledge(db, query, limit)` trả pdf_meta-shape (`chunks` = passages) + `quotes` (facts) để `QuoteExtractor`/`Formatter.evidence_block` dùng trực tiếp (không đoán author runtime — dùng fact).
- ai.py thay `retrieve_pdf_knowledge` → `retrieve_md_knowledge`. `QuoteExtractor.extract` ưu tiên dùng `quotes` fact sẵn có; chỉ khi passage có ngoặc kép mà không có fact mới áp l=strict (nhóm B).

### 3.4 Nạp .md qua Google Form (phanphoi.gs)
- Form ③ "Nạp tài liệu .md cho bot" (upload .md) → folder `_don_them_tai_lieu_bot_md` → watcher.
- Handler onFormSubmit copy .md vào folder đơn (giống Form tài liệu PDF).

### 3.5 Watcher (watcher.py)
- Thêm `xu_ly_don_them_md`: quét `_don_them_tai_lieu_bot_md`, đọc .md, gọi `index_md_bytes`. Bỏ nhánh nạp PDF-bot (`INCOMING_BOT_DOCS`) khỏi AI (giữ client distribution).

### 3.6 Gỡ Discord (cogs/doc_storage.py)
- Bỏ command nạp tài liệu-bot: `hvhn_themtailieu`, `hvhn_nap_link`, `hvhn_nap_tailieu` (bot-doc). Giữ command khách/phân phối.

### 3.7 Wipe kho PDF
- Script/command 1 lần: xoá `bot_docs/*`, `TRUNCATE ai_pdf_documents, ai_pdf_chunks`. Bỏ index PDF trong `add_document` (không còn nạp bot PDF).

### 3.8 Sửa retrieval ai_knowledge (`pdf_knowledge.py`/nơi query ai_knowledge)
- Query hiện chỉ khớp khi ~trùng title → đổi sang: tách từ khoá query, FTS/trigram trên `title+content`, trả top-k liên quan (không cần trùng title). AI được kết hợp nhiều tri thức, diễn giải (không chép nguyên văn). Grounding B vẫn áp: quote nguyên văn phải khớp nguồn.

## 4. Phân rã (mỗi phần 1 plan → có thể làm/merge độc lập)

- **A1 — Thư viện .md (Python, testable):** `md_knowledge.py` (parse + index) + bảng DB. TDD được. *Nền tảng.*
- **A2 — Wire ai.py sang .md + dùng quote-fact:** đổi retrieval, evidence từ fact. TDD phần parse/evidence.
- **A3 — Fix retrieval ai_knowledge:** keyword/kết hợp thay title-exact. TDD được.
- **A4 — Google Form .md + watcher ingest:** Apps Script (không test ở máy) + watcher job. Chủ deploy+test.
- **A5 — Wipe + gỡ Discord command + ngừng index PDF:** phá hủy dữ liệu → chạy khi chủ xác nhận.

## 5. Phạm vi / thứ tự

Làm A1 → A2 → A3 (Python, testable, merge dần vào main) trước; A4 (Apps Script) + A5 (wipe/gỡ, phá hủy) làm sau cùng khi chủ sẵn sàng deploy+test. A5 KHÔNG tự ý chạy.

## 6. Rủi ro / giả định

- Wipe ai_pdf_* + bot_docs là **phá hủy** → chỉ chạy khi chủ xác nhận; backup trước.
- Chủ phải soạn .md theo quy ước để quote→author trích đúng; sai quy ước → author rỗng (an toàn, không bịa).
- Apps Script `addFileUploadItem` không tạo được bằng code → câu hỏi upload .md phải thêm tay 1 lần (như Form PDF, xem MEMORY.md mục 2).
- Client distribution (watermark PDF) KHÔNG đổi — chỉ kho tri thức BOT chuyển .md.
