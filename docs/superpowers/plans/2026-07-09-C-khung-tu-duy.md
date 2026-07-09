# Khung Tư Duy Lập Luận (Nhóm C) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Chèn khung tư duy/dàn ý mềm theo thể loại (NLXH/NLVH) × bậc (thường/HSG) × chế độ (dàn ý/viết bài) vào prompt, để AI lập luận sâu, có hệ thống luận điểm, không hời hợt.

**Architecture:** Thêm 3 trường phân loại vào `RAGPlan`, `Planner` điền chúng bằng heuristic từ khóa. `Scaffold.for_plan(plan)` dựng soft instruction block (rỗng khi genre=NONE). Block được truyền qua tham số tùy chọn `guidance` xuyên `_safe_generate` → `_guarded_prompt`, chèn cạnh khối `CHE DO`. Chỉ hướng dẫn cách lập luận/bố cục — không cấp kiến thức, không đụng grounding của nhóm B.

**Tech Stack:** Python, discord.py, unittest.

## Global Constraints

- Đầu ra của AI luôn tiếng Việt; text hướng dẫn trong prompt ngầm viết tiếng Việt có dấu cho rõ nghĩa.
- Không thêm dependency mới. Test bằng `unittest`; chạy: `python -m unittest tests.<module> -v` từ d:\Bothvhn.
- Không đổi retrieval/grounding, không đổi kho tài liệu.
- Mọi call site `_guarded_prompt` cũ phải chạy nguyên (tham số `guidance` mặc định rỗng).
- Block guidance ngắn gọn (mỗi khung vài trăm ký tự) để không phình prompt.
- `_rag_plain(text)` chuẩn hóa ASCII không dấu, dùng để so khớp từ khóa.

---

### Task 1: Phân loại genre / level / write_essay trong RAGPlan + Planner

**Files:**
- Modify: `cogs/ai.py:196-208` (dataclass `RAGPlan` — thêm 3 trường), `cogs/ai.py:303-340` (`Planner` — thêm classifier + điền trong `build`)
- Test: `tests/test_composition_classifier.py` (tạo mới)

**Interfaces:**
- Produces: `RAGPlan.genre: str` ∈ {"NLXH","NLVH","NONE"}, `RAGPlan.level: str` ∈ {"THUONG","HSG"}, `RAGPlan.write_essay: bool`; `Planner.classify_composition(message: str, intent: str, author: str) -> tuple[str, str, bool]` trả `(genre, level, write_essay)`.
- Consumes: `_rag_plain`, `IntentClassifier.classify`.

- [ ] **Step 1: Viết test**

Tạo `tests/test_composition_classifier.py`:

```python
import unittest
from cogs.ai import Planner


class CompositionClassifierTest(unittest.TestCase):
    def test_nlxh_detected(self):
        p = Planner.build("Suy nghĩ về hiện tượng vô cảm trong đời sống hiện nay")
        self.assertEqual(p.genre, "NLXH")
        self.assertEqual(p.level, "THUONG")
        self.assertFalse(p.write_essay)

    def test_nlvh_detected(self):
        p = Planner.build("Phân tích nhân vật Chí Phèo trong tác phẩm cùng tên")
        self.assertEqual(p.genre, "NLVH")

    def test_hsg_signal(self):
        p = Planner.build("Đề thi HSG: Bàn về ý kiến cho rằng thơ là tiếng nói của tâm hồn")
        self.assertEqual(p.level, "HSG")

    def test_nlvh_nhan_dinh_is_hsg(self):
        p = Planner.build("Chứng minh nhận định: nghệ thuật là địa hạt của cái độc đáo qua một tác phẩm")
        self.assertEqual(p.genre, "NLVH")
        self.assertEqual(p.level, "HSG")

    def test_write_essay_flag(self):
        p = Planner.build("Viết bài văn phân tích bài thơ Sóng của Xuân Quỳnh")
        self.assertTrue(p.write_essay)

    def test_plain_question_is_none(self):
        p = Planner.build("Xuân Diệu sinh năm bao nhiêu")
        self.assertEqual(p.genre, "NONE")
```

- [ ] **Step 2: Chạy test — phải fail**

