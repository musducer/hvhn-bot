# RAG Attribution Fix + Instruction Pipeline — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Diệt bug gán sai tác giả + chống hallucination + đưa trọn chỉ thị văn phong tới model, mà không thu hẹp khả năng phân tích/dàn ý linh hoạt của AI.

**Architecture:** 2 tầng tri thức. Tầng 1 (attribution facts) gán tác giả **strict** — chỉ khi văn bản nói thẳng (verb/colon sát ngay trước quote), bỏ heuristic khoảng cách; chạy deterministic nên an toàn cả ở runtime (chuyển hẳn sang ingestion sẽ đi cùng nhóm A .md). Tầng 2 giữ retrieval semantic cho việc rộng, LLM vận dụng tự do nhưng mọi câu-trong-ngoặc-kép phải khớp Tầng 1 hoặc text user. Sửa ống chỉ thị: nạp trọn `SYSTEM INSTRUCTIONS.txt` vào system role + `BONUS.txt` làm few-shot.

**Tech Stack:** Python, discord.py, asyncpg/Postgres (pdf_knowledge), unittest.

## Global Constraints

- Tiếng Việt có dấu trong mọi chuỗi hướng tới người dùng.
- Không thêm dependency mới.
- Test bằng `unittest` (khớp `tests/` hiện có), chạy: `python -m unittest tests.<module> -v`.
- Không đổi schema Postgres trong plan này (attribution strict chạy trên chunk hiện có).
- `author = "UNKNOWN"` (hằng `QuoteExtractor.UNKNOWN`) khi không có gán tường minh.

---

### Task 1: `infer_author` strict — bỏ heuristic khoảng cách

**Files:**
- Modify: `cogs/ai.py:357-383` (`QuoteExtractor.infer_author`)
- Test: `tests/test_quote_extractor_attribution.py` (đã tồn tại, thêm case)

**Interfaces:**
- Consumes: `QuoteSpan` (`cogs/ai.py:224`), `cls._candidate_names`, `cls.AUTHOR_VERBS`, `_rag_plain`.
- Produces: `infer_author(chunk_text: str, span: QuoteSpan) -> tuple[str, float]` — trả `(name, confidence)`; `(UNKNOWN, 0.0)` khi không có attribution tường minh **ngay sát** trước quote.

- [ ] **Step 1: Thêm test — tên ở xa nhưng không có verb/colon sát thì UNKNOWN**

Thêm vào `tests/test_quote_extractor_attribution.py`:

```python
    def test_far_name_without_adjacent_verb_is_unknown(self):
        meta = {"chunks": [{"title": "far.pdf", "chunk_index": 2, "content": (
            "Nam Cao là nhà văn hiện thực. Trong một đoạn khác, xuất hiện câu: "
            "“Hạnh phúc là một tấm chăn quá hẹp.”"
        )}]}
        plan = Planner.build("Cho một nhận định")
        quotes = QuoteExtractor.extract(meta, plan, "Cho một nhận định")
        self.assertEqual(quotes[0].author, "UNKNOWN")
```

- [ ] **Step 2: Chạy test — phải fail**

Run: `python -m unittest tests.test_quote_extractor_attribution -v`
Expected: FAIL ở `test_far_name_without_adjacent_verb_is_unknown` (heuristic cũ gán "Nam Cao").

- [ ] **Step 3: Viết lại `infer_author` strict**

Thay toàn bộ thân `infer_author` (`cogs/ai.py:357-383`):

```python
    @classmethod
    def infer_author(cls, chunk_text: str, span: QuoteSpan) -> tuple[str, float]:
        # Chi gan tac gia khi co gan tuong minh NGAY SAT truoc quote:
        # "<Ten> <verb>:" hoac "<Ten>:" trong cua so hep truoc dau mo ngoac.
        window_start = max(0, span.start - 120)
        before = chunk_text[window_start:span.start]
        names = cls._candidate_names(before)
        if not names:
            return cls.UNKNOWN, 0.0
        name, _n_start, n_end = names[-1]  # ten gan quote nhat
        tail = before[n_end:]              # doan giua ten va quote
        tail_plain = _rag_plain(tail)
        # Phai chi con verb attribution +/hoac dau hai cham, khong chen cau khac.
        if len(tail.strip(" \t")) > 40 or "." in tail:
            return cls.UNKNOWN, 0.0
        has_verb = any(verb in tail_plain for verb in cls.AUTHOR_VERBS)
        has_colon = ":" in tail
        if has_verb and has_colon:
            return name, 0.95
        if has_colon:
            return name, 0.8
        if has_verb:
            return name, 0.7
        return cls.UNKNOWN, 0.0
```

