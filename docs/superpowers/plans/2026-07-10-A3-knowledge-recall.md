# A3 — Fix recall kho tri thức (mở rộng khái niệm) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development. Steps use checkbox (`- [ ]`). Làm trong worktree D:\Bothvhn-A (branch feat/kho-md).

**Goal:** AI dùng được tri thức trong `ai_knowledge` kể cả khi câu hỏi diễn đạt khác từ ngữ trong title/nội dung (vd query "viết đoạn giới thiệu" phải khớp tri thức "cách mở bài").

**Root cause (từ ví dụ chủ):** `_knowledge_context` chỉ khớp theo token literal (FTS 'simple' + LIKE `%term%`). Query dùng từ đồng nghĩa/diễn đạt khác → không token nào trùng → 0 kết quả → AI không có gì để dùng.

**Architecture:** Thêm hàm thuần `expand_query_terms(query)` nở mỗi từ khoá thuộc một **cụm khái niệm Ngữ Văn** ra cả cụm; dùng danh sách nở này cho cả tsquery lẫn LIKE trong `_knowledge_context`, rank theo số cụm/term khớp, hạ ngưỡng để trả cả khớp một phần.

**Tech Stack:** Python, unittest.

## Global Constraints

- Làm trong D:\Bothvhn-A. Test: `python -m unittest tests.test_query_expansion -v`.
- `expand_query_terms` THUẦN, test đầy đủ. Không thêm dependency.
- Không đổi schema; chỉ đổi cách dựng terms/patterns trong `_knowledge_context`.

---

### Task 1: `expand_query_terms` + cụm khái niệm

**Files:**
- Modify: `cogs/ai.py` (thêm hằng cụm + hàm thuần, đặt gần các helper `_rag_*` đầu file)
- Test: `tests/test_query_expansion.py` (mới)

**Interfaces:**
- Produces: `CONCEPT_CLUSTERS: list[list[str]]` (mỗi cụm là list từ khoá đồng nghĩa, dạng thường không dấu qua `_rag_plain`); `expand_query_terms(query: str) -> list[str]` trả danh sách term (đã _rag_plain, không trùng): gồm token gốc + mọi từ trong cụm mà token gốc chạm tới.

- [ ] **Step 1: Viết test**

Tạo `tests/test_query_expansion.py`:

```python
import unittest
from cogs.ai import expand_query_terms


class QueryExpansionTest(unittest.TestCase):
    def test_gioi_thieu_expands_to_mo_bai(self):
        terms = expand_query_terms("làm sao viết đoạn giới thiệu cho hay")
        self.assertIn("mo bai", terms)   # cùng cụm với "gioi thieu"

    def test_mo_bai_expands_to_gioi_thieu(self):
        terms = expand_query_terms("cách mở bài ấn tượng")
        self.assertIn("gioi thieu", terms)

    def test_dan_y_expands_to_bo_cuc(self):
        terms = expand_query_terms("cho mình cái dàn ý")
        self.assertIn("bo cuc", terms)
        self.assertIn("luan diem", terms)

    def test_unrelated_query_keeps_own_terms(self):
        terms = expand_query_terms("phân tích nhân vật Chí Phèo")
        self.assertIn("chi pheo", " ".join(terms) if isinstance(terms, list) else terms)
        # khong keo theo cum mo bai
        self.assertNotIn("mo bai", terms)

    def test_no_duplicates(self):
        terms = expand_query_terms("mở bài mở bài")
        self.assertEqual(len(terms), len(set(terms)))


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Chạy test — phải fail**

Run: `python -m unittest tests.test_query_expansion -v`
Expected: FAIL (`ImportError: expand_query_terms`).

- [ ] **Step 3: Thêm cụm + hàm**

Trong `cogs/ai.py`, gần các helper đầu file (sau `_rag_plain`), thêm:

```python
CONCEPT_CLUSTERS = [
    ["mo bai", "gioi thieu", "dan dat", "vao bai", "dat van de", "mo doan", "cau mo dau"],
    ["ket bai", "ket luan", "khep lai", "tong ket", "chot van de", "ket doan"],
    ["than bai", "trien khai", "phat trien y", "phan tich", "trien khai luan diem"],
    ["dan y", "bo cuc", "suon bai", "khung bai", "luan diem", "he thong luan diem", "y chinh"],
    ["dan chung", "bang chung", "vi du", "lieu chung", "minh chung"],
    ["ly le", "lap luan", "ly luan", "bien luan"],
    ["nghi luan xa hoi", "nlxh", "tu tuong dao li", "hien tuong doi song"],
    ["nghi luan van hoc", "nlvh", "phan tich tac pham", "cam nhan"],
    ["bien phap tu tu", "nghe thuat", "an du", "so sanh", "nhan hoa", "diep ngu"],
    ["nhan vat", "hinh tuong", "nhan vat van hoc"],
    ["van phong", "giong van", "loi van", "hanh van"],
    ["nhan dinh", "y kien", "trich dan", "cau noi"],
]