Run: `python -m unittest tests.test_composition_classifier -v`
Expected: FAIL (`AttributeError: 'RAGPlan' object has no attribute 'genre'`).

- [ ] **Step 3: Thêm 3 trường vào RAGPlan**

Trong dataclass `RAGPlan` (`cogs/ai.py:196-208`), thêm sau dòng `reason: str = ""`:

```python
    genre: str = "NONE"
    level: str = "THUONG"
    write_essay: bool = False
```

- [ ] **Step 4: Thêm classifier vào Planner + điền trong build**

Thêm method vào class `Planner` (ngay trước `build`, sau `author_filter`):

```python
    NLVH_MARKERS = (
        "nghi luan van hoc", "nlvh", "tac pham", "nhan vat", "doan tho", "bai tho",
        "doan trich", "kho tho", "hinh tuong", "chi tiet nghe thuat", "gia tri nhan dao",
        "binh giang", "cam nhan ve", "phan tich bai", "phan tich doan", "phan tich nhan vat",
    )
    NLXH_MARKERS = (
        "nghi luan xa hoi", "nlxh", "tu tuong dao li", "hien tuong doi song", "hien tuong",
        "quan niem song", "loi song", "y kien cho rang", "cham ngon", "ve cuoc song",
        "gia tri song", "vo cam", "suy nghi ve", "ban ve", "y nghia cua",
    )
    HSG_MARKERS = (
        "hsg", "hoc sinh gioi", "doi tuyen", "chuyen", "cap tinh", "khu vuc",
        "quoc gia", "olympic", "chuyen de",
    )
    ESSAY_MARKERS = (
        "viet bai", "viet thanh bai", "viet doan", "viet mo bai", "viet ket bai",
        "viet hoan chinh", "viet mot bai", "viet giup minh bai", "viet giup toi bai",
    )
    NHAN_DINH_MARKERS = ("nhan dinh", "y kien", "quan niem", "cho rang")
    CHUNG_MINH_MARKERS = ("chung minh", "lam sang to", "ban ve", "binh luan y kien", "lam ro")

    @classmethod
    def classify_composition(cls, message: str, intent: str, author: str) -> tuple[str, str, bool]:
        q = _rag_plain(message)
        if any(m in q for m in cls.NLVH_MARKERS):
            genre = "NLVH"
        elif any(m in q for m in cls.NLXH_MARKERS):
            genre = "NLXH"
        elif intent in {"OUTLINE", "ANALYSIS", "COMPARE"} and author:
            genre = "NLVH"
        else:
            genre = "NONE"
        level = "THUONG"
        if genre != "NONE":
            if any(m in q for m in cls.HSG_MARKERS):
                level = "HSG"
            elif genre == "NLVH" and any(m in q for m in cls.NHAN_DINH_MARKERS) and any(m in q for m in cls.CHUNG_MINH_MARKERS):
                level = "HSG"
        write_essay = any(m in q for m in cls.ESSAY_MARKERS)
        return genre, level, write_essay
```

Trong `build` (`cogs/ai.py:320-340`), sau dòng `author = cls.author_filter(message)` thêm:

```python
        genre, level, write_essay = cls.classify_composition(message, intent, author)
```

và trong `return RAGPlan(...)` thêm 3 tham số:

```python
            genre=genre,
            level=level,
            write_essay=write_essay,
```

- [ ] **Step 5: Chạy test — phải pass**

Run: `python -m unittest tests.test_composition_classifier -v`
Expected: PASS 6/6.

- [ ] **Step 6: Regression**

Run: `python -m unittest tests.test_rag_orchestration tests.test_quote_extractor_attribution -v`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add cogs/ai.py tests/test_composition_classifier.py
git commit -m "Classify composition genre, level, and essay-mode in RAGPlan"
```

---

### Task 2: Scaffold.for_plan — soft instruction block theo khung

**Files:**
- Modify: `cogs/ai.py` — thêm class `Scaffold` (đặt ngay sau `Formatter`, trước `class AI`)
- Test: `tests/test_scaffold.py` (tạo mới)

**Interfaces:**
- Consumes: `RAGPlan` (với `genre`, `level`, `write_essay`).
- Produces: `Scaffold.for_plan(plan: RAGPlan) -> str` — rỗng khi `genre == "NONE"`; ngược lại trả block hướng dẫn.

- [ ] **Step 1: Viết test**

Tạo `tests/test_scaffold.py`:

```python
import unittest
from cogs.ai import Scaffold, RAGPlan