- [ ] **Step 4: Chạy test — phải pass (cả 4 case cũ + case mới)**

Run: `python -m unittest tests.test_quote_extractor_attribution -v`
Expected: PASS toàn bộ (2 case Nam Cao/NMC, unknown-no-attribution, far-name).

- [ ] **Step 5: Commit**

```bash
git add cogs/ai.py tests/test_quote_extractor_attribution.py
git commit -m "Make author attribution strict, drop distance heuristic"
```

---

### Task 2: Bỏ fallback biến sentence thành quote

**Files:**
- Modify: `cogs/ai.py:392-394` (nhánh fallback trong `QuoteExtractor.extract`)
- Test: `tests/test_quote_extractor_attribution.py`

**Interfaces:**
- Consumes: `QuoteExtractor.quote_spans`, `pdf_meta["chunks"]`.
- Produces: `extract(pdf_meta, plan, query) -> list[QuoteEvidence]` — không còn dựng quote từ mảnh câu khi thiếu ngoặc kép.

- [ ] **Step 1: Thêm test — chunk không ngoặc kép thì không sinh quote**

```python
    def test_no_quote_marks_yields_no_evidence(self):
        meta = {"chunks": [{"title": "prose.pdf", "chunk_index": 3, "content": (
            "Nam Cao miêu tả Cí Phèo như một bi kịch bị từ chối quyền làm người, "
            "không hề có câu trích dẫn nguyên văn nào ở đây."
        )}]}
        plan = Planner.build("Những nhận định về Cí Phèo")
        quotes = QuoteExtractor.extract(meta, plan, "Những nhận định về Cí Phèo")
        self.assertEqual(quotes, [])
```

- [ ] **Step 2: Chạy test — phải fail**

Run: `python -m unittest tests.test_quote_extractor_attribution -v`
Expected: FAIL (fallback cũ dựng "unit" thành span).

- [ ] **Step 3: Xoá nhánh fallback**

Xoá đoạn `cogs/ai.py:392-394`:

```python
            if not spans and plan.intent in {"QUOTE_COLLECTION", "COMPARE", "ANALYSIS"}:
                units = AI._extract_units_from_chunk(query, chunk, quote_mode=False, max_units=2)
                spans = [QuoteSpan(unit, text.find(unit) if text.find(unit) >= 0 else 0, (text.find(unit) if text.find(unit) >= 0 else 0) + len(unit)) for unit in units]
```

Sau khi xoá, vòng lặp chỉ xử `spans = cls.quote_spans(text)`. Chunk không ngoặc kép → `spans=[]` → không sinh evidence.

- [ ] **Step 4: Chạy test — phải pass**

Run: `python -m unittest tests.test_quote_extractor_attribution -v`
Expected: PASS toàn bộ.

- [ ] **Step 5: Commit**

```bash
git add cogs/ai.py tests/test_quote_extractor_attribution.py
git commit -m "Drop sentence-to-quote fallback to stop fabricated quotes"
```

---

### Task 3: Evidence dạng object có cấu trúc cho LLM (root cause 5)

**Files:**
- Modify: `cogs/ai.py:451-459` (`Formatter.compare_seed`) + nơi dựng block quote cho prompt phân tích.
- Test: `tests/test_rag_orchestration.py` (thêm case) hoặc file test mới `tests/test_evidence_formatting.py`.

**Interfaces:**
- Consumes: `list[QuoteEvidence]`, `RAGPlan`.
- Produces: `Formatter.evidence_block(items: list[QuoteEvidence]) -> str` — mỗi dòng cấu trúc rõ `TÁC GIẢ | "quote" | nguồn`, và **ghi rõ UNKNOWN** khi chưa gán được, để LLM không tự suy luận quan hệ.

- [ ] **Step 1: Thêm test — block phân tách rõ tác giả, đánh dấu UNKNOWN**

Tạo `tests/test_evidence_formatting.py`:

```python
import unittest
from cogs.ai import Formatter, QuoteEvidence


class EvidenceFormattingTest(unittest.TestCase):
    def test_block_marks_author_and_unknown(self):
        items = [
            QuoteEvidence(quote="Nghệ thuật không cần là ánh trăng lừa dối",
                          author="Nam Cao", pdf_title="a.pdf"),
            QuoteEvidence(quote="Văn chương giúp con người đối thoại",
                          author="UNKNOWN", pdf_title="b.pdf"),
        ]
        block = Formatter.evidence_block(items)
        self.assertIn("Nam Cao", block)
        self.assertIn("CHUA XAC DINH TAC GIA", block)
        self.assertIn("a.pdf", block)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Chạy test — phải fail**

Run: `python -m unittest tests.test_evidence_formatting -v`
Expected: FAIL với `AttributeError: ... evidence_block`.

- [ ] **Step 3: Thêm `Formatter.evidence_block` + dùng lại trong `compare_seed`**

Thêm vào class `Formatter` (`cogs/ai.py`, cạnh `compare_seed`):

```python
    @staticmethod
    def evidence_block(items: list[QuoteEvidence]) -> str:
        if not items:
            return ""
        lines = ["TRICH DAN DA XAC MINH (chi dung nguyen van cac cau nay, dung gan sai tac gia):"]
        for item in items[:8]:
            if item.author and item.author != QuoteExtractor.UNKNOWN:
                who = item.author
            else:
                who = "CHUA XAC DINH TAC GIA (khong duoc tu gan ten)"
            src = f" | nguon: {item.pdf_title}" if item.pdf_title else ""
            lines.append(f"- TAC GIA: {who} | TRICH: \"{item.quote}\"{src}")
        return "\n".join(lines)
```

Sửa `compare_seed` để tái dùng (giữ header cũ cho tương thích):

```python
    @staticmethod
    def compare_seed(items: list[QuoteEvidence], plan: RAGPlan) -> str:
        return Formatter.evidence_block(items)
```

- [ ] **Step 4: Chạy test — phải pass**

Run: `python -m unittest tests.test_evidence_formatting -v`
Expected: PASS.

- [ ] **Step 5: Chạy lại toàn bộ suite RAG để không hồi quy**

Run: `python -m unittest tests.test_rag_orchestration tests.test_quote_extractor_attribution -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add cogs/ai.py tests/test_evidence_formatting.py
git commit -m "Pass verified quotes to LLM as structured evidence block"
```

---

### Task 4: Nạp trọn SYSTEM INSTRUCTIONS.txt + BONUS.txt vào system prompt

**Files:**
- Modify: `cogs/ai.py:25` (`SYSTEM_EXTRA_MAX_CHARS`), `cogs/ai.py:45-56` (loaders), `cogs/ai.py:115-131` (`THEN_SYSTEM_PROMPT`), `cogs/ai.py:1170-1178` (`_guarded_prompt` — gỡ chỉ thị khỏi user prompt).
- Test: `tests/test_document_grounding.py` (thêm case) hoặc mới `tests/test_system_instructions.py`.

**Interfaces:**
- Consumes: file `SYSTEM INSTRUCTIONS.txt`, `BONUS.txt` ở gốc repo.
- Produces: `LITERATURE_SYSTEM_INSTRUCTIONS` (trọn, không cắt), `BONUS_FEWSHOT` (nội dung BONUS.txt), và `THEN_SYSTEM_PROMPT` là chuỗi có chèn cả hai vào **system role**.

- [ ] **Step 1: Thêm test — instructions không bị cắt + BONUS được nạp vào system prompt**

Tạo `tests/test_system_instructions.py`:

```python
import unittest
from pathlib import Path
from cogs import ai


class SystemInstructionsTest(unittest.TestCase):
    def test_full_instructions_loaded_uncut(self):
        raw = Path("SYSTEM INSTRUCTIONS.txt").read_text(encoding="utf-8").strip()
        # Nap tron ven, khong con cat 1500 ky tu.
        self.assertGreaterEqual(len(ai.LITERATURE_SYSTEM_INSTRUCTIONS), len(raw) - 5)

    def test_bonus_loaded_into_system_prompt(self):
        self.assertTrue(ai.BONUS_FEWSHOT)
        # Dau hieu dac trung tu BONUS.txt (loi chu Trung chen ngang lam vi du xau).
        self.assertIn("Van hoc la nhan hoc", ai._plain_ascii(ai.BONUS_FEWSHOT)) \
            if hasattr(ai, "_plain_ascii") else self.assertIn("nhan hoc", ai.BONUS_FEWSHOT.lower())

    def test_system_prompt_contains_instructions(self):
        self.assertIn(ai.LITERATURE_SYSTEM_INSTRUCTIONS[:50], ai.THEN_SYSTEM_PROMPT)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Chạy test — phải fail**

Run: `python -m unittest tests.test_system_instructions -v`
Expected: FAIL (`SYSTEM_EXTRA_MAX_CHARS=1500` cắt file; `BONUS_FEWSHOT` chưa tồn tại; THEN_SYSTEM_PROMPT chưa chèn).

- [ ] **Step 3: Bỏ cắt + nạp BONUS + chèn vào system prompt**

Sửa `cogs/ai.py:25`:

