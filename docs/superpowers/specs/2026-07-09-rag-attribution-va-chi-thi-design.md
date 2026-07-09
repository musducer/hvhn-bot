# Spec — Nhóm B (RAG gán tác giả / chống hallucination) + phần C (ống chỉ thị)

Ngày: 2026-07-09
Repo: `D:\Bothvhn` — bot AI Ngữ Văn "Then"
File lõi: `cogs/ai.py`, `pdf_knowledge.py`, `SYSTEM INSTRUCTIONS.txt`, `BONUS.txt`

## 1. Vấn đề (đã xác nhận với hình root-cause)

Bug nghiêm trọng nhất: **gán sai tác giả** (vd Nam Cao ↔ Nguyễn Minh Châu). 5 root cause:

| # | Root cause | Code |
|---|---|---|
| 1 🔴 | Quote extraction ở **runtime** thay vì ingestion | `QuoteExtractor.extract()` chạy mỗi query |
| 2 🔴 | Author attribution dùng **heuristic khoảng cách** | `ai.py:371` `score = 0.65 - distance/300 + verb_bonus + colon_bonus` |
| 3 🔴 | **Chunk** là đơn vị tri thức duy nhất | `ai.py:389` lặp `chunks`, 1 chunk nhiều tác giả/quote |
| 4 🟠 | Fallback sang **sentence** khi không có quote | `ai.py:392-394` mảnh câu bị coi là nguyên văn |
| 5 🟠 | Context là **string** thay vì object | Formatter nối chuỗi, LLM tự suy luận lại quan hệ |

Bug phụ (phần C): AI **không tiếp thu** `SYSTEM INSTRUCTIONS.txt` + `BONUS.txt`:
- `SYSTEM_EXTRA_MAX_CHARS = 1500` (`ai.py:25`) cắt file 164 dòng còn 1500 ký tự → mất 75%.
- Chỉ thị nhét vào **user prompt** (`ai.py:1175`) chứ không vào `system_prompt` thật.
- `BONUS.txt` **không được load** ở bất kỳ đâu.

Hệ quả: văn phong khô cứng, còn ảo giác, không theo giao thức chống hallucination trong file.

## 2. Nguyên tắc thiết kế

Gốc chung của 5 root cause: **tri thức không được cấu trúc hoá tại ingestion mà bị đoán lại bằng heuristic tại runtime.**

Nhưng người dùng hỏi rất rộng (phân tích, dàn ý, gợi ý ý tưởng, đề xuất dẫn chứng...), không chỉ hỏi nhận định. Nên **KHÔNG** thu hẹp AI về máy trích quote. Giải pháp: **2 tầng tri thức tách bạch.**

### Tầng 1 — Fact gán tác giả (chống bug)
- Trích `quote → author` **tại ingestion**, một lần/tài liệu.
- Chỉ gán tác giả khi văn bản **nói thẳng** (verb attribution / dấu hai chấm **ngay sát** quote: "X viết:", "X cho rằng"). Không thẳng → `author = UNKNOWN`.
- **Bỏ hoàn toàn** cách tính điểm theo khoảng cách (`0.65 - distance/300`). Không có "gần hơn nên chắc là của người này".
- Lưu thành object có cấu trúc `{quote, author, source, page, doc_id}` (attribution facts), không phải chuỗi.
- Runtime **không đoán lại** tác giả; chỉ tra cứu fact.

### Tầng 2 — Tri thức linh hoạt (phần lớn việc)
- Giữ retrieval semantic hiện tại cho phân tích/dàn ý/gợi ý/dẫn chứng.
- LLM **vận dụng tự do**, đan nhận định làm chất liệu dẫn dắt.
- Ràng buộc grounding: bất kỳ câu nào đặt **trong ngoặc kép + gán tên** phải khớp Tầng 1 hoặc văn bản user. Ngoài ra → diễn giải (không ngoặc kép) hoặc ghi rõ "theo trí nhớ, cần kiểm chứng".
- Intent rộng vẫn đi Tầng 2; quote chỉ là 1 nhánh, không phải cổng chặn.

### Bỏ fallback nguy hiểm (root cause 4)
- Bỏ nhánh biến "unit/sentence" thành quote khi không tìm được ngoặc kép (`ai.py:392-394`). Không có ngoặc kép → không có nguyên văn, chỉ diễn giải.

### Context là object (root cause 5)
- Truyền evidence cho LLM dưới dạng cấu trúc rõ ràng `author | quote | source`, không nối chuỗi mập mờ. (Đã có mầm ở `Formatter.compare_seed`; chuẩn hoá cho mọi intent quote.)

### Sửa ống chỉ thị (phần C)
- Nạp **trọn** `SYSTEM INSTRUCTIONS.txt` vào `system_prompt` thật (bỏ/nâng `SYSTEM_EXTRA_MAX_CHARS`, không cắt 1500; đưa vào system role, không vào user prompt).
- Nạp `BONUS.txt` làm **ví dụ few-shot bad→good** dạy AI né đúng các lỗi trong file (chữ Trung chen ngang "描绘/批判", bịa "Thị bị bạo hành", hời hợt, sáo rỗng).
- Kết quả: văn phong ấm/giàu hình ảnh + giao thức chống hallucination thật sự tới model.

## 3. Phạm vi

**Trong phạm vi:** `cogs/ai.py` (QuoteExtractor, infer_author, extract, Formatter, build prompt, load instructions), `pdf_knowledge.py` (nơi lưu attribution facts khi ingestion nếu cần), `SYSTEM INSTRUCTIONS.txt`, `BONUS.txt`.

**Ngoài phạm vi (làm ở nhóm sau):** đổi kho tài liệu sang .md (nhóm A), cân bằng 3 nguồn sâu (một phần đã đụng ở Tầng 2 nhưng tinh chỉnh sau), Form nạp .md, sảnh chào mừng, watcher, gia hạn theo giờ, chương trình trải nghiệm.

## 4. Tiêu chí thành công

- Query "nhận định của Nam Cao về X" không bao giờ trả về quote của tác giả khác chỉ vì ở gần.
- Không tìm được nguyên văn → nói rõ "chưa tìm thấy nguyên văn... không bịa", không dựng mảnh câu thành quote.
- AI trả lời phân tích/dàn ý vẫn linh hoạt, đan nhận định làm dẫn dắt, không bị khoá về máy trích quote.
- Văn phong ấm, giàu hình ảnh theo SYSTEM INSTRUCTIONS.txt; không lặp lại lỗi trong BONUS.txt.
- Không còn trường hợp gán tác giả bằng khoảng cách.

## 5. Rủi ro / giả định

- Ingestion-time extraction cần chỗ lưu: nếu kho tài liệu sắp đổi sang .md (nhóm A), tránh làm 2 lần → attribution facts nên trích ở bước ingestion chung. Tạm thời trích trên kho hiện tại; khi sang .md tái dùng cùng hàm.
- Nạp trọn instructions làm prompt dài hơn → chú ý ngân sách token (Groq 413). Ưu tiên Gemini cho prompt dài, giữ nén context Tầng 2 khi cần.