def _plan(genre, level="THUONG", write_essay=False):
    return RAGPlan(intent="ANALYSIS", genre=genre, level=level, write_essay=write_essay)


class ScaffoldTest(unittest.TestCase):
    def test_none_is_empty(self):
        self.assertEqual(Scaffold.for_plan(_plan("NONE")), "")

    def test_nlxh_has_phan_bien_and_bai_hoc(self):
        block = Scaffold.for_plan(_plan("NLXH"))
        self.assertIn("Phản biện", block)
        self.assertIn("Bài học", block)

    def test_nlvh_has_he_thong_luan_diem(self):
        block = Scaffold.for_plan(_plan("NLVH"))
        self.assertIn("Hệ thống luận điểm", block)

    def test_hsg_nlvh_mentions_ly_luan(self):
        block = Scaffold.for_plan(_plan("NLVH", level="HSG"))
        self.assertIn("lý luận văn học", block)
        self.assertIn("so sánh", block.lower())

    def test_hsg_nlxh_mentions_da_tang(self):
        block = Scaffold.for_plan(_plan("NLXH", level="HSG"))
        self.assertIn("đa tầng", block)

    def test_default_is_outline(self):
        block = Scaffold.for_plan(_plan("NLVH"))
        self.assertIn("dàn ý chi tiết", block)

    def test_write_essay_switches_to_essay(self):
        block = Scaffold.for_plan(_plan("NLVH", write_essay=True))
        self.assertIn("bài văn hoàn chỉnh", block)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Chạy test — phải fail**

Run: `python -m unittest tests.test_scaffold -v`
Expected: FAIL (`ImportError: cannot import name 'Scaffold'`).

- [ ] **Step 3: Thêm class Scaffold**

Thêm vào `cogs/ai.py` ngay trước `class AI(commands.Cog):`:

```python
class Scaffold:
    _NLXH_THUONG = (
        "Mở bài: dẫn dắt tự nhiên rồi nêu thẳng vấn đề nghị luận.\n"
        "Thân bài: (1) Giải thích từ khóa/khái niệm cốt lõi; (2) Bàn luận — khẳng định "
        "đúng/sai, mỗi ý kèm lí lẽ sắc và dẫn chứng thực tế cụ thể; (3) Phản biện & mở rộng "
        "— lật ngược vấn đề, phê phán biểu hiện trái; (4) Bài học nhận thức và hành động.\n"
        "Kết bài: khẳng định lại và liên hệ bản thân."
    )
    _NLXH_HSG = (
        "Đây là đề nghị luận xã hội mức HSG: thường trừu tượng, đa nghĩa.\n"
        "Mở bài: dẫn dắt có chiều sâu, nêu vấn đề.\n"
        "Thân bài: (1) Giải mã nhiều lớp nghĩa của từ khóa; (2) Bàn luận với chiều sâu "
        "nhân sinh và triết lí, lí lẽ chặt; (3) Phản biện đa tầng — giới hạn vấn đề, điều "
        "kiện đúng/sai, mặt trái; (4) Dẫn chứng đa dạng: đời sống + văn học + nhân vật lịch "
        "sử; (5) Bài học nhận thức và hành động.\n"
        "Kết bài: nâng vấn đề, để lại dư âm. Hành văn giàu hình ảnh, có dấu ấn tư duy riêng."
    )
    _NLVH_THUONG = (
        "Mở bài: giới thiệu tác giả — tác phẩm — vấn đề nghị luận (nêu nhận định nếu đề có).\n"
        "Thân bài: (1) Khái quát hoàn cảnh sáng tác/vị trí đoạn; (2) Hệ thống luận điểm — "
        "mỗi luận điểm phân tích cả nội dung và nghệ thuật, có dẫn chứng và lời bình; "
        "(3) Đánh giá giá trị nội dung, nghệ thuật, phong cách.\n"
        "Kết bài: khẳng định và nêu cảm nghĩ. Liên hệ/mở rộng khi hợp lí."
    )
    _NLVH_HSG = (
        "Đây là đề nghị luận văn học mức HSG, thường là một nhận định lý luận văn học cần "
        "chứng minh.\n"
        "Mở bài: giới thiệu và trích nhận định làm trục.\n"
        "Thân bài: (1) Giải thích nhận định (vận dụng thuật ngữ lý luận văn học: thi pháp, "
        "điểm nhìn, tình huống, giá trị nhân đạo...); (2) Chứng minh qua tác phẩm bằng hệ "
        "thống luận điểm sâu (nội dung + nghệ thuật + dẫn chứng + bình); (3) So sánh, liên "
        "hệ rộng với tác phẩm cùng đề tài/thời kỳ; (4) Phản biện đa chiều, bàn giới hạn của "
        "nhận định; (5) Đánh giá đóng góp và phong cách tác giả.\n"
        "Kết bài: khẳng định, nâng tầm. Hành văn giàu chất văn, có sáng tạo."
    )

    @classmethod
    def _skeleton(cls, plan: RAGPlan) -> str:
        if plan.genre == "NLXH":
            return cls._NLXH_HSG if plan.level == "HSG" else cls._NLXH_THUONG
        return cls._NLVH_HSG if plan.level == "HSG" else cls._NLVH_THUONG

    @classmethod
    def for_plan(cls, plan: RAGPlan) -> str:
        if plan.genre == "NONE":
            return ""
        skeleton = cls._skeleton(plan)
        if plan.write_essay:
            mode_line = (
                "Nhiệm vụ: viết thành bài văn hoàn chỉnh, mạch lạc, các phần nối liền thành "
                "văn xuôi (không gạch đầu dòng), giữ nguyên chiều sâu lập luận theo khung dưới."
            )
        else:
            mode_line = (
                "Nhiệm vụ: lập dàn ý chi tiết theo khung dưới; đào sâu từng ý — lí lẽ, dẫn "
                "chứng, phản biện, liên hệ mở rộng — không liệt kê hời hợt."
            )
        return f"KHUNG TƯ DUY LẬP LUẬN:\n{mode_line}\n{skeleton}"
```