```python
SYSTEM_EXTRA_MAX_CHARS = 20000
```

Thêm loader BONUS ngay sau `LITERATURE_SYSTEM_INSTRUCTIONS = _load_literature_system_instructions()` (`cogs/ai.py:56`):

```python
def _load_bonus_fewshot() -> str:
    path = Path(__file__).resolve().parents[1] / "BONUS.txt"
    try:
        text = path.read_text(encoding="utf-8").strip()
    except Exception:
        return ""
    if len(text) > SYSTEM_EXTRA_MAX_CHARS:
        text = text[:SYSTEM_EXTRA_MAX_CHARS] + "\n...(rut gon BONUS vi qua dai)"
    return text


BONUS_FEWSHOT = _load_bonus_fewshot()
```

Chuyển `THEN_SYSTEM_PROMPT` (`cogs/ai.py:115-131`) từ hằng chuỗi sang chuỗi ghép có chèn instructions + BONUS. Thêm ngay sau khối literal:

```python
THEN_SYSTEM_PROMPT = THEN_SYSTEM_PROMPT + (
    ("\n\n=== CHI THI VAN PHONG & CHONG AO GIAC (BAT BUOC TUAN THU) ===\n"
     + LITERATURE_SYSTEM_INSTRUCTIONS) if LITERATURE_SYSTEM_INSTRUCTIONS else ""
) + (
    ("\n\n=== VI DU XAU -> TOT (tranh dung cac loi nay: chen chu Trung, bia chi tiet, hoi hot) ===\n"
     + BONUS_FEWSHOT) if BONUS_FEWSHOT else ""
)
```

- [ ] **Step 4: Gỡ chỉ thị khỏi user prompt (tránh nhét 2 lần)**

Trong `_guarded_prompt` (`cogs/ai.py:1170-1178`), xoá khối `literature_rules` và tham chiếu `{literature_rules}` trong chuỗi trả về (instructions giờ nằm ở system role):

```python
    @staticmethod
    def _guarded_prompt(prompt: str, knowledge: str, web_context: str, mode: str) -> str:
        source_block = knowledge or "KHONG CO KHO PDF/TRI THUC HVHN PHU HOP DUOC NAP."
        web_block = web_context or "KHONG CO NGUON WEB DUOC TRUY XUAT."
        return (
            "Ban la Then, tro giang AI mon Ngu van cua HVHN. Luon tra loi bang tieng Viet co dau, tru khi nguoi dung yeu cau ngon ngu khac.\n"
            f"CHE DO: {mode}\n"
            "KHO PDF/TRI THUC/FEEDBACK HVHN DA TRUY XUAT:\n"
            f"{source_block}\n\n"
            "NGUON WEB DA TRA CUU (neu co):\n"
```

(Giữ nguyên phần còn lại của return sau dòng này.)

- [ ] **Step 5: Chạy test — phải pass**

Run: `python -m unittest tests.test_system_instructions -v`
Expected: PASS cả 3 case.

- [ ] **Step 6: Regression toàn suite**

Run: `python -m unittest discover -s tests -v`
Expected: PASS (không hồi quy grounding/orchestration).

- [ ] **Step 7: Commit**

```bash
git add cogs/ai.py tests/test_system_instructions.py
git commit -m "Load full literature instructions and BONUS few-shot into system prompt"
```

---

## Self-Review

**Spec coverage:**
- Root cause 2 (heuristic khoảng cách) → Task 1. ✔
- Root cause 4 (sentence fallback) → Task 2. ✔
- Root cause 5 (context string→object) → Task 3. ✔
- Phần C ống chỉ thị (cắt 1500, sai role, BONUS không nạp) → Task 4. ✔
- Tầng 2 linh hoạt: giữ nguyên retrieval semantic (không đụng), chỉ siết quote — không thu hẹp việc rộng. ✔
- Root cause 1 & 3 (runtime vs ingestion, chunk là đơn vị duy nhất): correctness đã đạt nhờ attribution strict + bỏ fallback (chạy runtime nay an toàn, deterministic). Chuyển hẳn extraction sang ingestion + tách quote khỏi chunk là **việc của nhóm A (.md)** — ghi rõ ở spec §5, không làm trong plan này để tránh trùng.

**Placeholder scan:** không có TBD/TODO; mọi step có code/command cụ thể.

**Type consistency:** `infer_author -> tuple[str,float]`, `extract -> list[QuoteEvidence]`, `evidence_block(items)->str`, `LITERATURE_SYSTEM_INSTRUCTIONS`/`BONUS_FEWSHOT`/`THEN_SYSTEM_PROMPT` là module-level str — nhất quán giữa các task.
