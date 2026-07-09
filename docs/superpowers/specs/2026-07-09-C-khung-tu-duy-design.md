# Spec — Nhóm C (sâu): Khung tư duy lập luận / dàn ý theo thể loại & bậc

Ngày: 2026-07-09
Repo: `D:\Bothvhn` — bot AI Ngữ Văn "Then"
File lõi: `cogs/ai.py` (`IntentClassifier`, `Planner`, `RAGPlan`, `_guarded_prompt`, luồng trả lời chính).

## 1. Vấn đề

Hiện mỗi câu hỏi chỉ truyền `CHE DO: {mode}` (một chuỗi suy từ intent) + seed quote cho COMPARE/ANALYSIS. **Không có khung tư duy/dàn ý riêng** cho từng loại bài. Hệ quả: AI phân tích sơ sài, không đào tận cùng, không có hệ thống luận điểm rõ, không phân biệt kiểu bài. (Phần văn phong khô + chống hallucination đã xử ở nhóm B; nhóm C lo phần *cấu trúc lập luận chủ động*.)

## 2. Nguyên tắc

Chèn **soft instruction block** hướng dẫn *cách lập luận + bố cục* theo loại bài, để AI tự sản sinh linh hoạt (không template cứng, không few-shot ép điền). Block chỉ dạy cách nghĩ/cách dựng bài — **không cấp kiến thức, không nới lỏng grounding** (mọi trích dẫn vẫn phải khớp evidence nhóm B). Text block trong prompt ngầm có thể tiếng Anh nếu gọn token; **đầu ra của AI luôn tiếng Việt** theo văn phong Học giả Ngữ Văn.

## 3. Ba chiều phân loại (thêm vào `RAGPlan` + `Planner`)

- **genre** ∈ {`NLXH`, `NLVH`, `NONE`}
  - NLXH: "tư tưởng đạo lí", "hiện tượng đời sống", "quan niệm sống", "ý kiến cho rằng", câu nói/châm ngôn về đời sống, "vô cảm", "lối sống"...
  - NLVH: "tác phẩm", "nhân vật", "đoạn thơ/bài thơ/đoạn trích", "phân tích ... trong ...", tên tác giả, nhận định lý luận văn học.
  - NONE: hỏi đáp thường (định nghĩa, tra cứu) → không chèn khung.
- **level** ∈ {`THUONG`, `HSG`} — áp cho cả NLXH và NLVH.
  - HSG khi có: "HSG", "học sinh giỏi", "đội tuyển", "chuyên", "cấp tỉnh/khu vực/quốc gia", hoặc đề dạng **nhận định LLVH/tư tưởng cần bàn/chứng minh**.
- **write_essay** ∈ {`False` (mặc định = dàn ý chi tiết), `True`}
  - True khi prompt nói rõ: "viết bài", "viết thành bài", "viết đoạn văn", "viết mở bài/kết bài", "viết hoàn chỉnh".
  - Mặc định (False) = **dàn ý chi tiết**: đào sâu từng ý — lí lẽ, dẫn chứng, phản biện, liên hệ mở rộng — **bất kể** prompt có chữ "chi tiết" hay không.

## 4. Nội dung các khung (soft block)

### NLXH — THUONG (dàn ý)
Mở (dẫn dắt + nêu vấn đề) → Giải thích từ khóa/khái niệm → Bàn luận (khẳng định đúng/sai + lí lẽ + dẫn chứng thực tế) → Phản biện/mở rộng (lật ngược, phê phán biểu hiện trái) → Bài học nhận thức & hành động → Kết.

### NLXH — HSG (dàn ý)
Như trên nhưng nâng: đề thường trừu tượng/đa nghĩa → **giải mã nhiều lớp nghĩa**; bàn luận có **chiều sâu nhân sinh + triết lí**; **phản biện đa tầng** (giới hạn vấn đề, điều kiện đúng/sai); dẫn chứng **đa dạng** (đời sống + văn học + nhân vật lịch sử); chất văn giàu hình ảnh, có dấu ấn tư duy cá nhân.