- [ ] **Step 4: Chạy test — phải pass**

Run: `python -m unittest tests.test_scaffold -v`
Expected: PASS 7/7.

- [ ] **Step 5: Commit**

```bash
git add cogs/ai.py tests/test_scaffold.py
git commit -m "Add Scaffold builder for genre/level-aware reasoning frameworks"
```

---

### Task 3: Truyền guidance vào prompt

**Files:**
- Modify: `cogs/ai.py:1229` (`_guarded_prompt` — thêm param `guidance`), `cogs/ai.py:1369-1379` (`_safe_generate` — thêm param `guidance` + truyền xuống), `cogs/ai.py:1635` (luồng chính — tính và truyền guidance)
- Test: `tests/test_guidance_injection.py` (tạo mới)

**Interfaces:**
- Consumes: `Scaffold.for_plan`, `RAGPlan`.
- Produces: `_guarded_prompt(prompt, knowledge, web_context, mode, guidance="") -> str` chèn `guidance` cạnh `CHE DO` khi không rỗng; `_safe_generate(..., guidance="")` chuyển tiếp guidance.

- [ ] **Step 1: Viết test**

Tạo `tests/test_guidance_injection.py`:

```python
import unittest
from cogs.ai import AI


class GuidanceInjectionTest(unittest.TestCase):
    def test_guidance_included_when_present(self):
        out = AI._guarded_prompt("Câu hỏi", "ctx", "", "analysis", guidance="KHUNG TƯ DUY LẬP LUẬN: test-marker")
        self.assertIn("KHUNG TƯ DUY LẬP LUẬN: test-marker", out)

    def test_no_guidance_key_when_empty(self):
        out = AI._guarded_prompt("Câu hỏi", "ctx", "", "analysis")
        self.assertNotIn("KHUNG TƯ DUY", out)

    def test_backward_compatible_signature(self):
        # Goi cu khong co guidance van chay.
        out = AI._guarded_prompt("Câu hỏi", "ctx", "", "chat")
        self.assertIn("YEU CAU NGUOI DUNG", out)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Chạy test — phải fail**

Run: `python -m unittest tests.test_guidance_injection -v`
Expected: FAIL (`test_guidance_included_when_present` — `_guarded_prompt` chưa nhận `guidance`).

- [ ] **Step 3: Thêm param guidance vào `_guarded_prompt`**

Sửa chữ ký `cogs/ai.py:1229`:

```python
    def _guarded_prompt(prompt: str, knowledge: str, web_context: str, mode: str, guidance: str = "") -> str:
```

Sửa phần return: sau dòng `f"CHE DO: {mode}\n"` chèn:

```python
            + (f"{guidance}\n" if guidance else "")
```

Cụ thể khối đầu return thành:

```python
        return (
            "Ban la Then, tro giang AI mon Ngu van cua HVHN. Luon tra loi bang tieng Viet co dau, tru khi nguoi dung yeu cau ngon ngu khac.\n"
            f"CHE DO: {mode}\n"
            + (f"{guidance}\n" if guidance else "")
            + "KHO PDF/TRI THUC/FEEDBACK HVHN DA TRUY XUAT:\n"
```

(Chuyển các dòng chuỗi liên tiếp còn lại từ nối ngầm sang nối `+` cho đồng nhất — hoặc giữ nguyên vì Python nối literal liền kề; chỉ cần đảm bảo biểu thức `(f"{guidance}\n" if guidance else "")` được `+` với phần trước và sau. Cách an toàn: bọc guidance giữa hai chuỗi bằng toán tử `+` như trên và giữ literal-adjacency cho phần còn lại sau `"KHO PDF/..."`.)

- [ ] **Step 4: Thêm param guidance vào `_safe_generate` và chuyển tiếp**

Sửa chữ ký `_safe_generate` (`cogs/ai.py:1369`), thêm `guidance: str = ""` vào cuối danh sách tham số. Tại dòng `1379`:

```python
        full_prompt = self._guarded_prompt(prompt, knowledge, web_context, mode, guidance)
```

(Dòng repair `1391` giữ nguyên không guidance — repair không cần khung.)

- [ ] **Step 5: Tính và truyền guidance ở luồng chính**

Tại `cogs/ai.py:1635`, đổi lời gọi `_safe_generate` để truyền guidance tính từ plan. Ngay trước dòng `answer, full_prompt = await self._safe_generate(...)` thêm:

```python
        guidance = Scaffold.for_plan(plan)
```

và sửa lời gọi:

```python
        answer, full_prompt = await self._safe_generate(prompt, knowledge, web_context, mode, retrieval_hit=retrieval_hit, guidance=guidance)
```

- [ ] **Step 6: Chạy test — phải pass**

Run: `python -m unittest tests.test_guidance_injection -v`
Expected: PASS 3/3.

- [ ] **Step 7: Regression toàn suite**

Run: `python -m unittest discover -s tests -v`
Expected: PASS (không hồi quy).

- [ ] **Step 8: Commit**

```bash
git add cogs/ai.py tests/test_guidance_injection.py
git commit -m "Inject reasoning scaffold into main answer prompt"
```

---

## Self-Review

**Spec coverage:**
- 3 chiều genre/level/write_essay → Task 1. ✔
- Soft block theo (genre×level×essay) + intent → Task 2 (`Scaffold`). ✔
- Chèn qua `guidance` giữ tương thích call site cũ → Task 3. ✔
- genre=NONE không chèn → Task 2 `test_none_is_empty` + Task 3 `test_no_guidance_key_when_empty`. ✔
- Không đụng grounding/retrieval: chỉ thêm trường + block + 1 tham số; không sửa logic truy xuất. ✔

**Placeholder scan:** không TBD/TODO; mọi step có code/command.

**Type consistency:** `classify_composition -> tuple[str,str,bool]`; `Scaffold.for_plan(plan)->str`; `_guarded_prompt(...,guidance="")->str`; `_safe_generate(...,guidance="")`. Tên trường `genre/level/write_essay` nhất quán giữa Task 1→2→3.

**Lưu ý reviewer:** Task 3 Step 3 sửa cách nối chuỗi trong `_guarded_prompt` — cần kiểm output vẫn đúng thứ tự và không mất dòng nào (test `test_backward_compatible_signature` giữ mốc `YEU CAU NGUOI DUNG`).