def expand_query_terms(query: str) -> list[str]:
    base = _rag_plain(query)
    tokens = [t for t in re.findall(r"[a-z0-9]{2,}", base) if t]
    out: list[str] = []

    def _add(t: str):
        if t and t not in out:
            out.append(t)

    for t in tokens:
        _add(t)
    # no cum: neu chuoi query cham toi bat ky phrase nao trong cum -> them ca cum
    for cluster in CONCEPT_CLUSTERS:
        if any(phrase in base for phrase in cluster):
            for phrase in cluster:
                _add(phrase)
    return out
```

- [ ] **Step 4: Chạy test — phải pass**

Run: `python -m unittest tests.test_query_expansion -v`
Expected: PASS 5/5.

- [ ] **Step 5: Commit**

```bash
git add cogs/ai.py tests/test_query_expansion.py
git commit -m "Add Vietnamese literary concept expansion for query terms"
```

---

### Task 2: Dùng term nở trong `_knowledge_context`

**Files:**
- Modify: `cogs/ai.py` (`_knowledge_context` ~1122-1171)
- Test: `tests/test_knowledge_recall.py` (mới, kiểm tĩnh)

**Interfaces:**
- `_knowledge_context` dựng `terms` = `expand_query_terms(query)` (thay regex cũ), `patterns = [f"%{t}%" for t in terms]`, `ts_query = " ".join(terms)` — phần SQL giữ nguyên (đã LIKE ANY + tsquery), nhờ term nở nên khớp cả diễn đạt khác.

- [ ] **Step 1: Viết test tĩnh**

Tạo `tests/test_knowledge_recall.py`:

```python
import inspect
import unittest
import cogs.ai as ai


class KnowledgeRecallTest(unittest.TestCase):
    def test_knowledge_context_uses_expansion(self):
        src = inspect.getsource(ai.AI._knowledge_context)
        self.assertIn("expand_query_terms", src)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Chạy test — phải fail**

Run: `python -m unittest tests.test_knowledge_recall -v`
Expected: FAIL.

- [ ] **Step 3: Sửa `_knowledge_context`**

Trong `_knowledge_context` (`cogs/ai.py:1122-1123`), thay dòng dựng `terms`:

```python
    async def _knowledge_context(self, query: str, limit: int = 6) -> str:
        terms = expand_query_terms(query)[:24]
```

Giữ nguyên phần còn lại (patterns/tsquery/SQL dùng `terms`). Vì `" ".join(terms)` giờ chứa cả cụm nở, `websearch_to_tsquery` sẽ OR-khớp rộng hơn, và `LIKE ANY(patterns)` bắt cả từ đồng nghĩa.

- [ ] **Step 4: Chạy test — phải pass**

Run: `python -m unittest tests.test_knowledge_recall -v`
Expected: PASS.

- [ ] **Step 5: Regression + import**

Run: `python -m unittest tests.test_query_expansion tests.test_knowledge_recall tests.test_md_knowledge tests.test_quote_fact -v`
Expected: PASS.
Run: `python -c "import cogs.ai"`
Expected: không lỗi.

- [ ] **Step 6: Commit**

```bash
git add cogs/ai.py tests/test_knowledge_recall.py
git commit -m "Use concept-expanded terms for manual knowledge recall"
```

---

## Self-Review

**Spec coverage (A3):** nở khái niệm để query diễn đạt khác vẫn khớp title/nội dung → T1; wire vào retrieval → T2. Bug "chỉ khớp khi trùng title" được giải bằng OR-khớp trên cụm đồng nghĩa. ✔
**Placeholder scan:** không TBD; mọi step có code/command.
**Type consistency:** `expand_query_terms(str)->list[str]` (đã _rag_plain); `CONCEPT_CLUSTERS: list[list[str]]`. `_knowledge_context` dùng list terms như cũ (patterns/join) → tương thích SQL sẵn có.
**Lưu ý:** cụm khái niệm là heuristic thủ công, mở rộng dần khi gặp ca mới. Không đụng grounding B (quote nguyên văn vẫn phải khớp nguồn). Nếu chủ muốn AI *kết hợp* nhiều tri thức + không chép nguyên văn: đó là hành vi LLM — đã có chỉ thị trong THEN_SYSTEM_PROMPT (nhóm B/C); A3 chỉ lo phần fetch đủ tri thức lên context.