### NLVH — THUONG (dàn ý)
Mở (tác giả–tác phẩm–vấn đề, kèm nhận định nếu có) → Khái quát (hoàn cảnh sáng tác/vị trí đoạn) → **Hệ thống luận điểm** (mỗi luận điểm: nội dung + nghệ thuật + dẫn chứng + lời bình) → Đánh giá (giá trị nội dung/nghệ thuật, phong cách) → Liên hệ/mở rộng → Kết.

### NLVH — HSG (dàn ý)
Như trên nhưng nâng: bám **nhận định LLVH** làm trục (giải thích nhận định → chứng minh qua tác phẩm); vận dụng **thuật ngữ lý luận** (thi pháp, điểm nhìn, tình huống, giá trị nhân đạo...); **so sánh–liên hệ rộng** (tác phẩm cùng đề tài/thời kỳ); **phản biện đa chiều**; đánh giá **đóng góp/phong cách** tác giả; chất văn + sáng tạo.

### Điều biến theo intent
- `OUTLINE`: xuất ra dàn ý là chính.
- `ANALYSIS`/`COMPARE`: dùng khung tương ứng, nhấn hệ thống luận điểm / đối chiếu.
- `write_essay=True`: chuyển khung thành **mạch bài văn liền** (mở–thân–kết thành đoạn), giữ nguyên chiều sâu và các bước lập luận.

## 5. Cơ chế chèn (kỹ thuật)

- Thêm trường `genre: str = "NONE"`, `level: str = "THUONG"`, `write_essay: bool = False` vào `RAGPlan`.
- `Planner.build` điền 3 trường này (hàm phân loại riêng, dựa `_rag_plain`).
- Thêm builder thuần: `Scaffold.for_plan(plan: RAGPlan) -> str` trả soft block (chuỗi rỗng khi genre=NONE).
- Thêm tham số tùy chọn `guidance: str = ""` vào `_guarded_prompt`; nếu có thì chèn vào prompt cạnh khối `CHE DO`. **Mọi call site cũ giữ nguyên** (default rỗng).
- Luồng trả lời chính (`answer`/`_safe_generate`): tính `guidance = Scaffold.for_plan(plan)` và truyền vào.

## 6. Phạm vi

**Trong:** `cogs/ai.py` — phân loại genre/level/write_essay, `Scaffold`, chèn guidance. Test đơn vị cho phân loại + builder.
**Ngoài:** không đổi retrieval/grounding (nhóm B), không đổi kho tài liệu (nhóm A), không few-shot bài mẫu (đã có BONUS ở system prompt).

## 7. Tiêu chí thành công

- Đề NLXH → dàn ý có đủ: giải thích → bàn luận → phản biện → bài học; HSG thì đa tầng + chiều sâu.
- Đề NLVH → dàn ý có **hệ thống luận điểm** (ND+NT+dẫn chứng+bình) + đánh giá + liên hệ; HSG thì bám nhận định LLVH + so sánh rộng.
- Mặc định ra **dàn ý chi tiết**; prompt bảo "viết bài" → ra bài văn liền mạch.
- genre=NONE (hỏi đáp thường) → không chèn khung, không phình prompt vô ích.
- Không tăng rủi ro token/Groq quá mức (block ngắn gọn, ưu tiên súc tích).

## 8. Rủi ro / giả định

- Nhận diện genre/level bằng từ khóa có thể sai biên (đề mơ hồ) → chọn ngưỡng thận trọng; sai thì rơi về khung chung/NONE, không bịa.
- Guidance làm prompt dài thêm → giữ block ngắn (mỗi khung ~vài trăm ký tự); đường Groq đã có compact system prompt (nhóm B) nên chịu tải tốt.
