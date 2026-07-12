import os
import re
import asyncio
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from html import unescape
from urllib.parse import parse_qs, unquote, urlparse

import aiohttp
import discord
from discord import app_commands
from discord.ext import commands
from md_knowledge import retrieve_md_knowledge, backfill_embeddings, count_missing_embeddings
import md_embeddings

GROQ_MODEL = os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.0-flash")
# Rate limit cua Groq tinh THEO MODEL (moi model 1 quota TPD rieng tren cung key),
# nen khi model chinh chay het quota thi thu model khac cung key truoc khi bo cuoc.
GROQ_FALLBACK_MODELS = [
    m.strip() for m in os.getenv(
        "GROQ_FALLBACK_MODELS", "moonshotai/kimi-k2-instruct-0905,llama-3.1-8b-instant"
    ).split(",") if m.strip()
]
GROQ_MODELS = [GROQ_MODEL] + [m for m in GROQ_FALLBACK_MODELS if m != GROQ_MODEL]
# Free tier gemini-2.0-flash da bi Google dua ve 0; 2.5-flash/lite van con free tier.
GEMINI_FALLBACK_MODELS = [
    m.strip() for m in os.getenv(
        # Alias "-latest" luon tro ve model flash hien hanh — tranh 404 "no longer
        # available to new users" nhu gemini-2.5-flash (da gap 2026-07-11).
        "GEMINI_FALLBACK_MODELS", "gemini-flash-latest,gemini-flash-lite-latest"
    ).split(",") if m.strip()
]
GEMINI_SKIP_MODELS = {
    m.strip().lower() for m in os.getenv("HVHN_GEMINI_SKIP_MODELS", "gemini-2.0-flash").split(",") if m.strip()
}
GEMINI_MODELS = []
for _model in [GEMINI_MODEL] + GEMINI_FALLBACK_MODELS:
    if _model.lower() in GEMINI_SKIP_MODELS or _model in GEMINI_MODELS:
        continue
    GEMINI_MODELS.append(_model)
# Cau van hoc (prefer_rich_style): thu Gemini 2.5 Pro TRUOC (tieng Viet tot nhat trong
# dam free, hieu sac thai van chuong). Free tier Pro gioi han request/ngay -> het quota
# thi tu rot xuong Cerebras gpt-oss-120b roi Gemini flash. KHONG dung cho factual/verifier
# de khong dot quota Pro quy. Env GEMINI_LIT_MODELS de chinh.
GEMINI_LIT_MODELS = [
    m.strip() for m in os.getenv("GEMINI_LIT_MODELS", "gemini-2.5-pro").split(",")
    if m.strip() and m.strip().lower() not in GEMINI_SKIP_MODELS
]
# Provider OpenAI-compatible bo sung, free tier khong can the: chi bat khi co key trong env.
# "models" la chain fallback: model dau la chinh; ID sai/404 thi tu nhay model sau.
EXTRA_OPENAI_PROVIDERS = [
    {"name": name, "url": url, "keys": keys,
     "models": ([os.getenv(model_env)] if os.getenv(model_env) else []) + default_models}
    for name, url, keys_env, model_env, default_models in (
        # gpt-oss-120b la model lon nhat free tier Cerebras thuc su cap quyen
        # (qwen-235b/glm-4.6 tra 404 "no access" voi key free — da thu 2026-07-11).
        ("cerebras", "https://api.cerebras.ai/v1/chat/completions",
         "CEREBRAS_API_KEYS", "CEREBRAS_MODEL",
         ["gpt-oss-120b", "qwen-3-32b", "llama-3.3-70b"]),
        ("openrouter", "https://openrouter.ai/api/v1/chat/completions",
         "OPENROUTER_API_KEYS", "OPENROUTER_MODEL",
         ["meta-llama/llama-3.3-70b-instruct:free"]),
        ("mistral", "https://api.mistral.ai/v1/chat/completions",
         "MISTRAL_API_KEYS", "MISTRAL_MODEL", ["mistral-small-latest"]),
    )
    if (keys := [k.strip() for k in os.getenv(keys_env, "").split(",") if k.strip()])
]
MAX_DISCORD_LEN = 3800
WEB_RESULT_LIMIT = 3
WEB_CONTEXT_LIMIT = 3
GROQ_MAX_PROMPT_CHARS = int(os.getenv("GROQ_MAX_PROMPT_CHARS", "24000"))
GROQ_SAFE_PROMPT_CHARS = int(os.getenv("GROQ_SAFE_PROMPT_CHARS", "18000"))
CONTEXT_MAX_CHARS = int(os.getenv("HVHN_CONTEXT_MAX_CHARS", "18000"))
COMPACT_CONTEXT_MAX_CHARS = int(os.getenv("HVHN_COMPACT_CONTEXT_MAX_CHARS", "9000"))
SYSTEM_EXTRA_MAX_CHARS = 32000
VERIFIER_EVIDENCE_MAX_CHARS = 6000
# Sampling cho nhanh sinh cau tra loi VAN HOC chinh: noi rong de van co chat,
# giau tu vung, khong khô/lap; do dai du de phan tich sau. Cac nhanh factual/
# verifier van giu mac dinh chat (temp thap, top_p 0.4) de khong tang ao giac.
LIT_TEMPERATURE = float(os.getenv("HVHN_LIT_TEMPERATURE", "0.7"))
LIT_TOP_P = float(os.getenv("HVHN_LIT_TOP_P", "0.95"))
LIT_MAX_TOKENS = int(os.getenv("HVHN_LIT_MAX_TOKENS", "3000"))
AI_ANSWER_TIMEOUT_SECONDS = int(os.getenv("HVHN_AI_ANSWER_TIMEOUT_SECONDS", "105"))
AI_FORCE_FALLBACK_TIMEOUT_SECONDS = int(os.getenv("HVHN_AI_FORCE_FALLBACK_TIMEOUT_SECONDS", "35"))
LOW_RETRIEVAL_SCORE = float(os.getenv("HVHN_LOW_RETRIEVAL_SCORE", "1.0"))
# Duoi nguong nay coi nhu truy xuat .md lac de -> khong nhoi vao context (tranh chep tai lieu khong lien quan).
MD_MIN_RELEVANCE = float(os.getenv("HVHN_MD_MIN_RELEVANCE", "2.0"))
RETRIEVAL_DEBUG = os.getenv("HVHN_RETRIEVAL_DEBUG", "").strip().lower() in {"1", "true", "yes", "on"}
DEBUG_COMMAND_TIMEOUT_SECONDS = int(os.getenv("HVHN_DEBUG_COMMAND_TIMEOUT_SECONDS", "25"))
PDF_DEFAULT_LIMIT = int(os.getenv("HVHN_PDF_DEFAULT_LIMIT", "7"))
PDF_AGGREGATE_LIMIT = int(os.getenv("HVHN_PDF_AGGREGATE_LIMIT", "16"))
TRUSTED_SOURCE_HINTS = (
    ".gov.vn",
    ".edu.vn",
    "moet.gov.vn",
    "chinhphu.vn",
    "quochoi.vn",
    "thuvienphapluat.vn",
    "nxb",
    "thivien.net",
    "wikipedia.org",
)


def _load_literature_system_instructions() -> str:
    path = Path(__file__).resolve().parents[1] / "SYSTEM INSTRUCTIONS.txt"
    try:
        text = path.read_text(encoding="utf-8").strip()
    except Exception:
        return ""
    if len(text) > SYSTEM_EXTRA_MAX_CHARS:
        text = text[:SYSTEM_EXTRA_MAX_CHARS] + "\n...(da rut gon chi thi he thong vi qua dai)"
    return text


LITERATURE_SYSTEM_INSTRUCTIONS = _load_literature_system_instructions()


def _plain_ascii(value: str) -> str:
    text = unicodedata.normalize("NFKD", value or "")
    text = "".join(c for c in text if not unicodedata.combining(c))
    return text.replace("đ", "d").replace("Đ", "D")


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


def _load_style_guide() -> str:
    path = Path(__file__).resolve().parents[1] / "STYLE VAN PHONG.txt"
    try:
        text = path.read_text(encoding="utf-8").strip()
    except Exception:
        return ""
    if len(text) > SYSTEM_EXTRA_MAX_CHARS:
        text = text[:SYSTEM_EXTRA_MAX_CHARS] + "\n...(rut gon STYLE vi qua dai)"
    return text


STYLE_GUIDE = _load_style_guide()


def _clip_text(value: str, max_chars: int) -> str:
    value = (value or "").strip()
    if len(value) <= max_chars:
        return value
    return value[:max_chars].rsplit(" ", 1)[0].rstrip() + "\n...(rut gon vi qua dai)"


def _budget_append(parts: list[str], label: str, text: str, remaining: int) -> int:
    text = (text or "").strip()
    if not text or remaining <= len(label) + 20:
        return remaining
    block = f"{label}:\n{_clip_text(text, remaining - len(label) - 3)}"
    if len(block) > remaining:
        block = _clip_text(block, remaining)
    parts.append(block)
    return remaining - len(block) - 2


def build_context_budget(
    query: str,
    pdf_chunks: str,
    manual_knowledge: str,
    web_results: str,
    max_chars: int,
    *,
    teacher_feedback: str = "",
) -> str:
    parts: list[str] = []
    remaining = max(1200, max_chars)
    remaining = _budget_append(parts, "KHO TRI THUC HVHN UU TIEN", pdf_chunks, remaining)
    remaining = _budget_append(parts, "TRI THUC HVHN THU CONG", manual_knowledge, remaining)
    remaining = _budget_append(parts, "GOP Y GIAO VIEN DA SUA", teacher_feedback, remaining)
    remaining = _budget_append(parts, "NGUON WEB TIN CAY BO SUNG", web_results, remaining)
    if not parts:
        return ""
    return "\n\n".join(parts)


def _context_part_stats(pdf_chunks: str, manual_knowledge: str, teacher_feedback: str, web_results: str, final_context: str) -> dict:
    return {
        "pdf_chars": len(pdf_chunks or ""),
        "manual_chars": len(manual_knowledge or ""),
        "feedback_chars": len(teacher_feedback or ""),
        "web_chars": len(web_results or ""),
        "final_context_chars": len(final_context or ""),
        "context_truncated": len(final_context or "") < (
            len(pdf_chunks or "") + len(manual_knowledge or "") + len(teacher_feedback or "") + len(web_results or "")
        ),
    }

SYSTEM_PROMPT = (
    "Bạn là trợ giảng môn Ngữ Văn cho cộng đồng HVHN. Trả lời bằng tiếng Việt có dấu, "
    "rõ trọng tâm, ưu tiên giúp học sinh tự suy nghĩ. Tuyệt đối không bịa thông tin. "
    "Nếu không đủ căn cứ, phải nói rõ không đủ dữ liệu thay vì đoán bừa."
)

THEN_SYSTEM_PROMPT = (
    "Bạn là Then, trợ giảng Ngữ Văn của Hồn Văn - Hồn Người.\n"
    "LUẬT BẮT BUỘC:\n"
    "1. Không được bịa tác giả, tác phẩm, nhân vật, năm sáng tác, hoàn cảnh sáng tác, "
    "trích dẫn, nhận định phê bình, số liệu, hay nội dung bài học.\n"
    "2. Không đặt trong dấu ngoặc kép bất kỳ câu nào nếu câu đó không xuất hiện trong "
    "văn bản người dùng gửi hoặc KHO TRI THỨC HVHN LIÊN QUAN.\n"
    "2b. GÁN TÁC GIẢ: chỉ gán một câu/nhận định cho một người khi (a) ngay cạnh câu đó "
    "trong nguồn có dấu quy kết rõ ('X viết:', '— X', 'theo X'), hoặc (b) ngữ cảnh ghi rõ "
    "'TÁC GIẢ: <tên>' cho đoạn đó — khi ấy người viết đoạn chính là tác giả đó. TUYỆT ĐỐI "
    "không lấy một cái tên xuất hiện ở chỗ khác trong kho để gán cho câu đang xét. Nếu không "
    "xác định được, nói thẳng 'chưa xác định được tác giả trong tài liệu' thay vì đoán.\n"
    "3. Nếu câu hỏi cần chi tiết văn bản/tác phẩm mà không có dữ liệu xác thực, hãy nói "
    "'không đủ dữ liệu để khẳng định' và đưa cách kiểm chứng/hướng làm an toàn.\n"
    "4. Chỉ nhận xét dựa trên văn bản người dùng đưa vào; không suy diễn "
    "học sinh đã viết những ý không có trong bài.\n"
    "5. Luôn trả lời trực tiếp vào câu hỏi trước, rồi mới nói nguồn/căn cứ sau.\n"
    "6. Không được trả lời kiểu 'có thể tham khảo các nguồn sau' rồi liệt kê link. "
    "Nguồn web chỉ là căn cứ để tổng hợp thành câu trả lời.\n"
    "7. Không mở đầu bằng công thức máy móc kiểu 'Câu trả lời đúng trọng tâm là...', "
    "'Dưới đây là...'. Vào thẳng nội dung như một người thầy đang trò chuyện.\n"
    "8. CẤM trả lời chung chung, rỗng nghĩa kiểu lặp lại từ khóa câu hỏi ('phong cách X "
    "độc đáo, sâu sắc, giàu hình ảnh' mà không nói RÕ độc đáo ở đâu). Khi có tài liệu/nguồn "
    "liên quan, BẮT BUỘC dùng chi tiết, câu thơ, dẫn chứng, nhận định CỤ THỂ trong đó để "
    "phân tích; mỗi ý phải gắn với một dẫn chứng hoặc lập luận riêng, không nói suông.\n"
    "9. Người dùng có thể gõ sai chính tả hoặc thiếu dấu tên tác giả/tác phẩm — hãy hiểu "
    "theo nghĩa đúng gần nhất và trả lời, không bắt bẻ lỗi gõ.\n"
    "10. Ngữ cảnh 'KHO TRI THỨC HVHN' đưa kèm CÓ THỂ KHÔNG liên quan câu hỏi. Chỉ dùng "
    "phần thực sự khớp với ĐỀ BÀI/tác phẩm đang hỏi. Nếu tài liệu nói về tác giả/tác phẩm "
    "KHÁC (ví dụ đề hỏi bài thơ A nhưng tài liệu nói về Xuân Diệu/Thơ Mới), TUYỆT ĐỐI bỏ qua, "
    "không được lắp nội dung đó vào bài. Với nghị luận xã hội: phân tích từ chính ngữ liệu đề "
    "cho và dẫn chứng đời sống thực, không mượn lý luận phê bình văn học.\n"
    "11. TRÍCH THƠ/VĂN NGUYÊN VĂN TRONG MỌI CHẾ ĐỘ (kể cả khi chỉ phân tích, không được yêu "
    "cầu 'chép nguyên văn'): khi dẫn một câu thơ/câu văn, phải chép ĐÚNG TỪNG CHỮ, đúng dấu "
    "câu, GIỮ NGUYÊN các điệp từ/điệp ngữ ('và… và… và', 'này đây… này đây', 'cho… cho…'). "
    "TUYỆT ĐỐI không rút gọn, không gộp câu, không diễn xuôi thơ rồi bỏ trong ngoặc kép. Nếu "
    "không nhớ/không có chính xác nguyên văn thì mô tả bằng lời thường, KHÔNG đặt trong ngoặc "
    "kép. Chính điệp từ, nhịp, cú pháp là bằng chứng phong cách — làm mất chúng là làm hỏng bài.\n"
    "12. CẤM phân tích 3 tầng cụt 'khẳng định → dẫn thơ → lặp lại khẳng định'. Mỗi luận điểm "
    "BẮT BUỘC đủ 4 tầng: (a) gọi tên thủ pháp/nhãn tự cụ thể → (b) trích đúng nguyên văn dẫn "
    "chứng → (c) phân tích VÌ SAO thủ pháp đó tạo ra hiệu quả ấy (đi vào cơ chế, không nói "
    "chung 'thể hiện sự phong phú') → (d) khái quát lên tư tưởng/phong cách. Không kết bài bằng "
    "cách tóm lại y hệt thân bài. Không lặp lại cùng một cụm khái quát quá một lần trong bài.\n"
    "13. Ngữ cảnh kèm theo (Nguồn:, tên báo, tên trang, tên tài liệu) CHỈ để bạn tự đối chiếu, "
    "TUYỆT ĐỐI KHÔNG nêu tên nguồn nội bộ đó trong bài (không viết 'theo báo X', 'trên trang báo Y', "
    "'trong tài liệu Z'). CẤM kết bài bằng lời khuyên đi kiểm chứng/tra cứu/đọc toàn văn bài viết ở "
    "một tờ báo hay trang nào — người hỏi cần một bài hoàn chỉnh, không phải chỉ dẫn đi đọc chỗ khác. "
    "Kết bài phải chốt lại bằng một nhận định của chính mình.\n"
    "14. VĂN PHẢI CÓ HƠI THỞ, đừng khô như báo cáo học thuật. Tránh lối viết cứng đờ, đầy thuật ngữ "
    "biên khảo kiểu 'cơ chế biểu hiện của sự kế thừa', 'kiến tạo kiểu nhân vật', 'vùng thẩm mỹ', "
    "'được mổ xẻ trực diện'. Thay vào đó viết như một người thầy đang say sưa giảng: câu có nhịp, "
    "có chỗ nhấn, có cảm xúc thật trước cái hay của văn chương; dùng hình ảnh sống động nhưng gắn "
    "chặt vào dẫn chứng, không sáo. Được phép giàu hình ảnh, chỉ cấm mơ hồ và rỗng nghĩa.\n"
    "15. GIỌNG CHU VĂN SƠN — BẮT BUỘC, KHÔNG THƯƠNG LƯỢNG (bài phân tích văn học):\n"
    "  (a) MỔ MỘT CHỮ ĐẮT: mỗi bài PHẢI dừng lại soi ÍT NHẤT MỘT chữ/nhãn tự cụ thể — trỏ đúng chữ đó "
    "ra, hỏi vì sao Nam Cao/tác giả chọn CHÍNH chữ ấy chứ không phải chữ khác (vd chữ 'ươn ướt' chứ "
    "không phải 'khóc'; 'thấy' chứ không phải 'nghĩ'). Phân tích Ý mà không mổ CHỮ là hỏng, viết lại.\n"
    "  (b) CÓ 'TÔI' THẬT dẫn dắt: dám nêu chính kiến ('Tôi nghĩ...', 'Tôi cho rằng...', 'Không hẳn.'), "
    "trò chuyện với người đọc, KHÔNG tuyên ngôn vô ngã.\n"
    "  (c) NHỊP: đan câu dài–ngắn; sau một đoạn phân tích dày phải có MỘT câu cực ngắn dằn giọng chốt ý "
    "('Không hẳn.', 'Chỉ một chữ thôi.', 'Thế là đủ.'). Ít nhất MỘT câu hỏi tu từ mở ý rồi tự trả lời.\n"
    "  (d) CẤM TUYỆT ĐỐI lối bài văn mẫu: KHÔNG tiêu đề tiểu mục kiểu 'Bát cháo hành — Hiện thân của...'; "
    "KHÔNG các cụm đao to búa lớn rỗng ('kết tinh toàn bộ tư tưởng nhân đạo', 'tài năng nghệ thuật bậc "
    "thầy', 'chân lý nghệ thuật', 'cứu rỗi một linh hồn', 'giá trị nhân văn sâu sắc'). Mọi khái quát lớn "
    "phải mọc LÊN TỪ một chữ/một dẫn chứng vừa mổ, không phán từ trên trời.\n"
    "16. TƯ DUY PHẢI CHẶT VÀ CÓ PHÁT HIỆN RIÊNG: (a) không nói lại điều sách giáo khoa ai cũng biết — bài "
    "phải có ÍT NHẤT MỘT ý mới mẻ, một góc nhìn/phát hiện của riêng mình (một nghịch lí, một chi tiết bị "
    "bỏ quên, một cách đọc lệch khỏi lối mòn). (b) Lập luận phải có phản đề hoặc đặt cạnh một cách hiểu "
    "khác rồi bác lại/bổ sung ('Người ta thường bảo... nhưng...'), không xuôi chiều một mạch. (c) Mỗi "
    "luận điểm phải THẮT vào luận điểm trước, dẫn tới một kết luận KHÔNG đoán trước được từ câu mở.\n"
    "17. TUYỆT ĐỐI KHÔNG BIẾN CÂU TRẢ LỜI THÀNH BẢN KIỂM KÊ TÀI LIỆU. Ngữ cảnh/trích dẫn kèm theo chỉ "
    "là NGUYÊN LIỆU để bạn viết bài, KHÔNG phải đối tượng để mô tả. CẤM: 'Tóm tắt các tài liệu liên quan "
    "nhất', lập bảng liệt kê trích dẫn của từng tác giả, 'Đánh giá mức độ đầy đủ dữ liệu', 'các trích dẫn "
    "trên là tài liệu ưu tiên nhất', bàn xem 'có/không đủ dữ liệu để...'. Người hỏi cần một BÀI NGHỊ LUẬN "
    "hoàn chỉnh trả lời thẳng câu hỏi bằng lập luận và chính kiến của bạn — được dùng dẫn chứng trong ngữ "
    "cảnh nhưng phải DỆT chúng vào mạch phân tích, không kê khai. Nếu ngữ cảnh không đủ hoặc lạc đề, cứ tự "
    "phân tích bằng kiến thức văn học của mình; TUYỆT ĐỐI không quay ra tường thuật/xếp hạng tài liệu.\n"
    "Giọng văn: sắc, ấm, giàu hình ảnh nhưng không mơ hồ, viết như người thật chứ không như "
    "bản mẫu. Câu hỏi đơn giản thì trả lời gọn; câu hỏi cần phân tích thì đi sâu có lớp lang, "
    "tách rõ nội dung, nghệ thuật và liên hệ mở rộng."
)

_THEN_SYSTEM_PROMPT_CORE = THEN_SYSTEM_PROMPT

THEN_SYSTEM_PROMPT = _THEN_SYSTEM_PROMPT_CORE + (
    ("\n\n=== CHI THI VAN PHONG & CHONG AO GIAC (BAT BUOC TUAN THU) ===\n"
     + LITERATURE_SYSTEM_INSTRUCTIONS) if LITERATURE_SYSTEM_INSTRUCTIONS else ""
) + (
    ("\n\n=== VI DU XAU -> TOT (tranh dung cac loi nay: chen chu Trung, bia chi tiet, hoi hot) ===\n"
     + BONUS_FEWSHOT) if BONUS_FEWSHOT else ""
) + (
    ("\n\n=== VAN PHONG MAU — HOC THEO GIONG AM/SONG (khong khô, khong sao rong) ===\n"
     + STYLE_GUIDE) if STYLE_GUIDE else ""
)

# Compact system prompt used for the Groq path only. Groq has a much smaller
# effective context budget than Gemini, so the full THEN_SYSTEM_PROMPT
# (which can grow to ~35k chars once LITERATURE_SYSTEM_INSTRUCTIONS and
# BONUS_FEWSHOT are appended) never fits and previously caused unrecoverable
# 413 errors even after prompt compression. This trimmed variant keeps the
# core rules plus a short head of the literary style instructions, dropping
# BONUS_FEWSHOT entirely, while still enforcing Vietnamese output and the
# anti-fabrication / no-fake-quote rules.
_GROQ_INSTRUCTIONS_HEAD_CHARS = 2500
THEN_SYSTEM_PROMPT_GROQ = _THEN_SYSTEM_PROMPT_CORE + (
    ("\n\n=== STYLE & ANTI-HALLUCINATION NOTES (SUMMARY) ===\n"
     + LITERATURE_SYSTEM_INSTRUCTIONS[:_GROQ_INSTRUCTIONS_HEAD_CHARS])
    if LITERATURE_SYSTEM_INSTRUCTIONS else ""
)
if len(THEN_SYSTEM_PROMPT_GROQ) > GROQ_SAFE_PROMPT_CHARS:
    THEN_SYSTEM_PROMPT_GROQ = THEN_SYSTEM_PROMPT_GROQ[:GROQ_SAFE_PROMPT_CHARS]


def _user_is_teacher(interaction: discord.Interaction) -> bool:
    # Giáo viên/admin: có quyền manage_guild HOẶC mang role admin/giáo viên cấu hình.
    if not isinstance(interaction.user, discord.Member):
        return False
    if interaction.user.guild_permissions.manage_guild:
        return True
    allow = {r.strip().lower() for r in os.getenv("HVHN_TEACHER_ROLES", "HVHN Admin,Giáo viên").split(",") if r.strip()}
    return any(role.name.strip().lower() in allow for role in interaction.user.roles)


class FeedbackModal(discord.ui.Modal, title="Sửa câu trả lời cho Then"):
    correction = discord.ui.TextInput(
        label="Câu sửa / góp ý của giáo viên",
        style=discord.TextStyle.paragraph,
        required=True,
        max_length=1800,
    )

    def __init__(self, bot: commands.Bot, prompt: str, answer: str):
        super().__init__()
        self.bot = bot
        self.prompt = prompt
        self.answer = answer

    async def on_submit(self, interaction: discord.Interaction):
        # Chỉ correction của giáo viên/admin được DUYỆT (đưa vào ngữ cảnh AI). Người khác:
        # lưu dạng CHỜ DUYỆT, không dùng cho tới khi giáo viên duyệt -> chống đầu độc feedback.
        approved = _user_is_teacher(interaction)
        await self.bot.db.execute(
            """
            INSERT INTO ai_feedback (user_id, prompt, answer, rating, correction, approved)
            VALUES ($1, $2, $3, 'needs_fix', $4, $5)
            """,
            interaction.user.id,
            self.prompt,
            self.answer,
            str(self.correction),
            approved,
        )
        msg = ("Đã lưu góp ý của giáo viên (đã duyệt). Then sẽ dùng để mài câu trả lời."
               if approved else
               "Đã ghi nhận góp ý — sẽ được giáo viên xem xét trước khi Then sử dụng. Cảm ơn bạn!")
        await interaction.response.send_message(msg, ephemeral=True)


class FeedbackView(discord.ui.View):
    def __init__(self, bot: commands.Bot, prompt: str, answer: str):
        super().__init__(timeout=86400)
        self.bot = bot
        self.prompt = prompt
        self.answer = answer

    @discord.ui.button(label="Đúng", style=discord.ButtonStyle.success)
    async def good(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.bot.db.execute(
            """
            INSERT INTO ai_feedback (user_id, prompt, answer, rating)
            VALUES ($1, $2, $3, 'good')
            """,
            interaction.user.id,
            self.prompt,
            self.answer,
        )
        await interaction.response.send_message("Đã lưu đánh giá tốt.", ephemeral=True)

    @discord.ui.button(label="Cần sửa", style=discord.ButtonStyle.danger)
    async def needs_fix(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(FeedbackModal(self.bot, self.prompt, self.answer))


def _rag_plain(value: str) -> str:
    value = unicodedata.normalize("NFD", value or "")
    value = "".join(ch for ch in value if unicodedata.category(ch) != "Mn").lower()
    return value.replace("đ", "d")


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


@dataclass
class RAGPlan:
    intent: str
    exact_quote: bool = False
    aggregate: bool = False
    document_only: bool = False
    external_knowledge: bool = False
    citations: bool = True
    author_filter: str = ""
    retrieval_limit: int = PDF_DEFAULT_LIMIT
    use_llm: bool = True
    reason: str = ""
    genre: str = "NONE"
    level: str = "THUONG"
    write_essay: bool = False


@dataclass
class QuoteEvidence:
    quote: str
    author: str = "UNKNOWN"
    pdf_title: str = ""
    page: int | None = None
    chunk_id: str = ""
    source: str = ""
    chunk: int | None = None
    context: str = ""
    confidence: float = 0.0
    score: int = 0


@dataclass
class QuoteSpan:
    quote: str
    start: int
    end: int


class IntentClassifier:
    @staticmethod
    def classify(message: str) -> str:
        q = _rag_plain(message)
        if "debug" in q:
            return "DEBUG"
        quote_markers = ("chep nguyen van", "nguyen van", "dung tung chu", "trich dan", "trich nguyen")
        aggregate_markers = ("tong hop", "tat ca", "moi nhan dinh", "toan bo", "liet ke", "cho minh 5", "5 nhan dinh")
        if any(m in q for m in quote_markers):
            return "QUOTE_COLLECTION" if any(m in q for m in aggregate_markers) else "QUOTE_SINGLE"
        if any(m in q for m in aggregate_markers):
            return "QUOTE_COLLECTION" if "nhan dinh" in q or "trich" in q else "SUMMARY"
        if "so sanh" in q or "doi chieu" in q:
            return "COMPARE"
        if "dan y" in q or "lap dan y" in q:
            return "OUTLINE"
        if "phan tich" in q or "cam nhan" in q or "binh giang" in q:
            return "ANALYSIS"
        if "giai thich" in q or "la gi" in q or "khai niem" in q:
            return "EXPLAIN"
        if any(m in q for m in ("moi nhat", "hom nay", "hien nay", "tra cuu web", "tin tuc")):
            return "WEB_SEARCH"
        return "CHAT"


class Planner:
    @staticmethod
    def author_filter(message: str) -> str:
        # \.? sau moi token de bat ten viet tat co dau cham: "A. Camus", "F. Kafka".
        patterns = [
            r"(?:của|cua)\s+([A-ZÀ-ỸĐ][\wÀ-ỹĐđ]*\.?(?:\s+[A-ZÀ-ỸĐ][\wÀ-ỹĐđ]*\.?){0,4})",
            r"(?:tác giả|tac gia)\s+([A-ZÀ-ỸĐ][\wÀ-ỹĐđ]*\.?(?:\s+[A-ZÀ-ỸĐ][\wÀ-ỹĐđ]*\.?){0,4})",
        ]
        for pattern in patterns:
            match = re.search(pattern, message or "")
            if match:
                value = re.sub(r"\s+", " ", match.group(1)).strip(" .,:;?!")
                stop = re.search(r"\b(về|ve|trong|theo|là|la|và|va)\b", value, flags=re.I)
                if stop:
                    value = value[:stop.start()].strip()
                return value
        return ""

    NLVH_MARKERS = (
        "nghi luan van hoc", "nlvh", "tac pham", "nhan vat", "doan tho", "bai tho",
        "doan trich", "kho tho", "hinh tuong", "chi tiet nghe thuat", "gia tri nhan dao",
        "binh giang", "cam nhan ve", "phan tich bai", "phan tich doan", "phan tich nhan vat",
        "truyen ngan", "truyen dai", "tieu thuyet", "kich", "chi tiet trong", "chi tiet",
        "tinh huong truyen", "ngoi ke", "diem nhin tran thuat",
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
        literary_context = (
            any(m in q for m in cls.NLVH_MARKERS)
            or (author and any(m in q for m in ("truyen", "bai", "tho", "tac pham", "chi tiet", "nhan vat")))
        )
        if literary_context:
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

    @classmethod
    def build(cls, message: str) -> RAGPlan:
        intent = IntentClassifier.classify(message)
        q = _rag_plain(message)
        author = cls.author_filter(message)
        genre, level, write_essay = cls.classify_composition(message, intent, author)
        exact = intent == "QUOTE_SINGLE"
        aggregate = intent == "QUOTE_COLLECTION"
        document_only = any(m in q for m in ("theo tai lieu", "tai lieu da nap", "trong tai lieu", "kho pdf", "da nap")) or intent.startswith("QUOTE")
        retrieval_limit = PDF_AGGREGATE_LIMIT if intent in {"QUOTE_COLLECTION", "COMPARE", "OUTLINE", "SUMMARY"} else PDF_DEFAULT_LIMIT
        return RAGPlan(
            intent=intent,
            exact_quote=exact,
            aggregate=aggregate,
            document_only=document_only,
            external_knowledge=(intent == "WEB_SEARCH"),
            citations=True,
            author_filter=author,
            retrieval_limit=retrieval_limit,
            use_llm=intent not in {"QUOTE_SINGLE", "QUOTE_COLLECTION"},
            reason=f"intent={intent}; author={author or 'none'}",
            genre=genre,
            level=level,
            write_essay=write_essay,
        )


class QuoteExtractor:
    QUOTE_PAIRS = ((chr(8220), chr(8221)), ('"', '"'), ("'", "'"))
    AUTHOR_VERBS = ("cho rang", "viet", "noi", "khang dinh", "nhan dinh", "quan niem", "tung viet")
    UNKNOWN = "UNKNOWN"

    @classmethod
    def quote_spans(cls, text: str) -> list[QuoteSpan]:
        text = re.sub(r"\s+", " ", text or "").strip()
        spans: list[QuoteSpan] = []
        for open_q, close_q in cls.QUOTE_PAIRS:
            start = 0
            while True:
                left = text.find(open_q, start)
                if left < 0:
                    break
                right = text.find(close_q, left + 1)
                if right < 0:
                    break
                quote = text[left + 1:right].strip()
                if 20 <= len(quote) <= 1200:
                    spans.append(QuoteSpan(quote=quote, start=left, end=right + 1))
                start = right + 1
        spans.sort(key=lambda item: item.start)
        deduped = []
        seen = set()
        for span in spans:
            key = _rag_plain(span.quote)[:260]
            if key in seen:
                continue
            seen.add(key)
            deduped.append(span)
        return deduped

    @classmethod
    def quoted_units(cls, text: str) -> list[str]:
        return [span.quote for span in cls.quote_spans(text)]

    @classmethod
    def _candidate_names(cls, text: str) -> list[tuple[str, int, int]]:
        token_pattern = re.compile(r"[^\W\d_][^\W\d_'-]*", flags=re.UNICODE)
        tokens = [(m.group(0), m.start(), m.end()) for m in token_pattern.finditer(text or "")]
        names = []
        i = 0
        while i < len(tokens):
            word, start, end = tokens[i]
            if not word[:1].isupper():
                i += 1
                continue
            words = [word]
            j = i + 1
            while j < len(tokens) and len(words) < 5 and tokens[j][0][:1].isupper():
                words.append(tokens[j][0])
                end = tokens[j][2]
                j += 1
            if len(words) >= 2:
                names.append((" ".join(words), start, end))
                i = j
            else:
                i += 1
        return names

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
        if len(tail.strip()) > 40 or any(p in tail for p in ".!?…;\n"):
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

    @staticmethod
    def _author_matches(requested_plain: str, author_plain: str) -> bool:
        # Khop bien the ten: "Albert Camus" == "A. Camus" == "A.Camus" (cung ho),
        # nhung KHONG nham "Nam Cao" voi "Cao Ba Quat" (chi chung 1 token giua).
        if not requested_plain:
            return True
        if requested_plain == author_plain:
            return True
        rt = [t for t in re.split(r"[^0-9a-zà-ỹđ]+", requested_plain) if len(t) >= 2]
        at = [t for t in re.split(r"[^0-9a-zà-ỹđ]+", author_plain) if len(t) >= 2]
        if not rt or not at:
            return False
        if rt[-1] == at[-1]:            # cung HO (token cuoi)
            return True
        rs, as_ = set(rt), set(at)
        return rs <= as_ or as_ <= rs  # ten nay la tap con ten kia (vd viet tat)

    @classmethod
    def extract(cls, pdf_meta: dict, plan: RAGPlan, query: str) -> list[QuoteEvidence]:
        requested_plain = _rag_plain(plan.author_filter)
        evidences: list[QuoteEvidence] = []
        for fact in pdf_meta.get("quotes") or []:
            author = (fact.get("author") or cls.UNKNOWN).strip() or cls.UNKNOWN
            if requested_plain and not cls._author_matches(requested_plain, _rag_plain(author)):
                continue
            quote = re.sub(r"\s+", " ", fact.get("quote") or "").strip()
            if not quote:
                continue
            evidences.append(QuoteEvidence(
                quote=quote,
                author=author,
                pdf_title=fact.get("title") or "",
                page=None,
                chunk_id=f"fact::{author}",
                source=fact.get("source") or "",
                chunk=None,
                context=quote,
                confidence=1.0,
                score=1000 + AI._unit_score(query, quote),
            ))
        for chunk in pdf_meta.get("chunks") or []:
            text = re.sub(r"\s+", " ", chunk.get("content") or chunk.get("excerpt") or "").strip()
            spans = cls.quote_spans(text)
            for span in spans:
                author, confidence = cls.infer_author(text, span)
                if requested_plain and not cls._author_matches(requested_plain, _rag_plain(author)):
                    continue
                score = int(confidence * 100) + AI._unit_score(query, span.quote)
                evidences.append(QuoteEvidence(
                    quote=span.quote,
                    author=author,
                    pdf_title=chunk.get("title") or "",
                    page=chunk.get("page"),
                    chunk_id=f"{chunk.get('title') or ''}#{chunk.get('chunk_index')}",
                    source=chunk.get("source") or "",
                    chunk=chunk.get("chunk_index"),
                    context=text[max(0, span.start - 140): min(len(text), span.end + 140)],
                    confidence=confidence,
                    score=score,
                ))
        return Aggregator.deduplicate(evidences)


class Aggregator:
    @staticmethod
    def deduplicate(items: list[QuoteEvidence]) -> list[QuoteEvidence]:
        seen = set()
        out = []
        for item in sorted(items, key=lambda x: x.score, reverse=True):
            key = _rag_plain(item.quote)[:220]
            if key in seen:
                continue
            seen.add(key)
            out.append(item)
        return out


class Formatter:
    @staticmethod
    def quote_single(items: list[QuoteEvidence], plan: RAGPlan) -> str | None:
        if not items:
            who = f" của {plan.author_filter}" if plan.author_filter else ""
            return f"Chưa tìm thấy nhận định nguyên văn{who} trong các tài liệu đã truy xuất. Không nên tự bịa hoặc chép theo trí nhớ."
        item = items[0]
        author = item.author or plan.author_filter or "Không rõ tác giả trong đoạn truy xuất"
        source = f"\nNguồn: {item.pdf_title}" if item.pdf_title else ""
        return f"\"{item.quote}\"\n\nTác giả/người được gán: {author}{source}"

    @staticmethod
    def quote_collection(items: list[QuoteEvidence], plan: RAGPlan) -> str | None:
        if not items:
            return "Chưa tìm thấy các nhận định nguyên văn phù hợp trong tài liệu đã truy xuất. Không bổ sung bằng trí nhớ ngoài tài liệu."
        lines = ["Các nhận định/trích dẫn tìm thấy trong tài liệu đã truy xuất:"]
        for index, item in enumerate(items, 1):
            author = item.author or "Không rõ tác giả trong đoạn truy xuất"
            source = f" — {item.pdf_title}" if item.pdf_title else ""
            lines.append(f"{index}. \"{item.quote}\"\n   Tác giả/người được gán: {author}{source}")
        return "\n".join(lines)

    @staticmethod
    def compare_seed(items: list[QuoteEvidence], plan: RAGPlan) -> str:
        return Formatter.evidence_block(items)

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


class Scaffold:
    _COMPARE = (
        "Day la cau hoi SO SANH: khong viet theo kieu giong nhau/khac nhau chung chung.\n"
        "Voi moi truc so sanh, phai di theo nhip A -> B -> diem gap/lech: "
        "(1) lam ro khai niem/truc so sanh; (2) tac pham A: chi tiet/hinh tuong/tinh huong cu the -> y nghia; "
        "(3) tac pham B: chi tiet/hinh tuong/tinh huong cu the -> y nghia; "
        "(4) diem gap va do lech giua hai tac pham; (5) danh gia nang cao.\n"
        "Neu de bai co cac khai niem nhu chuc nang, hien thuc, sang tao, phai giai thich ngan tung khai niem "
        "roi moi ap vao tac pham. Khong neu hoan canh sang tac, trai nghiem tac gia, y do tac gia neu context "
        "khong cung cap bang chung."
    )
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
        "kiện đúng/sai, mặt trái; (4) Dẫn chứng phong phú từ thực tế đời sống và nhân vật "
        "lịch sử/người thật (không dùng dẫn chứng văn học); (5) Bài học nhận thức và hành động.\n"
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
        if plan.intent == "COMPARE":
            if plan.genre == "NONE":
                return (
                    "KHUNG TU DUY LAP LUAN:\n"
                    "Nhiem vu: tra loi theo truc so sanh co dan chung cu the; tranh van mau rong.\n"
                    f"{cls._COMPARE}"
                )
            skeleton = cls._skeleton(plan)
            return (
                "KHUNG TU DUY LAP LUAN:\n"
                "Nhiem vu: lap dan y/tra loi theo truc so sanh, moi y phai co bang chung van ban va loi binh rieng.\n"
                f"{cls._COMPARE}\n{skeleton}"
            )
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


class AI(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.groq_keys = [k.strip() for k in os.getenv("GROQ_API_KEYS", "").split(",") if k.strip()]
        self.gemini_keys = [k.strip() for k in os.getenv("GEMINI_API_KEYS", "").split(",") if k.strip()]
        self.serper_key = os.getenv("SERPER_API_KEY", "").strip()
        self.tavily_key = os.getenv("TAVILY_API_KEY", "").strip()
        self.last_ai_errors: list[str] = []
        self._last_verifier_rejected = False
        print(f"[ai] GROQ_MODEL={GROQ_MODEL}", flush=True)
        print(f"[ai] GEMINI_MODEL={GEMINI_MODEL}", flush=True)
        print(f"[ai] groq_keys={len(self.groq_keys)} gemini_keys={len(self.gemini_keys)}", flush=True)

    @staticmethod
    def _redact_key(key: str) -> str:
        if not key:
            return "<missing>"
        if len(key) <= 10:
            return key[:2] + "***" + key[-2:]
        return key[:6] + "***" + key[-4:]

    @staticmethod
    def _api_error(provider: str, model: str, status: int | None, body: str = "", exc: BaseException | None = None) -> dict:
        return {
            "provider": provider,
            "model": model,
            "status": status,
            "body": body or "",
            "exception": repr(exc) if exc else "",
        }

    @staticmethod
    def _estimated_tokens(*texts: str) -> int:
        chars = sum(len(text or "") for text in texts)
        return max(1, chars // 4)

    @staticmethod
    def _is_request_too_large(error: dict | str) -> bool:
        if isinstance(error, dict):
            status = error.get("status")
            body = str(error.get("body", "")).lower()
            return status == 413 or "request too large" in body or "tpm" in body or "tokens per minute" in body
        lowered = str(error).lower()
        return "413" in lowered or "request too large" in lowered or "tpm" in lowered

    @staticmethod
    def _compress_prompt_for_groq(prompt: str) -> str:
        head = (
            "BAN RUT GON CONTEXT: Uu tien bang chung tai lieu/manual lien quan nhat. "
            "Neu thieu du lieu, noi ro chua du du lieu de khang dinh.\n\n"
        )
        return head + _clip_text(prompt, COMPACT_CONTEXT_MAX_CHARS)

    def _log_api_event(
        self,
        event: str,
        *,
        provider: str,
        model: str,
        key: str,
        key_index: int,
        total_keys: int,
        status: int | None = None,
        body: str = "",
        exc: BaseException | None = None,
    ) -> None:
        print(
            "[ai-api] "
            f"event={event} provider={provider} model={model} "
            f"key_index={key_index}/{total_keys} key={self._redact_key(key)} key_exists={bool(key)} "
            f"groq_keys={len(self.groq_keys)} gemini_keys={len(self.gemini_keys)} "
            f"status={status} body={body!r} exception={repr(exc) if exc else ''}",
            flush=True,
        )

    async def ask_openai_compat(
        self,
        session: aiohttp.ClientSession,
        provider: str,
        url: str,
        model: str,
        key: str,
        prompt: str,
        system_prompt: str = SYSTEM_PROMPT,
        temperature: float = 0.2,
        top_p: float = 0.4,
        max_tokens: int | None = None,
    ) -> tuple[bool, str | dict]:
        headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
        payload = {
            "model": model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": prompt},
            ],
            "temperature": temperature,
            "top_p": top_p,
        }
        if max_tokens is not None:
            payload["max_tokens"] = max_tokens
        async with session.post(url, headers=headers, json=payload, timeout=60) as resp:
            if resp.status != 200:
                body = await resp.text()
                print(
                    f"[ai-api] provider={provider} model={model} non_200 status={resp.status} body={body!r}",
                    flush=True,
                )
                return False, self._api_error(provider, model, resp.status, body)
            data = await resp.json()
            return True, data["choices"][0]["message"]["content"].strip()

    async def ask_groq(
        self,
        session: aiohttp.ClientSession,
        key: str,
        prompt: str,
        system_prompt: str = SYSTEM_PROMPT,
        temperature: float = 0.2,
        top_p: float = 0.4,
        max_tokens: int | None = None,
        model: str = GROQ_MODEL,
    ) -> tuple[bool, str | dict]:
        return await self.ask_openai_compat(
            session, "groq", "https://api.groq.com/openai/v1/chat/completions",
            model, key, prompt, system_prompt, temperature, top_p, max_tokens,
        )

    async def ask_gemini(
        self,
        session: aiohttp.ClientSession,
        key: str,
        prompt: str,
        system_prompt: str = SYSTEM_PROMPT,
        temperature: float = 0.2,
        top_p: float = 0.4,
        max_tokens: int | None = None,
        model: str = GEMINI_MODEL,
    ) -> tuple[bool, str | dict]:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={key}"
        generation_config: dict = {"temperature": temperature, "topP": top_p}
        if max_tokens is not None:
            generation_config["maxOutputTokens"] = max_tokens
        payload = {
            "systemInstruction": {"parts": [{"text": system_prompt}]},
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": generation_config,
        }
        async with session.post(url, json=payload, timeout=60) as resp:
            if resp.status != 200:
                body = await resp.text()
                print(
                    f"[ai-api] provider=gemini model={model} non_200 status={resp.status} body={body!r}",
                    flush=True,
                )
                return False, self._api_error("gemini", model, resp.status, body)
            data = await resp.json()
            try:
                return True, data["candidates"][0]["content"]["parts"][0]["text"].strip()
            except (KeyError, IndexError):
                return False, self._api_error("gemini", model, 200, repr(data))

    async def generate(
        self,
        prompt: str,
        system_prompt: str = SYSTEM_PROMPT,
        temperature: float = 0.2,
        top_p: float = 0.4,
        max_tokens: int | None = None,
        prefer_rich_style: bool = False,
    ) -> str | None:
        errors: list[str] = []
        prompt_chars = len(prompt) + len(system_prompt)
        prompt_tokens = self._estimated_tokens(prompt, system_prompt)
        # prefer_rich_style: cau tra loi van hoc can chat van -> uu tien Gemini vi nhanh Groq
        # phai cat gan het chi thi van phong + vut BONUS few-shot (gioi han context), van se kho.
        prefer_gemini = (prompt_chars > GROQ_SAFE_PROMPT_CHARS or prefer_rich_style) and bool(self.gemini_keys)
        print(
            "[ai-api] "
            f"event=generate_start groq_keys={len(self.groq_keys)} gemini_keys={len(self.gemini_keys)} "
            f"groq_model={GROQ_MODEL} gemini_model={GEMINI_MODEL} "
            f"prompt_chars={prompt_chars} est_tokens={prompt_tokens} prefer_gemini={prefer_gemini}",
            flush=True,
        )
        async with aiohttp.ClientSession() as session:

            async def try_gemini_all(event: str, models: list[str] | None = None) -> str | None:
                # Thu tung model (free tier tinh theo model) x tung key.
                for gemini_model in (models if models is not None else GEMINI_MODELS):
                    for index, key in enumerate(self.gemini_keys, start=1):
                        self._log_api_event(
                            event,
                            provider="gemini",
                            model=gemini_model,
                            key=key,
                            key_index=index,
                            total_keys=len(self.gemini_keys),
                            body=f"prompt_chars={prompt_chars} est_tokens={prompt_tokens}",
                        )
                        try:
                            ok, content = await self.ask_gemini(
                                session, key, prompt, system_prompt, temperature, top_p, max_tokens, model=gemini_model
                            )
                            if ok:
                                self.last_ai_errors = []
                                self._log_api_event(
                                    "ok", provider="gemini", model=gemini_model,
                                    key=key, key_index=index, total_keys=len(self.gemini_keys),
                                )
                                return str(content)
                            if isinstance(content, dict):
                                errors.append(
                                    f"provider=gemini model={gemini_model} status={content.get('status')} body={content.get('body', '')}"
                                )
                        except Exception as exc:
                            errors.append(f"Gemini exception: {type(exc).__name__}: {exc}")
                return None

            async def try_extras() -> str | None:
                # Provider OpenAI-compatible (Cerebras/OpenRouter/Mistral): moi provider
                # co chain model rieng; dung prompt/system goc (Cerebras context lon),
                # chi nen khi qua dai.
                extra_system = system_prompt
                extra_prompt = prompt
                if len(extra_prompt) + len(extra_system) > 60000:
                    extra_prompt = self._compress_prompt_for_groq(prompt)
                for provider in EXTRA_OPENAI_PROVIDERS:
                    for extra_model in provider["models"]:
                        for index, key in enumerate(provider["keys"], start=1):
                            self._log_api_event(
                                "try",
                                provider=provider["name"],
                                model=extra_model,
                                key=key,
                                key_index=index,
                                total_keys=len(provider["keys"]),
                                body=f"prompt_chars={len(extra_prompt) + len(extra_system)}",
                            )
                            try:
                                ok, content = await self.ask_openai_compat(
                                    session, provider["name"], provider["url"], extra_model, key,
                                    extra_prompt, extra_system, temperature, top_p, max_tokens,
                                )
                                if ok:
                                    self.last_ai_errors = []
                                    self._log_api_event(
                                        "ok", provider=provider["name"], model=extra_model,
                                        key=key, key_index=index, total_keys=len(provider["keys"]),
                                    )
                                    return str(content)
                                if isinstance(content, dict):
                                    errors.append(
                                        f"provider={provider['name']} model={extra_model} status={content.get('status')} body={content.get('body', '')}"
                                    )
                                    # Model ID sai/khong ton tai -> bo qua key con lai, nhay model sau.
                                    if content.get("status") in (400, 404):
                                        break
                            except Exception as exc:
                                errors.append(f"{provider['name']} exception: {type(exc).__name__}: {exc}")
                return None

            # Cau hoi van hoc — thu tu uu tien chat luong tieng Viet:
            #  1) Gemini 2.5 Pro (tot nhat cho van Viet; free tier gioi han/ngay)
            #  2) Cerebras gpt-oss-120b (quota ben, chi khi co CEREBRAS_API_KEYS;
            #     qwen-3-235b/glm-4.6 tra 404 no-access voi key free)
            #  3) Gemini flash  4) Groq
            if prefer_rich_style and self.gemini_keys and GEMINI_LIT_MODELS:
                result = await try_gemini_all("try_lit_gemini_pro", models=GEMINI_LIT_MODELS)
                if result is not None:
                    return result

            tried_extras_first = False
            if prefer_rich_style and EXTRA_OPENAI_PROVIDERS:
                tried_extras_first = True
                result = await try_extras()
                if result is not None:
                    return result

            if prefer_gemini:
                result = await try_gemini_all("try_long_context_first")
                if result is not None:
                    return result

            # Groq has a much tighter effective context budget than Gemini.
            # If the caller's system prompt is the large THEN_SYSTEM_PROMPT
            # (instructions + BONUS examples appended), swap in the compact
            # Groq-only variant so the request can actually fit and the 413
            # retry below has a real chance of succeeding.
            groq_system_prompt = system_prompt
            if len(system_prompt) > GROQ_SAFE_PROMPT_CHARS:
                groq_system_prompt = THEN_SYSTEM_PROMPT_GROQ

            groq_prompt = prompt
            if len(groq_prompt) + len(groq_system_prompt) > GROQ_MAX_PROMPT_CHARS:
                groq_prompt = self._compress_prompt_for_groq(prompt)
                print(
                    "[ai-api] "
                    f"event=groq_prompt_compressed original_chars={len(prompt) + len(groq_system_prompt)} "
                    f"compressed_chars={len(groq_prompt) + len(groq_system_prompt)} "
                    f"est_tokens={self._estimated_tokens(groq_prompt, groq_system_prompt)}",
                    flush=True,
                )
            # Quota Groq tinh theo (model x org): model chinh chay het TPD thi cac model
            # fallback tren cung key van con nguyen quota.
            for groq_model in GROQ_MODELS:
              for index, key in enumerate(self.groq_keys, start=1):
                self._log_api_event(
                    "try",
                    provider="groq",
                    model=groq_model,
                    key=key,
                    key_index=index,
                    total_keys=len(self.groq_keys),
                    body=f"prompt_chars={len(groq_prompt) + len(groq_system_prompt)} est_tokens={self._estimated_tokens(groq_prompt, groq_system_prompt)}",
                )
                try:
                    ok, content = await self.ask_groq(session, key, groq_prompt, groq_system_prompt, temperature, top_p, max_tokens, model=groq_model)
                    if ok:
                        self.last_ai_errors = []
                        self._log_api_event(
                            "ok",
                            provider="groq",
                            model=groq_model,
                            key=key,
                            key_index=index,
                            total_keys=len(self.groq_keys),
                        )
                        return str(content)
                    if isinstance(content, dict):
                        self._log_api_event(
                            "non_200",
                            provider="groq",
                            model=groq_model,
                            key=key,
                            key_index=index,
                            total_keys=len(self.groq_keys),
                            status=content.get("status"),
                            body=content.get("body", ""),
                        )
                        errors.append(
                            f"provider=groq model={groq_model} status={content.get('status')} body={content.get('body', '')}"
                        )
                        if self._is_request_too_large(content) and groq_prompt == prompt:
                            retry_prompt = self._compress_prompt_for_groq(prompt)
                            self._log_api_event(
                                "retry_compressed_after_413",
                                provider="groq",
                                model=groq_model,
                                key=key,
                                key_index=index,
                                total_keys=len(self.groq_keys),
                                status=content.get("status"),
                                body=f"retry_chars={len(retry_prompt) + len(groq_system_prompt)} est_tokens={self._estimated_tokens(retry_prompt, groq_system_prompt)}",
                            )
                            ok2, content2 = await self.ask_groq(session, key, retry_prompt, groq_system_prompt, temperature, top_p, max_tokens, model=groq_model)
                            if ok2:
                                self.last_ai_errors = []
                                return str(content2)
                            if isinstance(content2, dict):
                                errors.append(
                                    f"provider=groq model={groq_model} retry status={content2.get('status')} body={content2.get('body', '')}"
                                )
                    else:
                        errors.append(f"Groq {content}")
                        self._log_api_event(
                            "error",
                            provider="groq",
                            model=groq_model,
                            key=key,
                            key_index=index,
                            total_keys=len(self.groq_keys),
                            body=str(content),
                        )
                except Exception as exc:
                    msg = f"Groq exception: {type(exc).__name__}: {exc}"
                    errors.append(msg)
                    self._log_api_event(
                        "exception",
                        provider="groq",
                        model=groq_model,
                        key=key,
                        key_index=index,
                        total_keys=len(self.groq_keys),
                        exc=exc,
                    )

            if not prefer_gemini:
                result = await try_gemini_all("try")
                if result is not None:
                    return result

            if not tried_extras_first:
                result = await try_extras()
                if result is not None:
                    return result
        self.last_ai_errors = errors[-8:]
        print(
            "[ai-api] "
            f"event=all_failed groq_keys={len(self.groq_keys)} gemini_keys={len(self.gemini_keys)} "
            f"errors={self.last_ai_errors!r}",
            flush=True,
        )
        return None


    def _has_ai(self) -> bool:
        return bool(self.groq_keys or self.gemini_keys or EXTRA_OPENAI_PROVIDERS)

    def _ai_error_message(self) -> str:
        joined = " | ".join(self.last_ai_errors)
        if not joined:
            return "AI loi API nhung chua co chi tiet trong log."
        compact = re.sub(r"\s+", " ", joined).strip()
        if len(compact) > 1500:
            compact = compact[:1500] + "..."
        return "AI API failed. Provider details: " + compact

    @staticmethod
    def _split_answer_pages(answer: str, max_chars: int = MAX_DISCORD_LEN) -> list[str]:
        text = (answer or "").strip()
        if not text:
            return [""]
        if len(text) <= max_chars:
            return [text]

        pages: list[str] = []
        current = ""

        def flush_current() -> None:
            nonlocal current
            if current.strip():
                pages.append(current.strip())
                current = ""

        def push_unit(unit: str) -> None:
            nonlocal current
            unit = unit.strip()
            if not unit:
                return
            if len(unit) > max_chars:
                flush_current()
                for part in AI._split_oversized_unit(unit, max_chars):
                    pages.append(part)
                return
            candidate = f"{current}\n\n{unit}".strip() if current else unit
            if len(candidate) <= max_chars:
                current = candidate
            else:
                flush_current()
                current = unit

        for block in re.split(r"\n\s*\n", text):
            push_unit(block)
        flush_current()
        return pages or [text[:max_chars].rstrip()]

    @staticmethod
    def _split_oversized_unit(unit: str, max_chars: int) -> list[str]:
        sentences = re.findall(r".+?(?:[.!?…]+(?:\s+|$)|$)", unit, flags=re.S)
        parts: list[str] = []
        current = ""
        for sentence in sentences:
            sentence = sentence.strip()
            if not sentence:
                continue
            if len(sentence) > max_chars:
                if current.strip():
                    parts.append(current.strip())
                    current = ""
                words = sentence.split()
                chunk = ""
                for word in words:
                    candidate = f"{chunk} {word}".strip()
                    if len(candidate) <= max_chars:
                        chunk = candidate
                    else:
                        if chunk:
                            parts.append(chunk)
                        chunk = word[:max_chars]
                if chunk:
                    parts.append(chunk)
                continue
            candidate = f"{current} {sentence}".strip() if current else sentence
            if len(candidate) <= max_chars:
                current = candidate
            else:
                if current.strip():
                    parts.append(current.strip())
                current = sentence
        if current.strip():
            parts.append(current.strip())
        return parts

    async def _send_answer_embeds(
        self,
        interaction: discord.Interaction,
        *,
        title: str,
        answer: str,
        full_prompt: str,
    ) -> None:
        pages = self._split_answer_pages(answer, MAX_DISCORD_LEN)
        total = len(pages)
        footer_base = f"Then trả lời {interaction.user.display_name} · thấy chỗ nào cần chỉnh, bấm nút góp ý giúp Then nhé."
        for index, page in enumerate(pages, start=1):
            shown_title = f"{title} ({index}/{total})" if total > 1 else title
            embed = discord.Embed(title=shown_title, description=page, color=discord.Color.green())
            footer = f"{footer_base} · Phần {index}/{total}" if total > 1 else footer_base
            embed.set_footer(text=footer)
            view = FeedbackView(self.bot, full_prompt, answer) if index == 1 else None
            if index > 1:
                await asyncio.sleep(0.35)
            try:
                await interaction.followup.send(embed=embed, view=view)
                print(f"[debug] discord_answer_page_sent page={index}/{total} chars={len(page)} embed=True", flush=True)
            except Exception as exc:
                print(
                    f"[debug] discord_answer_page_embed_failed page={index}/{total} "
                    f"chars={len(page)} err={type(exc).__name__}: {exc}",
                    flush=True,
                )
                fallback_parts = self._split_answer_pages(page, 1800)
                for part_index, part in enumerate(fallback_parts, start=1):
                    fallback = part
                    if total > 1:
                        suffix = f" [{part_index}/{len(fallback_parts)}]" if len(fallback_parts) > 1 else ""
                        fallback = f"**{shown_title}{suffix}**\n\n{part}"
                    try:
                        await interaction.followup.send(content=fallback)
                        print(
                            f"[debug] discord_answer_page_sent page={index}/{total} "
                            f"fallback_part={part_index} chars={len(fallback)} embed=False",
                            flush=True,
                        )
                    except Exception as fallback_exc:
                        print(
                            f"[debug] discord_answer_page_fallback_failed page={index}/{total} "
                            f"part={part_index} err={type(fallback_exc).__name__}: {fallback_exc}",
                            flush=True,
                        )
                        break

    @staticmethod
    def _retrieval_count(context: str, marker: str) -> int:
        return len(re.findall(rf"^\[{re.escape(marker)}\d+\]", context or "", flags=re.M))

    @staticmethod
    def _insufficient_answer(answer: str) -> bool:
        lowered = AI._plain_text(answer or "")
        return "khong du du lieu de khang dinh" in lowered or "chua du du lieu de khang dinh" in lowered

    @staticmethod
    def _query_terms(query: str, limit: int = 16) -> list[str]:
        plain = AI._plain_text(query)
        return [t for t in re.findall(r"[a-z0-9]{3,}", plain)[:limit]]

    @classmethod
    def _important_query_terms(cls, query: str, limit: int = 10) -> list[str]:
        stop = {
            "hay", "theo", "tai", "lieu", "nap", "cho", "biet", "la", "gi", "ve", "cua", "mot", "cac",
            "nhung", "moi", "can", "dung", "trong", "duoc", "voi", "neu", "hoi", "van", "chuong",
            "nhan", "dinh", "tong", "hop", "trich", "dan", "nguyen", "van", "chep",
        }
        terms = []
        for term in cls._query_terms(query, 32):
            if term not in stop and term not in terms:
                terms.append(term)
        return terms[:limit]

    @classmethod
    def _request_profile(cls, query: str) -> dict:
        q = cls._plain_text(query)
        quote = any(marker in q for marker in (
            "chep nguyen van", "nguyen van", "dung tung chu", "trich dan", "trich nguyen", "chep lai",
        ))
        aggregate = any(marker in q for marker in (
            "tong hop", "tat ca", "moi nhan dinh", "toan bo", "liet ke", "gom lai", "he thong",
        ))
        document_only = any(marker in q for marker in (
            "theo tai lieu", "tai lieu da nap", "trong tai lieu", "kho pdf", "da nap",
            "chep nguyen van", "nguyen van", "trich dan",
        ))
        return {"quote": quote, "aggregate": aggregate, "document_only": document_only}

    # Cum tu mo dau cau hoi hay bi viet hoa -> KHONG phai ten tac gia/tac pham.
    _SUBJECT_STOPWORDS = {
        "phan tich", "suy nghi", "cam nhan", "cam nghi", "binh giang", "binh luan",
        "chung minh", "lam sang to", "lam ro", "phong cach", "gia tri", "y nghia",
        "nghi luan", "van hoc", "cau hoi", "yeu cau", "nhan xet", "danh gia",
        "so sanh", "lien he", "ban ve", "the nao", "vi sao", "tai sao",
        "hinh tuong", "nhan vat", "chi tiet", "tinh huong", "doan tho", "bai tho",
        "kho tho", "doan trich", "truyen ngan", "tac pham", "tac gia", "nha tho",
        "nha van", "quan niem", "viet nam", "ha noi", "sai gon", "cach mang",
    }
    # Chuoi 2-4 am tiet cung viet hoa kieu Viet ("Nguyen Binh", "Nguyen Huy Thiep",
    # "Vo Nhat") -> ung vien ten rieng.
    _NAME_SEQ_RE = re.compile(
        r"[A-ZÀ-ỸĐ][a-zà-ỹđ]+(?:\s+[A-ZÀ-ỸĐ][a-zà-ỹđ]+){1,3}"
    )

    @classmethod
    def _query_subjects(cls, query: str, plan) -> list[str]:
        """Tac gia + ten tac pham -> chu de bat buoc cua cau hoi. Lay tu (1) author_filter,
        (2) chuoi trong ngoac kep, (3) chuoi ten rieng viet hoa (vd 'phong cach tho Nguyen
        Binh' -> 'Nguyen Binh') de bat ca khi cau hoi khong dung 'cua'/'tac gia'."""
        subjects: list[str] = []
        if getattr(plan, "author_filter", ""):
            subjects.append(cls._plain_text(plan.author_filter))
        for m in re.findall(r"[\"'“”‘’«»]([^\"'“”‘’«»]{2,60})[\"'“”‘’«»]", query or ""):
            t = cls._plain_text(m).strip()
            if len(t) >= 3:
                subjects.append(t)
        for m in cls._NAME_SEQ_RE.findall(query or ""):
            t = cls._plain_text(m).strip()
            words = t.split()
            # Bo cum mo dau cau hoi bi viet hoa (vd "Phan Tich", "Phong Cach").
            if not words or t in cls._SUBJECT_STOPWORDS or " ".join(words[:2]) in cls._SUBJECT_STOPWORDS:
                continue
            if len(t) >= 3:
                subjects.append(t)
        # Loai trung, giu thu tu.
        seen: set[str] = set()
        uniq: list[str] = []
        for s in subjects:
            if s and s not in seen:
                seen.add(s)
                uniq.append(s)
        return uniq

    @classmethod
    def _text_mentions_subject(cls, subjects: list[str], text: str) -> bool:
        """True neu text co nhac toi it nhat mot chu de (ten tac pham/tac gia hoac ho tac gia)."""
        if not subjects:
            return True  # khong ro chu de -> khong phan xet
        haystack = cls._plain_text(text or "")
        if not haystack.strip():
            return False
        for subj in subjects:
            if subj in haystack:
                return True
            last = subj.split()[-1] if subj.split() else ""
            if len(last) >= 4 and re.search(r"\b" + re.escape(last) + r"\b", haystack):
                return True
        return False

    @classmethod
    def _context_off_subject(cls, query: str, plan, pdf_meta: dict) -> bool:
        """True khi cau hoi neu ro tac gia/tac pham NHUNG cac doan truy xuat khong he
        nhac toi chung -> kho tra ve tai lieu LAC tac pham (vd hoi Tuong Ve Huu ma tra
        ve Chi Pheo). Chan de khong nhoi noi dung sai vao bai."""
        subjects = cls._query_subjects(query, plan)
        if not subjects:
            return False
        chunks = pdf_meta.get("chunks") or []
        if not chunks:
            return False
        haystack = " ".join(
            (c.get("title") or "") + " " + (c.get("first_500") or "") + " " + (c.get("excerpt") or "")
            for c in chunks
        )
        return not cls._text_mentions_subject(subjects, haystack)

    @classmethod
    def _retrieval_hit(cls, query: str, pdf_meta: dict) -> bool:
        terms = cls._query_terms(query)
        if not terms:
            return bool(pdf_meta.get("selected_count"))
        for chunk in (pdf_meta.get("chunks") or []):
            if chunk.get("matched_phrases"):
                return True
            matched = set(chunk.get("matched_keywords") or [])
            coverage = len(matched) / max(1, len(terms))
            important_terms = {term for term in terms if len(term) >= 4}
            if coverage >= 0.65 and (not important_terms or len(matched & important_terms) >= max(1, len(important_terms) // 2)):
                return True
        haystack = cls._plain_text(" ".join(
            (chunk.get("first_500") or "") + " " + (chunk.get("excerpt") or "")
            for chunk in (pdf_meta.get("chunks") or [])
        ))
        return len([term for term in terms if term in haystack]) / max(1, len(terms)) >= 0.75

    @staticmethod
    def _log_top_pdf_chunks(pdf_meta: dict) -> None:
        for chunk in (pdf_meta.get("chunks") or [])[:5]:
            preview = re.sub(r"\s+", " ", chunk.get("first_500") or chunk.get("excerpt", "")).strip()[:500]
            print(
                "[debug] top_pdf_chunk "
                f"id=P{chunk.get('index')} score={chunk.get('score')} rank={chunk.get('rank')} "
                f"kw={chunk.get('keyword_score')} phrase={chunk.get('phrase_score')} coverage={chunk.get('coverage')} "
                f"matched_phrases={chunk.get('matched_phrases')} missing_keywords={chunk.get('missing_keywords')} "
                f"title={chunk.get('title')!r} chunk_index={chunk.get('chunk_index')} first500={preview!r}",
                flush=True,
            )

    @staticmethod
    def _reason_code(pdf_meta: dict, manual_count: int, feedback_count: int, web_count: int, verifier_changed: bool = False) -> str:
        if verifier_changed:
            return "VERIFIER_REJECTED"
        if not (pdf_meta.get("selected_count") or manual_count or feedback_count or web_count):
            return "NO_RETRIEVAL"
        if not (pdf_meta.get("context") or manual_count or feedback_count or web_count):
            return "EMPTY_CONTEXT"
        if pdf_meta.get("error"):
            return "OCR_FAILURE"
        if pdf_meta.get("candidate_count", 0) > 0 and pdf_meta.get("selected_count", 0) == 0:
            return "RERANK_REJECTED"
        if pdf_meta.get("selected_count") and float(pdf_meta.get("top_score") or 0) < LOW_RETRIEVAL_SCORE:
            return "LOW_RETRIEVAL_SCORE"
        return "UNKNOWN"

    @staticmethod
    def _has_strong_evidence(pdf_meta: dict, manual_count: int, feedback_count: int, web_count: int) -> bool:
        if manual_count or feedback_count or web_count:
            return True
        return bool(pdf_meta.get("selected_count")) and float(pdf_meta.get("top_score") or 0) >= LOW_RETRIEVAL_SCORE


    def _is_admin(self, interaction: discord.Interaction) -> bool:
        if not isinstance(interaction.user, discord.Member):
            return False
        role_name = os.getenv("HVHN_ADMIN_ROLE", "HVHN Admin").strip()
        return any(role.name == role_name for role in interaction.user.roles) or interaction.user.guild_permissions.manage_guild

    async def _embed_query(self, query: str):
        # Nhung cau hoi de tra cuu ngu nghia. Loi/thieu key -> None (lui ve tu khoa).
        if not md_embeddings.has_keys():
            return None
        try:
            return await md_embeddings.embed_query(query)
        except Exception as exc:
            print(f"[ai] embed_query_error {exc}", flush=True)
            return None

    async def _pdf_knowledge_context(self, query: str) -> str:
        try:
            qvec = await self._embed_query(query)
            result = await retrieve_md_knowledge(self.bot.db, query, limit=5, query_vector=qvec)
            return result.get("context", "")
        except Exception:
            return ""

    async def _pdf_retrieval(self, query: str, *, limit: int = PDF_DEFAULT_LIMIT) -> dict:
        try:
            qvec = await self._embed_query(query)
            return await retrieve_md_knowledge(self.bot.db, query, limit=limit, query_vector=qvec)
        except Exception as exc:
            print(f"[ai] md_retrieval_error {exc}", flush=True)
            return {"context": "", "chunks": [], "quotes": [], "selected_count": 0, "candidate_count": 0, "top_score": 0}

    async def _embed_fn(self, texts):
        return await md_embeddings.embed_texts(texts, task_type="RETRIEVAL_DOCUMENT")

    def _start_embed_backfill(self) -> bool:
        # Job nen co nhip, chi 1 lan chay dong thoi. Tra True neu vua khoi dong.
        if getattr(self, "_embed_running", False) or not md_embeddings.has_keys():
            return False
        self._embed_running = True

        async def _bg():
            try:
                res = await backfill_embeddings(
                    self.bot.db,
                    self._embed_fn,
                    batch=30,
                    pace_seconds=md_embeddings.backfill_pace_seconds(),
                )
                print(f"[ai] embed_backfill embedded={res.get('embedded')} ok={res.get('ok')} err={res.get('error')}", flush=True)
            except Exception as exc:
                print(f"[ai] embed_backfill_error {exc}", flush=True)
            finally:
                self._embed_running = False

        asyncio.create_task(_bg())
        return True

    @commands.Cog.listener()
    async def on_ready(self):
        if getattr(self, "_embed_started", False) or not md_embeddings.has_keys():
            return
        self._embed_started = True
        self._start_embed_backfill()

    @app_commands.command(name="hvhn_embed_backfill",
                          description="(admin) Nhúng embedding cho tài liệu .md để bot tra cứu theo ngữ nghĩa")
    async def hvhn_embed_backfill(self, interaction: discord.Interaction):
        if not self._is_admin(interaction):
            await interaction.response.send_message("Chỉ admin dùng được lệnh này.", ephemeral=True)
            return
        if not md_embeddings.has_keys():
            await interaction.response.send_message(
                "Chưa cấu hình JINA_API_KEYS, VOYAGE_API_KEYS hoặc GEMINI_API_KEYS nên không nhúng được.",
                ephemeral=True,
            )
            return
        await interaction.response.defer(ephemeral=True, thinking=True)
        remaining = await count_missing_embeddings(self.bot.db)
        if remaining == 0:
            await interaction.followup.send("Tất cả tài liệu đã được nhúng embedding. Không còn gì để làm.", ephemeral=True)
            return
        probe = await md_embeddings.probe()
        if not probe.startswith("OK"):
            await interaction.followup.send(
                f"API embedding lỗi: `{probe}`\nCòn {remaining} đoạn chưa nhúng.", ephemeral=True)
            return
        running = self._start_embed_backfill()
        note = "Đã khởi động nhúng nền." if running else "Đang nhúng nền (job trước còn chạy)."
        await interaction.followup.send(
            f"{note} Còn ~{remaining} đoạn, chạy dần để né giới hạn quota (~100/phút). "
            f"Vài phút nữa hỏi lại là có tra cứu ngữ nghĩa. Bấm lại lệnh để xem còn bao nhiêu.",
            ephemeral=True)

    async def _knowledge_context(self, query: str, limit: int = 6) -> str:
        terms = expand_query_terms(query)[:24]
        if not terms:
            rows = await self.bot.db.fetch(
                "SELECT category, title, content FROM ai_knowledge WHERE approved = TRUE ORDER BY created_at DESC LIMIT $1",
                limit,
            )
        else:
            patterns = [f"%{term}%" for term in terms]
            try:
                rows = await self.bot.db.fetch(
                    """
                    WITH q AS (SELECT websearch_to_tsquery('simple', $1) AS query)
                    SELECT category, title, content,
                           ts_rank_cd(
                             to_tsvector('simple', coalesce(category, '') || ' ' || coalesce(title, '') || ' ' || coalesce(content, '')),
                             q.query
                           ) AS rank
                    FROM ai_knowledge, q
                    WHERE approved = TRUE
                      AND (
                        to_tsvector('simple', coalesce(category, '') || ' ' || coalesce(title, '') || ' ' || coalesce(content, '')) @@ q.query
                        OR lower(title) LIKE ANY($2::text[])
                        OR lower(content) LIKE ANY($2::text[])
                        OR lower(category) LIKE ANY($2::text[])
                      )
                    ORDER BY rank DESC
                    LIMIT $3
                    """,
                    " ".join(terms),
                    patterns,
                    limit,
                )
            except Exception as exc:
                print(f"[ai] manual knowledge FTS fallback: {exc}", flush=True)
                rows = await self.bot.db.fetch(
                    """
                    SELECT category, title, content, 0::float AS rank
                    FROM ai_knowledge
                    WHERE approved = TRUE
                      AND (
                        lower(title) LIKE ANY($1::text[])
                        OR lower(content) LIKE ANY($1::text[])
                        OR lower(category) LIKE ANY($1::text[])
                      )
                    LIMIT $2
                    """,
                    patterns,
                    limit,
                )
        if not rows:
            return ""

        chunks = []
        for index, row in enumerate(rows, start=1):
            content = row["content"]
            if len(content) > 900:
                content = content[:900] + "..."
            chunks.append(f"[S{index}] [{row['category']}] {row['title']}\n{content}")
        return "\n\n".join(chunks)

    async def _feedback_context(self, query: str, limit: int = 3) -> str:
        terms = [t.lower() for t in re.findall(r"[\w?-?A-Za-z0-9]{3,}", query, flags=re.UNICODE)][:8]
        if not terms:
            return ""
        patterns = [f"%{term}%" for term in terms]
        rows = await self.bot.db.fetch(
            """
            SELECT prompt, correction
            FROM ai_feedback
            WHERE rating = 'needs_fix'
              AND correction IS NOT NULL
              AND approved = TRUE
              AND (lower(prompt) LIKE ANY($1::text[]) OR lower(correction) LIKE ANY($1::text[]))
            ORDER BY id DESC
            LIMIT $2
            """,
            patterns,
            limit,
        )
        if not rows:
            return ""
        blocks = []
        total = 0
        for i, row in enumerate(rows[:3], 1):
            remaining = max(0, 1000 - total)
            if remaining <= 80:
                break
            correction = _clip_text(str(row["correction"]), min(remaining, 320))
            block = f"[F{i}] Loi giao vien da sua:\n{correction}"
            blocks.append(block)
            total += len(block) + 2
        context = "\n\n".join(blocks)
        print(
            f"[debug] feedback_context count={len(blocks)} chars={len(context)} preview={context[:500]!r}",
            flush=True,
        )
        return context


    @staticmethod
    def _clean_text(text: str) -> str:
        text = unescape(text or "")
        text = re.sub(r"<[^>]+>", " ", text)
        text = re.sub(r"\s+", " ", text)
        return text.strip()

    @staticmethod
    def _source_score(url: str) -> int:
        lowered = url.lower()
        return sum(1 for hint in TRUSTED_SOURCE_HINTS if hint in lowered)

    @staticmethod
    def _unwrap_ddg_url(url: str) -> str:
        parsed = urlparse(unescape(url))
        if parsed.netloc.endswith("duckduckgo.com") and parsed.path.startswith("/l/"):
            target = parse_qs(parsed.query).get("uddg", [""])[0]
            if target:
                return unquote(target)
        return unescape(url)

    async def _search_serper(self, session: aiohttp.ClientSession, query: str) -> list[dict[str, str]]:
        if not self.serper_key:
            return []
        headers = {"X-API-KEY": self.serper_key, "Content-Type": "application/json"}
        payload = {"q": query, "gl": "vn", "hl": "vi", "num": WEB_RESULT_LIMIT}
        async with session.post("https://google.serper.dev/search", headers=headers, json=payload, timeout=12) as resp:
            if resp.status != 200:
                return []
            data = await resp.json()
        results = []
        for item in data.get("organic", [])[:WEB_RESULT_LIMIT]:
            link = item.get("link") or ""
            title = self._clean_text(item.get("title") or "")
            snippet = self._clean_text(item.get("snippet") or "")
            if link and title:
                results.append({"title": title, "url": link, "snippet": snippet})
        return results

    async def _search_tavily(self, session: aiohttp.ClientSession, query: str) -> list[dict[str, str]]:
        if not self.tavily_key:
            return []
        payload = {
            "api_key": self.tavily_key,
            "query": query,
            "search_depth": "basic",
            "max_results": WEB_RESULT_LIMIT,
            "include_answer": False,
        }
        async with session.post("https://api.tavily.com/search", json=payload, timeout=15) as resp:
            if resp.status != 200:
                return []
            data = await resp.json()
        results = []
        for item in data.get("results", [])[:WEB_RESULT_LIMIT]:
            link = item.get("url") or ""
            title = self._clean_text(item.get("title") or "")
            snippet = self._clean_text(item.get("content") or "")
            if link and title:
                results.append({"title": title, "url": link, "snippet": snippet[:450]})
        return results

    async def _search_duckduckgo(self, session: aiohttp.ClientSession, query: str) -> list[dict[str, str]]:
        params = {"q": query, "kl": "vn-vi"}
        headers = {"User-Agent": "Mozilla/5.0"}
        async with session.get("https://duckduckgo.com/html/", params=params, headers=headers, timeout=15) as resp:
            if resp.status != 200:
                return []
            html = await resp.text()

        results = []
        pattern = re.compile(
            r'<a[^>]+class="result__a"[^>]+href="(?P<url>[^"]+)"[^>]*>(?P<title>.*?)</a>.*?'
            r'<a[^>]+class="result__snippet"[^>]*>(?P<snippet>.*?)</a>',
            re.S,
        )
        for match in pattern.finditer(html):
            url = self._unwrap_ddg_url(match.group("url"))
            title = self._clean_text(match.group("title"))
            snippet = self._clean_text(match.group("snippet"))
            if url and title:
                results.append({"title": title, "url": url, "snippet": snippet})
            if len(results) >= WEB_RESULT_LIMIT:
                break
        return results

    @staticmethod
    def _plain_text(value: str) -> str:
        value = unicodedata.normalize("NFD", value or "")
        value = "".join(ch for ch in value if unicodedata.category(ch) != "Mn").lower()
        return value.replace("đ", "d")

    @staticmethod
    def _needs_web(query: str, mode: str, has_local_context: bool) -> bool:
        q = AI._plain_text(query)
        if mode == "user_text_only":
            return False
        current_markers = ("moi nhat", "hien nay", "hom nay", "2025", "2026", "tin", "luat", "diem chuan", "lich", "gia", "su kien")
        source_markers = ("dan nguon", "nguon", "kiem chung", "tra cuu", "ai la", "khi nao", "o dau")
        if any(marker in q for marker in current_markers + source_markers):
            return True
        return not has_local_context and len(q.split()) >= 6


    async def _web_context(self, query: str, mode: str, has_local_context: bool = False) -> str:
        if not self._needs_web(query, mode, has_local_context):
            print(f"[ai] web=skip mode={mode} local={has_local_context}", flush=True)
            return ""

        async with aiohttp.ClientSession() as session:
            try:
                results = []
                results.extend(await self._search_serper(session, query))
                results.extend(await self._search_tavily(session, query))
                if not results:
                    results = await self._search_duckduckgo(session, query)
            except Exception as exc:
                print(f"[ai] Web search exception: {exc}", flush=True)
                return ""

        deduped = {}
        for item in results:
            deduped.setdefault(item["url"], item)
        results = list(deduped.values())
        print(f"[ai] web_results={len(results[:WEB_CONTEXT_LIMIT])}", flush=True)

        chunks = []
        for index, item in enumerate(results[:WEB_CONTEXT_LIMIT], start=1):
            snippet = item["snippet"][:500]
            trust = "nguon dang tin hon" if self._source_score(item["url"]) else "can kiem chung"
            chunks.append(f"[W{index}] {item['title']}\nURL: {item['url']}\nDo tin cay: {trust}\nTom tat: {snippet}")
        return "\n\n".join(chunks)


    @staticmethod
    def _guarded_prompt(prompt: str, knowledge: str, web_context: str, mode: str, guidance: str = "") -> str:
        source_block = knowledge or "KHONG CO KHO TRI THUC HVHN PHU HOP DUOC NAP."
        web_block = web_context or "KHONG CO NGUON WEB DUOC TRUY XUAT."
        return (
            "Ban la Then, tro giang AI mon Ngu van cua HVHN. Luon tra loi bang tieng Viet co dau, tru khi nguoi dung yeu cau ngon ngu khac.\n"
            f"CHE DO: {mode}\n"
            + (f"{guidance}\n" if guidance else "")
            + "KHO TRI THUC/FEEDBACK HVHN DA TRUY XUAT:\n"
            f"{source_block}\n\n"
            "NGUON WEB DA TRA CUU (neu co):\n"
            f"{web_block}\n\n"
            "QUY TAC BAT BUOC:\n"
            "- Khong bia tac gia, tac pham, nhan vat, nam thang, hoan canh sang tac, trich dan, nhan dinh phe binh.\n"
            "- Neu KHO TRI THUC co noi dung lien quan, chi duoc tra loi tu KHO TRI THUC do; khong dung tri nho ngoai.\n"
            "- Neu nguoi dung hoi 'chep nguyen van', 'trich dan', 'nguyen van', phai giu dung tung chu tu context; khong dien giai/paraphrase.\n"
            "- Moi cau tho/cau van dat trong ngoac kep dai hon mot cum tu phai xuat hien NGUYEN VAN trong context/evidence va dung tac gia/tac pham dang hoi. Neu khong thay, bo quote do hoac noi chua du du lieu; khong duoc lay tho nguoi khac gan cho tac gia dang hoi.\n"
            "- Neu nguoi dung hoi 'tong hop', 'tat ca', 'moi nhan dinh', phai di qua tat ca doan [P...] duoc cap va rut ra moi y/trich dan lien quan; khong dung sau 1 doan.\n"
            "- Voi cau hoi theo tai lieu da nap, neu context co evidence thi khong duoc tra loi bang kien thuc chung hay tom tat chung chung.\n"
            "- Chi dat trong ngoac kep neu thay nguyen van trong van ban/context.\n"
            "- Neu context khong du de khang dinh, phai noi ro: chua du du lieu de khang dinh.\n"
            "- Neu KHO TRI THUC co bang chung lien quan, bat buoc tra loi dua tren bang chung do; khong duoc tu choi chung chung.\n"
            "- Duoc neu ghi chu nguon ngan gon khi cau tra loi mang tinh su kien/van hoc/can kiem chung.\n"
            "- Khong hien ma noi bo [P1], [S1], [W1] hoac URL dai; neu can, chi neu ten tai lieu/nguon ngan gon.\n"
            "- Tra loi thang vao cau hoi, sau do moi ghi can cu/nguon neu that su can.\n"
            "- Khong dung web neu kho HVHN da du; web chi bo sung thong tin thoi su/kiem chung.\n\n"
            "CHUAN CHAT LUONG HVHN:\n"
            "- Moi luan diem van hoc phai neo vao chi tiet van ban, hinh tuong, nhan vat, tinh huong, giong dieu, ket cau hoac bieu tuong cu the.\n"
            "- Cam cau rong neu khong co phan tich rieng: 'thong diep sau sac', 'gia tri y nghia', 'ngon ngu giau hinh anh', 'the hien su sang tao phong phu'.\n"
            "- Khong noi 'tac gia muon nhan manh', 'duoc viet dua tren trai nghiem cua tac gia', 'hoan canh sang tac' neu context khong cap bang chung.\n"
            "- Voi cau hoi so sanh: moi truc phai co A -> B -> diem gap/lech; khong gom hai tac pham vao mot nhan xet chung.\n"
            "- Voi cau hoi ve phong cach tac gia qua mot bai tho: phai neu mot luan de phong cach ro rang, roi phan tich 2-3 net dac sac qua tu ngu, hinh anh, nhip dieu, cai toi tru tinh, cam giac/thoi gian/khong gian. Khong chi liet ke 'lang man, tinh te, sau sac'.\n"
            "- Neu goi ten bien phap tu tu (so sanh/an du/diep ngu...), phai chi ra dau hieu ngon ngu cu the. Khong duoc goi la 'so sanh' khi cau dan khong co phe so sanh.\n"
            "- Van phong phan tich van hoc phai co chat van: mo bang mot truc tu tuong/hinh anh trung tam; dung dong tu co luc nhu 'bung len', 'ro ri', 'ket tinh', 'va cham', 'keo cang', 'chuyen hoa'; cau van co nhip ngan-dai dan xen. Tuyet doi khong viet nhu bao cao muc 'Ve noi dung/ve nghe thuat/tong ket'.\n"
            "- Hinh anh hoa lap luan nhung khong bay khoi evidence: moi an du/so sanh trong loi binh phai neo vao chi tiet van ban dang phan tich.\n"
            "- Truoc khi chot, tu kiem: co dan chung cu the cho tung tac pham chua, co suy doan ngoai context khong, co cau nao co the gan cho moi tac pham khong.\n"
            "- DO SAU & DO DAI (voi cau hoi phan tich/cam nhan/phong cach): trien khai IT NHAT 3-4 luan diem, moi luan diem la mot doan day du theo 4 tang: (a) goi ten thu phap/nhan tu cu the -> (b) trich NGUYEN VAN dan chung, GIU nguyen diep tu/diep ngu ('va... va... va', 'nay day... nay day', 'cho... cho...'), khong rut gon/dien xuoi tho -> (c) phan tich VI SAO thu phap ay tao ra hieu qua ay (co che ngon ngu, khong noi chung 'the hien su phong phu') -> (d) khai quat len tu tuong/phong cach. Bai phai du day dan, co chieu sau, KHONG duoc chi 3-4 doan ngan hoi hot.\n"
            "- CHONG DON THO: khong dan khoi trich qua 3 dong lien; trich 1-3 cau roi phan tich NGAY nhan tu cua doan do (chu nao dat nhat, vi sao), phan tich phai DAI hon phan trich; sau do moi trich tiep. Trich 10 cau roi binh 1 cau chung chung la bai hong.\n"
            "- CHONG VAN AI: han che toi da danh hoa 'su ...', 'viec ...' ('the hien su mong muon' -> 'cho thay ong khat khao'); dung dong tu manh, hinh anh cu the thay cho danh tu truu tuong.\n"
            "- CHONG LAP & CHONG CUT: khong lap lai cung mot cum khai quat (vd 'quan niem ve thoi gian va tuoi tre') qua mot lan; ket bai khong duoc tom lai y het than bai bang tu khac; moi doan phai them thong tin moi.\n\n"
            "YEU CAU NGUOI DUNG:\n"
            f"{prompt}"
        )


    @staticmethod
    def _has_grounding_footer(answer: str) -> bool:
        lowered = answer.lower()
        return (
            "tài liệu tham khảo" in lowered
            or "tai lieu tham khao" in lowered
            or "nguồn:" in lowered
            or "nguon:" in lowered
            or "chưa đủ dữ liệu" in lowered
            or "chua du du lieu" in lowered
        )

    @staticmethod
    def _looks_like_source_dump(answer: str) -> bool:
        lowered = answer.lower()
        source_dump_phrases = (
            "tham khảo các nguồn",
            "tham khảo nguồn",
            "các nguồn thông tin sau",
            "danh sách nguồn",
            "sources",
        )
        has_dump_intro = any(phrase in lowered[:350] for phrase in source_dump_phrases)
        has_many_source_bullets = len(re.findall(r"^\s*[-•]\s+.*\[(?:w|W)\d+\]", answer, re.M)) >= 3
        return has_dump_intro or has_many_source_bullets

    @staticmethod
    def _looks_like_generic_literary_answer(answer: str) -> bool:
        plain = AI._plain_text(answer or "")
        if len(plain) < 250:
            return False
        generic_phrases = (
            "thong diep sau sac",
            "gia tri va y nghia",
            "gia tri y nghia",
            "ngon ngu giau hinh anh",
            "su sang tao phong phu",
            "ve cuoc song con nguoi",
            "moi quan he giua con nguoi voi thien nhien",
            "tac gia muon nhan manh",
            "dua tren nhung trai nghiem",
        )
        hits = sum(1 for phrase in generic_phrases if phrase in plain)
        if hits < 2:
            return False
        evidence_markers = (
            "nhan vat", "hinh tuong", "tinh huong", "chi tiet", "bieu tuong", "giong dieu",
            "ket cau", "santiago", "ca kiem", "bien ca", "dan ca map", "di san", "rung",
        )
        marker_hits = sum(1 for marker in evidence_markers if marker in plain)
        return marker_hits < 3

    @staticmethod
    def _looks_like_weak_style_analysis(answer: str) -> bool:
        plain = AI._plain_text(answer or "")
        if len(plain) < 300:
            return False
        if "phong cach" not in plain:
            return False
        weak_labels = (
            "lang man tinh te va sau sac",
            "lang man, tinh te va sau sac",
            "ngon ngu tho giau hinh anh va am thanh",
            "bien phap tu tu tinh te",
            "cau truc tho linh hoat",
            "khong gian tho rong lon va sau sac",
            "tao ra nhung hinh anh dep",
            "am thanh em ai",
            "cau truc tho khong deu",
        )
        weak_hits = sum(1 for phrase in weak_labels if phrase in plain)
        if weak_hits >= 2:
            return True
        wrong_device_patterns = (
            "nhung so sanh nay giup",
            "nhung bien phap tu tu nay giup tao ra mot khong gian tho rong lon",
            # "nay day... nay day" la diep ngu/liet ke, khong phai doi xung — loi goi sai thu phap hay gap.
            "bien phap doi xung",
            "phep doi xung",
        )
        if any(pattern in plain for pattern in wrong_device_patterns):
            return True
        style_operations = (
            "cai toi", "cam giac", "nhip dieu", "thoi gian", "khong gian", "tu ngu",
            "hinh anh", "giong dieu", "nhan vat tru tinh", "chu the tru tinh",
        )
        return weak_hits >= 1 and sum(1 for op in style_operations if op in plain) < 3

    @staticmethod
    def _has_unverified_long_quotes(answer: str, evidence: str) -> bool:
        evidence_plain = AI._plain_text(evidence or "")
        for quote in QuoteExtractor.quoted_units(answer or ""):
            quote_plain = AI._plain_text(quote)
            # Short quoted titles/terms are allowed; long quoted units are treated as verbatim evidence.
            if len(quote_plain) < 24:
                continue
            if quote_plain not in evidence_plain:
                return True
        return False

    @staticmethod
    def _looks_like_dry_literary_style(answer: str) -> bool:
        plain = AI._plain_text(answer or "")
        if len(plain) < 350:
            return False
        if not any(term in plain for term in ("bai tho", "tac pham", "phong cach", "hinh tuong", "nhan vat")):
            return False
        dry_markers = (
            "ve noi dung",
            "ve nghe thuat",
            "tong ket",
            "tong quan",
            "duoc the hien qua",
            "tao ra mot",
            "giup tao ra",
            "rat giau hinh anh",
            "rat sau sac",
            "co gia tri",
            "tho mong va bay bong",
            "tao nen mot",
            "day la mot cach the hien",
            "muon gui den nguoi doc thong diep",
        )
        dry_hits = sum(1 for marker in dry_markers if marker in plain)
        vivid_markers = (
            "bung", "ro ri", "ket tinh", "va cham", "keo cang", "chuyen hoa",
            "nhip dap", "mach ngam", "du am", "am anh", "khac khoai", "cuong nhiet",
            "mong manh", "ran nut", "thao thuc", "tram tich",
        )
        vivid_hits = sum(1 for marker in vivid_markers if marker in plain)
        return dry_hits >= 3 and vivid_hits < 2

    @staticmethod
    def _repeated_phrase_defects(answer: str) -> list[str]:
        """Bat cac cau/cum bi lap gan nguyen van trong cau tra loi (loi 'dan cung mot ket luan
        sau moi dan chung' + 'ket bai chep lai mo bai'). Tra ve danh sach cum bi lap de nhet
        vao repair prompt cho model biet dich danh phai viet lai cho nao."""
        plain = AI._plain_text(answer or "")
        if len(plain) < 300:
            return []
        # Bo phan trich dan (tho lap "nay day..." la co y cua tac gia, khong phai loi cua bot).
        # Dung QuoteExtractor de ghep cap ngoac dung; regex don gian se coi dau dong " nhu dau mo
        # moi va nuot luon van xuoi giua hai trich dan.
        without_quotes = answer
        for span in sorted(QuoteExtractor.quote_spans(answer), key=lambda s: s.start, reverse=True):
            without_quotes = without_quotes[:span.start] + " " + without_quotes[span.end:]
        sentences = [s.strip() for s in re.split(r"[.!?\n]+", without_quotes) if len(s.strip()) >= 25]
        norm = [re.sub(r"\s+", " ", AI._plain_text(s)) for s in sentences]
        defects: list[str] = []
        seen: set[str] = set()
        # 1) Cau gan trung nhau: so shingle 8-tu giua moi cap cau.
        def shingles(s: str) -> set[str]:
            words = s.split()
            return {" ".join(words[i:i + 8]) for i in range(len(words) - 7)}
        shingle_sets = [shingles(s) for s in norm]
        for i in range(len(norm)):
            if not shingle_sets[i]:
                continue
            for j in range(i + 1, len(norm)):
                common = shingle_sets[i] & shingle_sets[j]
                if common:
                    key = min(common)
                    if key not in seen:
                        seen.add(key)
                        defects.append(sentences[i][:160])
                    break
        return defects[:5]

    @staticmethod
    def _strip_repeated_sentences(answer: str) -> str:
        """Fallback khi repair LLM khong chay duoc (429/hết quota): cat co hoc cac cau
        lap gan nguyen van (giu lan xuat hien dau, bo cac lan sau). Khong dung vao trich dan."""
        quote_ranges = [(s.start, s.end) for s in QuoteExtractor.quote_spans(answer)]

        def in_quote(a: int, b: int) -> bool:
            return any(a < qe and b > qs for qs, qe in quote_ranges)

        def shingles(s: str) -> set[str]:
            words = s.split()
            return {" ".join(words[i:i + 8]) for i in range(len(words) - 7)}

        seen: list[set[str]] = []
        out = []
        last = 0
        for m in re.finditer(r"[^.!?\n]+[.!?]?\s*", answer):
            seg = m.group(0)
            norm = re.sub(r"\s+", " ", AI._plain_text(seg)).strip()
            sh = shingles(norm)
            dup = bool(sh) and not in_quote(m.start(), m.end()) and any(sh & prev for prev in seen)
            if not dup:
                seen.append(sh)
                out.append(answer[last:m.start()])
                out.append(seg)
            last = m.end()
        out.append(answer[last:])
        cleaned = "".join(out)
        # don doan rong do bi cat
        cleaned = re.sub(r"\n{3,}", "\n\n", cleaned).strip()
        return cleaned if len(cleaned) >= 200 else answer

    @staticmethod
    def _ai_flavored_style_defects(answer: str) -> list[str]:
        """Bat 'mau AI': lam dung danh hoa 'su .../viec ...' va goi sai thu phap,
        khong phu thuoc gate 'phong cach' cua weak_style."""
        plain = AI._plain_text(answer or "")
        if len(plain) < 300:
            return []
        defects: list[str] = []
        su_count = len(re.findall(r"\bsu [a-z]", plain)) + len(re.findall(r"\bviec [a-z]", plain))
        if su_count >= 6:
            defects.append(
                f"Lam dung danh hoa kieu AI ('su ...', 'viec ...') {su_count} lan. Viet lai bang dong tu/tinh tu truc tiep: "
                "'su khan truong' -> 'khan truong', 'the hien su mong muon' -> 'cho thay ong khat khao', "
                "'su tuong phan giua su vinh cuu va su ngan ngui' -> 'troi dat thi con mai, doi nguoi thi huu han'."
            )
        # Don tho thay phan tich: trich khoi dai roi phan mot cau chung chung.
        spans = QuoteExtractor.quote_spans(answer)
        quoted_chars = sum(s.end - s.start for s in spans)
        prose_chars = max(len(answer) - quoted_chars, 1)
        # quote_spans da collapse newline -> do bang do dai: ~200 chars ~ 4-5 dong tho.
        has_long_block = any(len(s.quote) >= 200 for s in spans)
        if has_long_block or quoted_chars / (quoted_chars + prose_chars) > 0.35:
            defects.append(
                "Trich dan chiem qua nhieu bai (don tho thay phan tich). Moi lan chi trich 1-3 cau, "
                "phan tich NGAY nhan tu cua doan vua trich (vd 'ngon' trong 'Thang gieng ngon nhu mot cap moi gan' "
                "— vi giac hoa mua xuan, lay con nguoi lam chuan cai dep; 'rom vi chia phoi' — thoi gian duoc nem "
                "bang vi giac), roi moi trich tiep. Phan phan tich phai DAI HON phan trich."
            )
        for wrong in ("bien phap doi xung", "phep doi xung"):
            if wrong in plain:
                defects.append(
                    "Goi sai thu phap 'doi xung'. Kiem tra dau hieu ngon ngu: lap tu dau cau la DIEP NGU/DIEP CAU TRUC; "
                    "hai ve trai nghia la TUONG PHAN/DOI LAP. Chi goi ten phep co dau hieu that trong dan chung."
                )
                break
        # Van kho khan kieu bao cao hoc thuat: dem thuat ngu bien khao cung do; >=3 la kho, thieu hoi tho.
        academic = (
            "co che bieu hien", "co che tha hoa", "mo xe truc dien", "vung tham my",
            "kien tao kieu nhan vat", "kien tao nen kieu", "pham tru", "binh dien",
            "the hien ro net qua thuc tien", "duoc the hien ro net", "chuyen hoa cac",
        )
        hits = [p for p in academic if p in plain]
        if len(hits) >= 3:
            defects.append(
                "Van kho khan, cung nhu bao cao bien khao (cac cum: " + ", ".join(hits) + "). Viet lai cho "
                "co hoi tho: nhu mot nguoi thay dang say sua giang, cau co nhip va cho nhan, co cam xuc that "
                "truoc cai hay cua van chuong, dung hinh anh song dong bam vao dan chung. Van GIU do sau va "
                "dan chung, chi bo lop vo thuat ngu cung do."
            )
        # Lo nguon noi bo / day di doc cho khac (bao X, toan van bai viet).
        if AI._SOURCE_REFERRAL.search(answer or ""):
            defects.append(
                "Lo ten nguon noi bo va day nguoi hoi di kiem chung/tra cuu toan van tren bao/trang khac. "
                "Bo han cau do; ket bai bang mot nhan dinh cua chinh minh, khong nhac ten bao/trang/tai lieu."
            )
        # ==== CHE DO 'THU THU': liet ke/xep hang/tom tat corpus thay vi TRA LOI cau hoi ====
        lib_hits = [p for p in AI._LIBRARIAN_PHRASES if p in plain]
        bracketless_p = bool(re.search(r"(?<![a-z])p\d+\s*,\s*p\d+", plain) or re.search(r"(?<![a-z])p\d+\s+va\s+p\d+", plain))
        if lib_hits or bracketless_p:
            defects.append(
                "SAI NGHIEM TRONG: dang o che do 'thu thu' — tom tat/xep hang cac doan tai lieu (P1, P2, "
                "'kho PDF/HVHN', 'nen uu tien su dung khi can dan chung') thay vi TRA LOI cau hoi. Vut bo hoan "
                "toan loi liet ke do. Viet lai thanh MOT bai phan tich hoan chinh tra loi DUNG chi tiet/tac pham "
                "duoc hoi, khong nhac P1/P2/kho PDF/tai lieu, khong ban ve 'nen dung doan nao'. Neu kho khong co "
                "du lieu ve tac pham dang hoi thi tu phan tich bang kien thuc van hoc cua chinh minh — TUYET DOI "
                "khong lap noi dung cua mot tac pham KHAC (vd dang hoi Tuong Ve Huu ma noi ve Chi Pheo)."
            )
        # ==== SIET GIONG CHU VAN SON: chi soi bai phan tich van hoc dai (>=1200 ky tu van xuoi) ====
        if len(plain) >= 1200:
            # (1) Dao to bua lon rong nghia — cam theo LUAT 15(d).
            grand = (
                "ket tinh toan bo", "tai nang nghe thuat bac thay", "tai nang bac thay", "chan ly nghe thuat",
                "cuu roi mot linh hon", "cuu roi linh hon", "gia tri nhan dao sau sac", "gia tri nhan van sau sac",
                "tuyet tac", "kiet tac", "dinh cao nghe thuat", "song mai voi thoi gian", "muon doi", "bat hu",
                "sa mac lanh leo", "vien ngoc sang", "buc tranh tuyet dep", "thang hoa cam xuc",
            )
            ghits = [p for p in grand if p in plain]
            if ghits:
                defects.append(
                    "Dao to bua lon rong nghia (cac cum: " + ", ".join(ghits) + "). Bo het. Moi khai quat lon PHAI "
                    "moc len tu mot chu/mot dan chung vua mo ra, khong phan tu tren troi. Thay 'ket tinh toan bo tu "
                    "tuong nhan dao' bang mot nhan xet cu the ve chinh chi tiet dang phan tich."
                )
            # (2) Tieu de tieu muc kieu bai van mau 'X — Y' (LUAT 15d).
            header_re = re.compile(r"^\s*[^\n]{4,70}\s+[—–-]\s+[A-ZÀ-ỹĐ][^\n]{4,}$", re.MULTILINE)
            heads = [h for h in header_re.findall(answer or "") if len(h) < 90]
            if len(heads) >= 2:
                defects.append(
                    "Bo cuc bai van mau: cac tieu de tieu muc kieu 'Bat chao hanh — Hien than cua...'. Chu Van Son "
                    "khong chia bai bang tieu de dat san; hay de mach van tu chay lien, moi doan mo bang mot chu/ "
                    "mot dan chung cu the roi dan len y, khong dat tieu de tong ket truoc."
                )
            # (3) Thieu chu ky Chu Van Son: khong cai 'toi' dan dat VA khong cau hoi tu tu (LUAT 15b,c).
            has_first_person = bool(re.search(r"\btoi (nghi|cho|thay|tin|ngo|do|muon|xin chia)\b|theo toi\b|\bta thu\b", plain))
            has_rhetoric = "?" in (answer or "")
            if not has_first_person and not has_rhetoric:
                defects.append(
                    "Thieu chu ky giong Chu Van Son: khong co cai 'toi' binh luan dan dat, cung khong mot cau hoi tu tu "
                    "nao. Them chinh kien that ('Toi nghi...', 'Khong han.') va it nhat mot cau hoi tu tu mo y roi tu "
                    "tra loi, va mot cau cuc ngan dan giong sau doan phan tich day."
                )
        return defects

    @staticmethod
    def _pdf_reference_lines(knowledge: str) -> list[tuple[str, str]]:
        if "PDF" not in knowledge and "pdf" not in knowledge:
            return []
        refs = []
        for line in knowledge.splitlines():
            match = re.match(r"^\[(\d+)\]\s+(.+\.pdf)\s*$", line.strip(), flags=re.I)
            if match:
                refs.append((match.group(1), match.group(2).strip()))
        return refs

    @classmethod
    def _ensure_pdf_references(cls, answer: str, knowledge: str) -> str:
        refs = cls._pdf_reference_lines(knowledge)
        if not refs:
            return answer

        lowered = answer.lower()
        used_numbers = set(re.findall(r"(?<![A-Za-z])\[(\d+)\]", answer))
        selected = [(num, title) for num, title in refs if used_numbers and num in used_numbers]
        if not selected:
            selected = refs[:3]

        missing_titles = [(num, title) for num, title in selected if title not in answer]
        if "tài liệu tham khảo" in lowered or "tai lieu tham khao" in lowered:
            if not missing_titles:
                return answer
            lines = ["", "TÀI LIỆU THAM KHẢO (liên quan):"]
            lines.extend(f"[{num}] {title}" for num, title in missing_titles)
            return answer.rstrip() + "\n".join(lines)

        lines = ["", "TÀI LIỆU THAM KHẢO (liên quan):"]
        lines.extend(f"[{num}] {title}" for num, title in selected)
        return answer.rstrip() + "\n".join(lines)

    async def _verify_answer(
        self,
        answer: str,
        prompt: str,
        knowledge: str,
        web_context: str,
        mode: str,
        *,
        retrieval_hit: bool = False,
    ) -> str:
        if not answer:
            return answer
        compact_evidence = build_context_budget(
            prompt,
            knowledge,
            "",
            web_context,
            VERIFIER_EVIDENCE_MAX_CHARS,
        )
        compact_answer = _clip_text(answer, 4000)
        verifier_prompt = (
            "Kiem chung cau tra loi sau bang dung context duoc cung cap. "
            "Hay giu cau dung, xoa hoac viet lai moi khang dinh khong du can cu thanh 'chua du du lieu de khang dinh'. "
            "Neu BANG CHUNG RUT GON co thong tin lien quan, khong duoc bien cau tra loi thanh tu choi chung chung; hay sua de tra loi bang evidence. "
            "Tuyet doi khong them tac gia/tac pham/nam/trich dan/nhan dinh moi. "
            "Dong thoi tu cham chat luong nhu giao vien HSG: neu cau tra loi chung chung, lap lai tu khoa, "
            "thieu chi tiet van ban cho tung tac pham, hoac co cau kieu 'thong diep sau sac/gia tri y nghia/ngon ngu giau hinh anh' "
            "ma khong phan tich rieng, hay viet lai thanh lap luan co dan chung cu the. "
            "Voi cau hoi phong cach tac gia qua mot bai tho, phai co luan de phong cach, phan tich tu ngu/hinh anh/nhip dieu/cai toi tru tinh; "
            "xoa cac nhan xet rong nhu 'lang man, tinh te, sau sac', 'bien phap tu tu tinh te', 'cau truc linh hoat' neu khong duoc chung minh. "
            "Neu cau tra loi goi ten phep so sanh/an du/diep ngu sai voi dan chung, hay sua ten thao tac hoac bo han. "
            "Neu van phong kho nhu bao cao ('ve noi dung/ve nghe thuat/tong ket', lap 'duoc the hien qua/tao ra'), "
            "hay viet lai giau hinh anh hon: mo bang truc tu tuong/hinh anh trung tam, dung dong tu co luc, cau ngan-dai co nhip, "
            "nhung moi hinh anh binh luan van phai bam sat evidence. "
            "Kiem tung cau dat trong ngoac kep: neu cau tho/cau van do khong xuat hien nguyen van trong BANG CHUNG RUT GON, "
            "hoac xuat hien nhung khong gan dung tac gia/tac pham ma cau hoi yeu cau, phai xoa quote va khong duoc phan tich nhu tho cua tac gia do. "
            "Voi cau hoi so sanh, moi truc phai co tac pham A, tac pham B, diem gap va diem lech. "
            "Khong hien ma noi bo [P1]/[S1]/[W1] hoac URL dai. "
            "CHI tra ve NOI DUNG cau tra loi da sua cho hoc sinh; TUYET DOI khong kem loi dan/nhan xet "
            "ve chinh cau tra loi (khong viet 'Duoi day la phien ban sua doi', 'Cau tra loi cua ban da tot', "
            "'Toi da giu nguyen/them...'). Tra lai ban da sua, tieng Viet.\n\n"
            f"CAU HOI/PROMPT:\n{prompt}\n\n"
            f"BANG CHUNG RUT GON:\n{compact_evidence or 'KHONG CO'}\n\n"
            f"CAU TRA LOI CAN KIEM:\n{compact_answer}"
        )
        if RETRIEVAL_DEBUG:
            print(f"[debug] verifier_prompt\n{verifier_prompt}", flush=True)
        verified = await self.generate(verifier_prompt, THEN_SYSTEM_PROMPT, temperature=0.0)
        if RETRIEVAL_DEBUG:
            print(f"[debug] verifier_output\n{verified}", flush=True)
        if verified:
            self._last_verifier_rejected = (not self._insufficient_answer(answer)) and self._insufficient_answer(verified)
            verifier_reason = "VERIFIER_REJECTED" if self._last_verifier_rejected else "OK"
            print(
                f"[debug] verifier_result mode={mode} rejected={self._last_verifier_rejected} "
                f"input_insufficient={self._insufficient_answer(answer)} output_insufficient={self._insufficient_answer(verified)} "
                f"retrieval_hit={retrieval_hit} verifier_reason={verifier_reason}",
                flush=True,
            )
            if retrieval_hit and self._insufficient_answer(verified):
                print("[debug] verifier_override=retrieval_hit_prevents_false_insufficient", flush=True)
                return answer
            # Verifier co the roi vao model yeu (fallback 8B) va nghien nat bai tot
            # thanh vai doan cut. Neu ban "da kiem" ngan hon han ban goc ma ban goc
            # khong co van de trich dan, giu ban goc.
            if (
                len(verified) < 0.6 * len(answer)
                and not self._insufficient_answer(answer)
                and not self._has_unverified_long_quotes(answer, compact_evidence)
            ):
                print(
                    f"[debug] verifier_override=rewrite_too_short kept_original "
                    f"original_chars={len(answer)} verified_chars={len(verified)}",
                    flush=True,
                )
                return answer
            return verified
        print(f"[debug] verifier_result mode={mode} skipped=True", flush=True)
        return answer

    async def _safe_generate(
        self,
        prompt: str,
        knowledge: str,
        web_context: str,
        mode: str,
        *,
        retrieval_hit: bool = False,
        guidance: str = "",
    ) -> tuple[str | None, str]:
        self._last_verifier_rejected = False
        full_prompt = self._guarded_prompt(prompt, knowledge, web_context, mode, guidance)
        if RETRIEVAL_DEBUG:
            print(f"[debug] final_prompt\n{full_prompt}", flush=True)
        answer = await self.generate(
            full_prompt,
            THEN_SYSTEM_PROMPT,
            temperature=LIT_TEMPERATURE,
            top_p=LIT_TOP_P,
            max_tokens=LIT_MAX_TOKENS,
            prefer_rich_style=True,
        )
        evidence_for_quote_check = "\n\n".join(part for part in (knowledge, web_context) if part)
        repeated_defects = self._repeated_phrase_defects(answer or "")
        style_defects = self._ai_flavored_style_defects(answer or "")
        # Cau phan tich van hoc ma tra ve vai doan cut la chua dat do sau yeu cau.
        if answer and mode.startswith("literature") and len(answer) < 1500:
            style_defects = style_defects + [
                "Bai qua ngan so voi yeu cau phan tich (duoi 1500 ky tu). Trien khai it nhat 3-4 luan diem "
                "du 4 tang (thu phap -> trich nguyen van 1-3 cau -> phan tich co che -> khai quat phong cach), "
                "dung evidence trong context; khong don tho, khong lap y."
            ]
        librarian_dump = bool(answer) and self._looks_like_librarian_dump(answer)
        needs_repair = bool(answer) and (
            librarian_dump
            or self._looks_like_source_dump(answer)
            or self._looks_like_generic_literary_answer(answer)
            or self._looks_like_weak_style_analysis(answer)
            or self._looks_like_dry_literary_style(answer)
            or self._has_unverified_long_quotes(answer, evidence_for_quote_check)
            or bool(repeated_defects)
            or bool(style_defects)
        )
        if answer and needs_repair:
            if librarian_dump:
                # Che do 'thu thu' bam chat vao dong tai lieu lac de: cang giu kho trong
                # prompt thi model cang liet ke. Sua bang cach BO kho di, ep viet bang
                # kien thuc van hoc rieng.
                repair_knowledge, repair_web = "", ""
                repair_prompt = (
                    "Cau tra loi truoc bi loi NGHIEM TRONG: no liet ke/tom tat/xep hang cac doan tai lieu "
                    "(lap bang trich dan, 'tom tat cac tai lieu lien quan nhat', 'danh gia muc do day du du lieu', "
                    "'tai lieu uu tien nhat', 'thieu sot / du lieu chua du') thay vi TRA LOI cau hoi. Nhung tai "
                    "lieu do LAC de — vut bo hoan toan, dung nhac lai. Hay TU VIET mot bai nghi luan van hoc hoan "
                    "chinh, tra loi DUNG va TRUC TIEP cau hoi ben duoi bang kien thuc van hoc cua chinh minh: co "
                    "luan de, phan tich tu ngu/hinh anh/nhip dieu/cai toi tru tinh (neu la tho) hoac chi tiet/tinh "
                    "huong/nhan vat (neu la van xuoi), co dan chung va loi binh rieng. TUYET DOI khong nhac 'tai "
                    "lieu'/'trich dan'/'P1'/'P2'/'kho', khong lap bang, khong xep hang, khong danh gia 'du lieu day "
                    "du hay khong'.\n\n"
                    f"CAU HOI CAN TRA LOI:\n{prompt}"
                )
            else:
                repair_knowledge, repair_web = knowledge, web_context
                repetition_note = ""
                if style_defects:
                    repetition_note += "LOI VAN PHONG PHAT HIEN DUOC:\n" + "\n".join(f"  - {d}" for d in style_defects) + "\n"
                if repeated_defects:
                    listed = "\n".join(f"  - \"{d}\"" for d in repeated_defects)
                    repetition_note += (
                        "LOI LAP PHAT HIEN DUOC (nghiem trong): cac cau/y sau xuat hien GAN NGUYEN VAN "
                        "nhieu lan trong bai. Moi lan chi duoc noi mot y MOT LAN; sau moi dan chung phai "
                        "rut ra mot phat hien RIENG cho dan chung do, khong dan lai cung ket luan; ket bai "
                        "phai nang len tam khai quat moi chu khong chep lai mo bai:\n" + listed + "\n"
                    )
                repair_prompt = (
                    repetition_note +
                    "Sua cau tra loi sau de tra loi thang vao cau hoi, khong bia, khong chi liet ke nguon, "
                    "khong van mau rong. Moi luan diem van hoc phai co chi tiet/hinh tuong/tinh huong/bieu tuong cu the "
                    "va loi binh rieng. Voi cau hoi phong cach tac gia qua mot bai tho, phai co luan de phong cach, "
                    "phan tich tu ngu/hinh anh/nhip dieu/cai toi tru tinh; khong dung nhan xet rong nhu 'lang man, tinh te, sau sac'. "
                    "Viet lai co chat van hon: mo bang mot truc tu tuong/hinh anh trung tam, dung dong tu co luc, "
                    "cau ngan-dai dan xen, co du am; nhung khong them hinh anh nao khong bam vao context. "
                    "Neu neu bien phap tu tu, phai goi dung phep dua tren dau hieu ngon ngu trong dan chung. "
                    "Moi cau tho/cau van trong ngoac kep phai co nguyen van trong context va dung tac gia/tac pham; "
                    "neu khong, xoa quote do va khong phan tich no nhu dan chung. "
                    "Voi cau hoi so sanh, moi truc phai co A -> B -> diem gap/lech. "
                    "Khong them thong tin moi ngoai context. Neu du lieu khong du, noi ro chua du du lieu de khang dinh.\n\n"
                    f"CAU TRA LOI CAN SUA:\n{answer}"
                )
            repaired = await self.generate(
                self._guarded_prompt(repair_prompt, repair_knowledge, repair_web, "repair"),
                THEN_SYSTEM_PROMPT,
                temperature=LIT_TEMPERATURE,
                top_p=LIT_TOP_P,
                max_tokens=LIT_MAX_TOKENS,
                prefer_rich_style=True,
            )
            if repaired and not (librarian_dump and self._looks_like_librarian_dump(repaired)):
                answer = repaired
            elif librarian_dump:
                # Repair van con che do thu thu (hoac khong chay duoc): lot cac dong meta,
                # con hon gui nguyen ban liet ke tai lieu.
                answer = self._strip_internal_markers(repaired or answer)
                print("[debug] repair_still_librarian=stripped", flush=True)
            elif repeated_defects:
                # Repair LLM khong chay duoc (het quota/429): it nhat cat co hoc cau lap.
                answer = self._strip_repeated_sentences(answer)
                print("[debug] repair_fallback=strip_repeated_sentences", flush=True)
        if answer:
            answer = await self._verify_answer(answer, prompt, knowledge, web_context, mode, retrieval_hit=retrieval_hit)
            answer = self._strip_internal_markers(answer)
            # Chot chan cuoi: du di duong nao (repair thanh cong nhung van lap, verifier viet lai...),
            # cau lap gan nguyen van cung bi cat truoc khi gui.
            if self._repeated_phrase_defects(answer):
                answer = self._strip_repeated_sentences(answer)
                print("[debug] final_guard=strip_repeated_sentences", flush=True)
        return answer, full_prompt

    async def _force_grounded_answer(self, prompt: str, knowledge: str, web_context: str, mode: str) -> str | None:
        force_prompt = (
            "BAT BUOC TRA LOI BANG CHUNG DA TRUY XUAT NEU CO. "
            "Khong duoc noi 'khong du du lieu de khang dinh' khi KHO TRI THUC ben duoi co doan lien quan. "
            "Hay trich y tu evidence, noi ro can cu tu tai lieu nao, va chi tu choi nhung chi tiet khong nam trong evidence.\n\n"
            f"{prompt}"
        )
        full_prompt = self._guarded_prompt(force_prompt, knowledge, web_context, mode + "_force_grounded")
        if RETRIEVAL_DEBUG:
            print(f"[debug] forced_prompt\n{full_prompt}", flush=True)
        answer = await self.generate(full_prompt, THEN_SYSTEM_PROMPT, temperature=0.0)
        if answer:
            return self._strip_internal_markers(answer)
        return None

    @staticmethod
    def _timeout_fallback_answer(pdf_meta: dict, manual_knowledge: str, web_context: str, elapsed_seconds: int) -> str:
        base = (
            f"Then bị quá thời gian phản hồi sau khoảng {elapsed_seconds} giây nên không để bạn chờ trong trạng thái “thinking” nữa.\n\n"
            "Mình gửi trước phần căn cứ đã truy xuất được; bạn có thể hỏi lại ngắn hơn hoặc chạy `/hvhn_debug_retrieval` để xem evidence."
        )
        evidence = AI._evidence_fallback_answer(pdf_meta, manual_knowledge, web_context)
        return base + "\n\n---\n\n" + evidence

    @staticmethod
    def _evidence_fallback_answer(pdf_meta: dict, manual_knowledge: str, web_context: str) -> str:
        chunks = pdf_meta.get("chunks") or []
        if chunks:
            lines = ["Dựa trên các đoạn tài liệu đã truy xuất, có thể trả lời bằng chứng sau:"]
            for chunk in chunks[:3]:
                excerpt = re.sub(r"\s+", " ", chunk.get("excerpt", "")).strip()
                lines.append(f"- {chunk.get('title')} (đoạn {chunk.get('chunk_index')}): {excerpt[:650]}")
            lines.append("Phần trên là trích ý trực tiếp từ evidence; cần đối chiếu thêm tài liệu gốc nếu muốn diễn giải sâu hơn.")
            return "\n".join(lines)
        if manual_knowledge:
            return "Dựa trên tri thức HVHN đã truy xuất:\n" + AI._strip_internal_markers(_clip_text(manual_knowledge, 1800))
        if web_context:
            return "Dựa trên nguồn web đã truy xuất:\n" + AI._strip_internal_markers(_clip_text(web_context, 1800))
        return "Chưa có evidence đủ rõ để trả lời."


    @classmethod
    def _sentence_units(cls, text: str) -> list[str]:
        text = re.sub(r"\s+", " ", text or "").strip()
        if not text:
            return []
        units = re.split(r"(?<=[.!?])\s+|(?<=\")\s+", text)
        return [unit.strip() for unit in units if len(unit.strip()) >= 20]

    @classmethod
    def _quoted_units(cls, text: str) -> list[str]:
        text = re.sub(r"\s+", " ", text or "").strip()
        quotes = []
        quote_pairs = [(chr(8220), chr(8221)), ('"', '"'), ("'", "'")]
        for open_q, close_q in quote_pairs:
            start = 0
            while True:
                left = text.find(open_q, start)
                if left < 0:
                    break
                right = text.find(close_q, left + 1)
                if right < 0:
                    break
                quote = text[left + 1:right].strip()
                if 20 <= len(quote) <= 700 and quote not in quotes:
                    quotes.append(quote)
                start = right + 1
        return quotes

    @classmethod
    def _unit_score(cls, query: str, text: str) -> int:
        haystack = cls._plain_text(text)
        return sum(1 for term in cls._important_query_terms(query, 16) if term in haystack)

    @classmethod
    def _extract_units_from_chunk(cls, query: str, chunk: dict, *, quote_mode: bool, max_units: int = 4) -> list[str]:
        content = chunk.get("content") or chunk.get("excerpt") or chunk.get("first_500") or ""
        candidates = cls._quoted_units(content) if quote_mode else []
        if not candidates:
            candidates = cls._sentence_units(content)
        scored = []
        for unit in candidates:
            score = cls._unit_score(query, unit)
            if score > 0 or quote_mode:
                scored.append((score, unit))
        if not scored and candidates:
            scored = [(0, unit) for unit in candidates[:max_units]]
        scored.sort(key=lambda item: (item[0], len(item[1])), reverse=True)
        selected = []
        seen = set()
        for _, unit in scored:
            key = cls._plain_text(unit)[:180]
            if key in seen:
                continue
            seen.add(key)
            selected.append(unit)
            if len(selected) >= max_units:
                break
        return selected

    @classmethod
    def _deterministic_document_answer(cls, query: str, pdf_meta: dict, profile: dict) -> str | None:
        chunks = pdf_meta.get("chunks") or []
        if not chunks or not (profile.get("quote") or profile.get("aggregate")):
            return None
        max_chunks = 12 if profile.get("aggregate") else 5
        lines = []
        extracted_any = False
        if profile.get("quote"):
            lines.append("Nguyen van trong tai lieu da truy xuat:")
        else:
            lines.append("Cac nhan dinh/trich dan tim thay trong tai lieu da truy xuat:")
        for chunk in chunks[:max_chunks]:
            raw_quotes = cls._quoted_units(chunk.get("content") or "")
            units = cls._extract_units_from_chunk(
                query,
                chunk,
                quote_mode=bool(profile.get("quote") or profile.get("aggregate")),
                max_units=3 if profile.get("aggregate") else 2,
            )
            if not units:
                continue
            extracted_any = True
            lines.append(f"\n- {chunk.get('title')} (doan {chunk.get('chunk_index')}):")
            for unit in units:
                unit = unit.strip()
                if profile.get("quote") or unit in raw_quotes:
                    lines.append(f'  + "{unit}"')
                else:
                    lines.append(f"  + {unit}")
        if not extracted_any:
            return None
        lines.append("\nGhi chu: phan tren chi lay tu cac doan tai lieu da truy xuat; khong bo sung bang tri nho ngoai tai lieu.")
        return "\n".join(lines).strip()


    # Lời dẫn/nhận xét META do bước verifier/refine đôi khi chèn vào — phải lọc khỏi câu trả lời cuối.
    _META_LINE = re.compile(
        r"^\s*(?:"
        r"(?:dưới đây|sau đây)\s+là.*(?:phiên bản|câu trả lời|bản\s+(?:sửa|chỉnh|cải thiện))"
        r"|câu trả lời\s+(?:của bạn|trên|này|ban đầu).*(?:tốt|cải thiện|sửa|chỉnh|hoàn thiện|đáng)"
        r"|(?:tôi|mình)\s+(?:đã|xin|sẽ)?\s*(?:giữ nguyên|thêm|bổ sung|sửa|chỉnh|cải thiện|viết lại|điều chỉnh|tinh chỉnh)"
        r"|(?:phiên bản|bản)\s+(?:sửa đổi|cải thiện|chỉnh sửa|hoàn thiện)"
        r"|câu hỏi của bạn\s+(?:yêu cầu|đề nghị|muốn)"
        r"|(?:dưới đây|sau đây)\s+là\s+câu trả lời"
        r")\b.*$",
        re.IGNORECASE,
    )

    # Cau/doan "di kiem chung toan van bai viet tren bao X / trong tai lieu Y" — lo ten nguon
    # noi bo va day nguoi hoi di doc cho khac. Bat theo dau hieu dong-tu-kiem-chung + doi-tuong-nguon.
    _SOURCE_REFERRAL = re.compile(
        r"(?:kiểm chứng|tra cứu|tra c[uứ]|tìm đọc|tìm hiểu thêm|đối chiếu|tham khảo)"
        r"[^.\n]*?"
        r"(?:toàn văn|bài viết|bài báo|trang báo|tờ báo|\bbáo\s+\w|nguồn tài liệu|tài liệu (?:gốc|liên quan))",
        re.IGNORECASE,
    )

    # Cau disclaimer lo may moc RAG: "trong nguon/tai lieu duoc cung cap khong co/chi de cap...",
    # "can doi chieu voi SGK / tac pham goc". Lo noi bo + day nguoi hoi di tra van ban khac.
    _RAG_DISCLAIMER = re.compile(
        r"(?:"
        r"(?:nguồn\s+)?tài liệu\s+(?:được cung cấp|hiện có|kèm theo)"
        r"|(?:trong\s+)?(?:các\s+)?nguồn\s+(?:tài liệu\s+)?(?:được cung cấp|hiện có)"
        r"|(?:cần|phải|nên)\s+đối chiếu[^.\n]*?(?:sách giáo khoa|\bSGK\b|tác phẩm(?:\s+gốc)?|văn bản(?:\s+gốc)?)"
        r"|(?:tài liệu|nguồn)[^.\n]*?(?:không\s+(?:có|đề cập|chứa)|chỉ\s+đề cập(?:\s+khái quát)?)"
        r")",
        re.IGNORECASE,
    )

    @classmethod
    def _strip_source_referral(cls, answer: str) -> str:
        """Xoa doan/cau ket day nguoi hoi 'di tra cuu toan van tren bao X' (lo nguon noi bo)."""
        blocks = re.split(r"\n\s*\n", answer)
        kept = []
        for block in blocks:
            # Trong tung doan, bo rieng cau vi pham; giu phan con lai.
            sentences = re.split(r"(?<=[.!?])\s+", block)
            keep = [s for s in sentences
                    if not cls._SOURCE_REFERRAL.search(s)
                    and not cls._RAG_DISCLAIMER.search(s)]
            if keep:
                kept.append(" ".join(keep).strip())
        return "\n\n".join(b for b in kept if b).strip()

    # Cac cum tu dac trung che do 'thu thu' (liet ke/tom tat/xep hang corpus thay vi tra loi).
    # Dung chung cho detector (_ai_flavored_style_defects) va _looks_like_librarian_dump.
    _LIBRARIAN_PHRASES = (
        "tu kho pdf", "kho pdf/hvhn", "noi dung uu tien tu kho", "cac doan lien quan",
        "nen duoc uu tien su dung", "chua nhung cau trich nguyen van quan trong",
        "uu tien su dung khi can dan chung", "cac doan p1", "cac doan p3",
        # bien the: tom tat/xep hang/danh gia do day du cua kho tai lieu
        "tom tat ngan gon cac tai lieu", "tai lieu / thu", "tai lieu uu tien nhat",
        "la tai lieu uu tien", "danh gia muc do day du", "muc do day du du lieu",
        "du du lieu de tom tat", "cac trich dan tren la tai lieu", "cac trich dan tren deu",
        "y chinh (trich nguyen van)", "cac tai lieu / ", "cac tai lieu lien quan nhat",
        # bien the moi: "Tom tat ... cac tai lieu/doan trich uu tien nhat", section header
        "cac tai lieu/doan trich uu tien", "doan trich uu tien nhat", "thieu sot / du lieu chua du",
    )

    @classmethod
    def _looks_like_librarian_dump(cls, answer: str) -> bool:
        """True khi cau tra loi dang liet ke/tom tat/xep hang cac doan tai lieu thay vi
        tra loi cau hoi (P1,P2 tran hoac cac cum meta ve 'tai lieu uu tien/day du')."""
        plain = cls._plain_text(answer or "")
        if any(p in plain for p in cls._LIBRARIAN_PHRASES):
            return True
        return bool(
            re.search(r"(?<![a-z])p\d+\s*,\s*p\d+", plain)
            or re.search(r"(?<![a-z])p\d+\s+va\s+p\d+", plain)
        )

    # Dong meta lo may moc RAG: "Tom tat ... tu kho PDF/HVHN", "Cac doan lien quan khac",
    # "noi dung uu tien tu kho", "cac doan P1/P2 ... nen duoc uu tien su dung khi can dan chung".
    _LIBRARIAN_LINE = re.compile(
        r"^\s*(?:"
        r".*\bkho\s+PDF\b"
        r"|.*\bPDF/HVHN\b"
        r"|.*(?:nội dung|noi dung)\s+ưu tiên\s+từ\s+kho"
        r"|(?:các|cac)\s+đoạn\s+(?:liên quan|lien quan)"
        r"|.*\bP\d+\s+(?:và|va)\s+P\d+\b"
        r"|.*(?:nên được|nen duoc)\s+ưu tiên\s+sử dụng"
        # bien the tom tat/xep hang/danh gia do day du cua kho tai lieu
        r"|(?:tóm tắt|tom tat)\b[^\n]*\b(?:tài liệu|tai lieu|trích dẫn|trich dan)\b[^\n]*\b(?:liên quan|lien quan|ưu tiên|uu tien)"
        r"|(?:đánh giá|danh gia)\s+mức độ\s+(?:đầy đủ|day du)\s+(?:dữ liệu|du lieu)"
        r"|.*\b(?:là|la)\s+(?:tài liệu|tai lieu)\s+ưu tiên\s+nhất"
        r"|.*(?:các|cac)\s+(?:trích dẫn|trich dan)\s+trên\s+(?:là|la|đều|deu)\b"
        r"|\|\s*(?:Tác giả|Tac gia)\s*\|"  # dong tieu de bang "| Tac gia | Y chinh |"
        r")\b.*$",
        re.IGNORECASE,
    )

    @classmethod
    def _strip_internal_markers(cls, answer: str) -> str:
        lines = []
        for line in answer.splitlines():
            line = re.sub(r"\s*\[(?:P|S|W)\d+\]", "", line)
            # Marker doan tran khong ngoac ("P1", "P3, P4, P6"): chi xuat hien khi lo noi bo.
            line = re.sub(r"(?<![A-Za-z])P\d+(?:\s*,\s*P\d+)*(?:\s+(?:và|va)\s+P\d+)?", "", line)
            line = re.sub(r"URL:\s*https?://\S+", "", line)
            stripped = line.strip()
            if cls._META_LINE.match(stripped) or cls._LIBRARIAN_LINE.match(stripped):
                continue  # bỏ dòng meta / dòng "thủ thư" xếp hạng đoạn
            lines.append(line.rstrip())
        return cls._strip_source_referral("\n".join(lines).strip())

    _strip_visible_sources = _strip_internal_markers


    async def _then_answer(self, interaction: discord.Interaction, title: str, user_prompt: str, prompt: str, mode: str):
        if not self._has_ai():
            await interaction.response.send_message("Tinh nang AI chua cau hinh API key.", ephemeral=True)
            return

        await interaction.response.defer(thinking=True)
        print(f"[debug] before_retrieval query={user_prompt[:220]!r} mode={mode}", flush=True)
        plan = Planner.build(user_prompt)
        profile = self._request_profile(user_prompt)
        retrieval_limit = max(plan.retrieval_limit, PDF_AGGREGATE_LIMIT if profile["aggregate"] or profile["quote"] else PDF_DEFAULT_LIMIT)
        pdf_meta = await self._pdf_retrieval(user_prompt, limit=retrieval_limit)
        _empty_meta = {"context": "", "chunks": [], "quotes": [], "selected_count": 0, "candidate_count": 0, "top_score": 0}
        if plan.genre == "NLXH":
            # NLXH khong dung dan chung/ly luan van hoc -> khong nhoi kho phe binh (vd Ba dinh cao Tho Moi).
            print("[debug] md_suppressed reason=NLXH", flush=True)
            pdf_meta = dict(_empty_meta)
        elif self._context_off_subject(user_prompt, plan, pdf_meta):
            # Kho tra ve tai lieu LAC tac gia/tac pham dang hoi (vd hoi Tuong Ve Huu -> tra Chi Pheo).
            # Bo han: thà đe model tra loi bang kien thuc rieng con hon nhoi noi dung sai tac pham.
            print(f"[debug] md_suppressed reason=off_subject author={plan.author_filter!r} top_score={pdf_meta.get('top_score')}", flush=True)
            pdf_meta = dict(_empty_meta)
        elif (float(pdf_meta.get("top_score") or 0) < MD_MIN_RELEVANCE
              and not (profile["quote"] or profile["aggregate"]) and not plan.author_filter):
            # Truy xuat yeu/lac de -> bo, tranh lap noi dung tai lieu khong lien quan vao bai.
            print(f"[debug] md_suppressed reason=low_relevance top_score={pdf_meta.get('top_score')}", flush=True)
            pdf_meta = dict(_empty_meta)
        pdf_knowledge = pdf_meta.get("context", "")
        manual_knowledge = await self._knowledge_context(user_prompt)
        feedback_knowledge = await self._feedback_context(user_prompt)
        # Cau hoi neu ro tac gia/tac pham nhung kho thu cong/feedback lac han chu de
        # (vd hoi Tuong Ve Huu -> tra ve phong cach tho To Huu, 100+ trich dan NLXH): bo di.
        _subjects = self._query_subjects(user_prompt, plan)
        if _subjects and manual_knowledge and not self._text_mentions_subject(_subjects, manual_knowledge):
            print("[debug] manual_suppressed reason=off_subject", flush=True)
            manual_knowledge = ""
        if _subjects and feedback_knowledge and not self._text_mentions_subject(_subjects, feedback_knowledge):
            print("[debug] feedback_suppressed reason=off_subject", flush=True)
            feedback_knowledge = ""
        retrieval_hit = self._retrieval_hit(user_prompt, pdf_meta)
        quote_evidence = QuoteExtractor.extract(pdf_meta, plan, user_prompt)
        self._log_top_pdf_chunks(pdf_meta)
        print(
            f"[debug] after_retrieval pdf_candidates={pdf_meta.get('candidate_count', 0)} "
            f"pdf_selected={pdf_meta.get('selected_count', 0)} top_score={pdf_meta.get('top_score', 0)} "
            f"pdf_chars={len(pdf_knowledge)} manual_chars={len(manual_knowledge)} feedback_chars={len(feedback_knowledge)} "
            f"feedback_preview={feedback_knowledge[:500]!r} RETRIEVAL_HIT={retrieval_hit} "
            f"plan={plan.intent} author_filter={plan.author_filter!r} quote_evidence={len(quote_evidence)}",
            flush=True,
        )
        has_local_context = bool(pdf_knowledge or manual_knowledge or feedback_knowledge)
        web_context = "" if plan.document_only and has_local_context else await self._web_context(user_prompt, mode, has_local_context)
        manual_count = self._retrieval_count(manual_knowledge, "S")
        feedback_count = self._retrieval_count(feedback_knowledge, "F")
        web_count = self._retrieval_count(web_context, "W")
        print(
            f"[debug] after_rerank selected_chunks={pdf_meta.get('selected_count', 0)} "
            f"scores={[c.get('score') for c in (pdf_meta.get('chunks') or [])[:5]]}",
            flush=True,
        )
        knowledge = build_context_budget(
            user_prompt,
            pdf_knowledge,
            manual_knowledge,
            web_context,
            CONTEXT_MAX_CHARS,
            teacher_feedback=feedback_knowledge,
        )
        stats = _context_part_stats(pdf_knowledge, manual_knowledge, feedback_knowledge, web_context, knowledge)
        full_prompt_preview = self._guarded_prompt(prompt, knowledge, web_context, mode)
        print(
            "[debug] prompt_build_done "
            f"prompt_chars={len(full_prompt_preview)} est_tokens={self._estimated_tokens(full_prompt_preview)} "
            f"pdf_chars={stats['pdf_chars']} manual_chars={stats['manual_chars']} feedback_chars={stats['feedback_chars']} "
            f"web_chars={stats['web_chars']} final_context_chars={stats['final_context_chars']} "
            f"context_truncated={stats['context_truncated']} retrieved_chunk_count={pdf_meta.get('selected_count', 0)} "
            f"retrieved_chunk_titles={[c.get('title') for c in (pdf_meta.get('chunks') or [])[:5]]} "
            f"feedback_count={feedback_count} RETRIEVAL_HIT={retrieval_hit}",
            flush=True,
        )
        print(
            "[ai-retrieval] "
            f"query={user_prompt[:180]!r} mode={mode} "
            f"pdf_chunks={pdf_meta.get('selected_count', 0)} pdf_candidates={pdf_meta.get('candidate_count', 0)} "
            f"pdf_top_score={pdf_meta.get('top_score', 0)} manual={manual_count} feedback={feedback_count} web={web_count}",
            flush=True,
        )
        deterministic = None
        if plan.intent == "QUOTE_SINGLE":
            deterministic = Formatter.quote_single(quote_evidence, plan)
        elif plan.intent == "QUOTE_COLLECTION":
            deterministic = Formatter.quote_collection(quote_evidence, plan)
        elif profile["quote"] or profile["aggregate"]:
            deterministic = self._deterministic_document_answer(user_prompt, pdf_meta, profile)
        if deterministic and (retrieval_hit or quote_evidence or plan.intent.startswith("QUOTE")):
            answer = deterministic
            full_prompt = self._guarded_prompt(prompt, knowledge, web_context, mode + "_deterministic_extract")
            print(
                f"[debug] deterministic_answer mode={mode} intent={plan.intent} quote={profile['quote']} aggregate={profile['aggregate']} "
                f"chunks={pdf_meta.get('selected_count', 0)} quotes={len(quote_evidence)} chars={len(answer)}",
                flush=True,
            )
            await self._send_answer_embeds(interaction, title=title, answer=answer, full_prompt=full_prompt)
            print(f"[debug] final_answer_sent deterministic=True chars={len(answer)}", flush=True)
            return
        # Luon nhet cac trich dan/nhan dinh DA XAC MINH vao ngu canh khi co — ke ca intent CHAT
        # (vd "nhan dinh cua Vuong Tri Nhan"): truoc day chi nhet cho COMPARE/ANALYSIS nen LLM
        # khong thay quote da tra -> tra loi "khong co trong tai lieu" du kho co.
        seed = Formatter.evidence_block(quote_evidence) if quote_evidence else ""
        if seed:
            knowledge = build_context_budget(
                user_prompt,
                seed + "\n\n" + pdf_knowledge,
                manual_knowledge,
                web_context,
                CONTEXT_MAX_CHARS,
                teacher_feedback=feedback_knowledge,
            )
        guidance = Scaffold.for_plan(plan)
        full_prompt = self._guarded_prompt(prompt, knowledge, web_context, mode, guidance)
        try:
            answer, full_prompt = await asyncio.wait_for(
                self._safe_generate(prompt, knowledge, web_context, mode, retrieval_hit=retrieval_hit, guidance=guidance),
                timeout=AI_ANSWER_TIMEOUT_SECONDS,
            )
        except asyncio.TimeoutError:
            print(
                f"[debug] ai_answer_timeout mode={mode} seconds={AI_ANSWER_TIMEOUT_SECONDS} "
                f"query={user_prompt[:180]!r}",
                flush=True,
            )
            answer = self._timeout_fallback_answer(
                pdf_meta, manual_knowledge, web_context, AI_ANSWER_TIMEOUT_SECONDS
            )
        if answer is None:
            await interaction.followup.send(self._ai_error_message())
            return
        print(
            f"[debug] llm_answer_received insufficient={self._insufficient_answer(answer)} "
            f"answer_chars={len(answer)} verifier_rejected={self._last_verifier_rejected}",
            flush=True,
        )
        if self._insufficient_answer(answer):
            reason = self._reason_code(pdf_meta, manual_count, feedback_count, web_count, self._last_verifier_rejected)
            if stats["context_truncated"] and reason == "UNKNOWN":
                reason = "CONTEXT_TRUNCATED"
            if self._has_strong_evidence(pdf_meta, manual_count, feedback_count, web_count):
                if reason == "UNKNOWN":
                    reason = "PROMPT_FILTERED"
                try:
                    forced = await asyncio.wait_for(
                        self._force_grounded_answer(prompt, knowledge, web_context, mode),
                        timeout=AI_FORCE_FALLBACK_TIMEOUT_SECONDS,
                    )
                except asyncio.TimeoutError:
                    forced = None
                    print(
                        f"[debug] force_grounded_timeout mode={mode} seconds={AI_FORCE_FALLBACK_TIMEOUT_SECONDS}",
                        flush=True,
                    )
                if forced and not self._insufficient_answer(forced):
                    print(f"[debug] refusal_suppressed_by=force_grounded original_reason={reason}", flush=True)
                    answer = forced
                    reason = ""
                else:
                    reason = "VERIFIER_REJECTED" if self._last_verifier_rejected else "LLM_REFUSED"
                    answer = self._evidence_fallback_answer(pdf_meta, manual_knowledge, web_context)
                    print(f"[debug] refusal_replaced_by=evidence_fallback original_reason={reason}", flush=True)
                    reason = ""
            if reason and "REASON_CODE:" not in answer:
                answer = answer.rstrip() + f"\n\n`REASON_CODE: {reason}`"

        await self._send_answer_embeds(interaction, title=title, answer=answer, full_prompt=full_prompt)
        print(
            f"[debug] final_answer_sent insufficient={self._insufficient_answer(answer)} "
            f"chars={len(answer)} reason_code={'REASON_CODE:' in answer}",
            flush=True,
        )

    @app_commands.command(name="ai", description="Hỏi trợ giảng AI: giải đáp, gợi ý làm bài, phân tích tác phẩm")
    async def ai(self, interaction: discord.Interaction, question: str):
        prompt = (
            "Trả lời câu hỏi sau thật đúng trọng tâm. Nếu câu hỏi cần tìm Internet, hãy dùng nguồn web đã tra cứu "
            "để tổng hợp câu trả lời cụ thể, không chỉ liệt kê trang tham khảo. Ngắn khi câu hỏi đơn giản; "
            "sâu sắc, có luận điểm khi câu hỏi cần phân tích. Không bịa chi tiết không có nguồn.\n"
            f"Câu hỏi: {question}"
        )
        await self._then_answer(interaction, "Trợ giảng AI - HVHN", question, prompt, "general_safe")

    @app_commands.command(name="van_hoi", description="Hỏi Then về bài Văn, tác phẩm, luận điểm, dẫn chứng")
    async def van_hoi(self, interaction: discord.Interaction, cau_hoi: str):
        prompt = (
            "Trả lời câu hỏi Ngữ Văn sau theo phong cách HVHN: rõ trọng tâm, có chiều sâu, không sáo rỗng. "
            "Dùng nguồn web đã tra cứu để tổng hợp ý cụ thể; không trả lời bằng danh sách nguồn. "
            "Nếu hỏi về trích dẫn/chi tiết tác phẩm mà không có trong nguồn, hãy từ chối khẳng định và nói cần kiểm chứng.\n"
            f"Câu hỏi: {cau_hoi}"
        )
        await self._then_answer(interaction, "Then - Hỏi Văn", cau_hoi, prompt, "literature_qa")

    @app_commands.command(name="goi_y_mo_bai", description="Gợi ý mở bài theo đề Văn")
    async def goi_y_mo_bai(self, interaction: discord.Interaction, de_bai: str, phong_cach: str = "sâu sắc, không sáo"):
        prompt = (
            "Gợi ý 3 hướng mở bài cho đề sau. Không đưa trích dẫn/nhận định phê bình nếu không có nguồn. "
            "Mỗi hướng gồm: ý tưởng, mở bài mẫu ngắn 5-7 câu, khi nào nên dùng.\n"
            f"Phong cách mong muốn: {phong_cach}\nĐề bài: {de_bai}"
        )
        await self._then_answer(interaction, "Then - Gợi Ý Mở Bài", de_bai, prompt, "writing_suggestion")

    @app_commands.command(name="luyen_de_hom_nay", description="Then giao một bài luyện Văn hôm nay")
    async def luyen_de_hom_nay(self, interaction: discord.Interaction, chu_de: str = "nghị luận văn học"):
        prompt = (
            "Tạo một nhiệm vụ luyện Văn hôm nay. Nếu chủ đề cần tác phẩm cụ thể mà không có nguồn, hãy để ở mức mở "
            "hoặc nói cần thầy cô xác nhận. Gồm: đề bài, mục tiêu kỹ năng, dàn ý gợi mở, tiêu chí tự kiểm, bài tập 10 phút.\n"
            f"Chủ đề: {chu_de}"
        )
        await self._then_answer(interaction, "Then - Luyện Đề Hôm Nay", chu_de, prompt, "practice_task")

    @app_commands.command(name="ai_kienthuc_them", description="Thêm tri thức HVHN cho Then (Admin)")
    async def add_knowledge(self, interaction: discord.Interaction, category: str, title: str, content: str, source: str = ""):
        if not self._is_admin(interaction):
            await interaction.response.send_message("Bạn cần role HVHN Admin hoặc quyền Manage Server.", ephemeral=True)
            return
        await self.bot.db.execute(
            """
            INSERT INTO ai_knowledge (category, title, content, source, created_by)
            VALUES ($1, $2, $3, $4, $5)
            """,
            category.strip(),
            title.strip(),
            content.strip(),
            source.strip() or None,
            interaction.user.id,
        )
        await interaction.response.send_message("Đã thêm tri thức cho Then.", ephemeral=True)

    @app_commands.command(name="ai_kienthuc_tim", description="Tìm tri thức đã nạp cho Then")
    async def search_knowledge(self, interaction: discord.Interaction, tu_khoa: str):
        rows = await self.bot.db.fetch(
            """
            SELECT id, category, title, content
            FROM ai_knowledge
            WHERE approved = TRUE
              AND (lower(title) LIKE $1 OR lower(content) LIKE $1 OR lower(category) LIKE $1)
            ORDER BY created_at DESC
            LIMIT 8
            """,
            f"%{tu_khoa.lower()}%",
        )
        if not rows:
            await interaction.response.send_message("Chưa thấy tri thức phù hợp.", ephemeral=True)
            return
        embed = discord.Embed(title="Tri thức Then", color=discord.Color.blue())
        for row in rows:
            content = row["content"][:250] + ("..." if len(row["content"]) > 250 else "")
            embed.add_field(name=f"#{row['id']} [{row['category']}] {row['title']}", value=content, inline=False)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    async def _run_debug_retrieval(self, query: str) -> list[str]:
        print(f"[debug] before_retrieval query={query[:220]!r} mode=debug_command", flush=True)
        plan = Planner.build(query)
        profile = self._request_profile(query)
        retrieval_limit = max(plan.retrieval_limit, PDF_AGGREGATE_LIMIT if profile["aggregate"] or profile["quote"] else PDF_DEFAULT_LIMIT)
        pdf_meta = await self._pdf_retrieval(query, limit=retrieval_limit)
        manual_knowledge = await self._knowledge_context(query)
        feedback_knowledge = await self._feedback_context(query)
        quote_evidence = QuoteExtractor.extract(pdf_meta, plan, query)
        retrieval_hit = self._retrieval_hit(query, pdf_meta)
        self._log_top_pdf_chunks(pdf_meta)
        has_local_context = bool(pdf_meta.get("context") or manual_knowledge or feedback_knowledge)
        web_context = await self._web_context(query, "debug_retrieval", has_local_context)
        manual_count = self._retrieval_count(manual_knowledge, "S")
        feedback_count = self._retrieval_count(feedback_knowledge, "F")
        web_count = self._retrieval_count(web_context, "W")
        decision = self._reason_code(pdf_meta, manual_count, feedback_count, web_count)
        if decision == "UNKNOWN" and self._has_strong_evidence(pdf_meta, manual_count, feedback_count, web_count):
            decision = "OK"
        knowledge = build_context_budget(
            query,
            pdf_meta.get("context", ""),
            manual_knowledge,
            web_context,
            CONTEXT_MAX_CHARS,
            teacher_feedback=feedback_knowledge,
        )
        stats = _context_part_stats(pdf_meta.get("context", ""), manual_knowledge, feedback_knowledge, web_context, knowledge)
        prompt_preview = self._guarded_prompt(query, knowledge, web_context, "debug_retrieval")

        lines = [
            f"Query: `{query[:180]}`",
            f"Plan: `{plan.intent}` | author_filter: `{plan.author_filter or 'none'}` | exact_quote: `{plan.exact_quote}` | aggregate: `{plan.aggregate}`",
            f"Reason code: `{decision}`",
            f"Verifier decision: `{decision}` (debug retrieval only; no LLM/verifier call)",
            f"PDF candidates: `{pdf_meta.get('candidate_count', 0)}` | selected sent to LLM: `{pdf_meta.get('selected_count', 0)}` | top_score: `{pdf_meta.get('top_score', 0)}`",
            f"RETRIEVAL_HIT: `{retrieval_hit}`",
            f"Manual: `{manual_count}` | Feedback: `{feedback_count}` | Web sources: `{web_count}`",
            f"Quote evidence extracted: `{len(quote_evidence)}`",
            f"Prompt chars: `{len(prompt_preview)}` | est tokens: `{self._estimated_tokens(prompt_preview)}`",
            f"Chars PDF/manual/feedback/web/final: `{stats['pdf_chars']}` / `{stats['manual_chars']}` / `{stats['feedback_chars']}` / `{stats['web_chars']}` / `{stats['final_context_chars']}`",
            f"Context truncated: `{stats['context_truncated']}`",
            "",
            "Final selected PDF chunks sent to LLM:",
        ]
        chunks = pdf_meta.get("chunks") or []
        if not chunks:
            lines.append("- Khong co PDF chunk phu hop.")
        for chunk in chunks:
            first_500 = re.sub(r"\s+", " ", chunk.get("first_500") or chunk.get("excerpt", "")).strip()[:500]
            sent_excerpt = re.sub(r"\s+", " ", chunk.get("excerpt", "")).strip()[:500]
            lines.append(
                f"- P{chunk.get('index')} doc=`{chunk.get('title')}` chunk=`{chunk.get('chunk_index')}` "
                f"rank=`{chunk.get('rank')}` kw=`{chunk.get('keyword_score')}` phrase=`{chunk.get('phrase_score')}` "
                f"coverage=`{chunk.get('coverage')}` rerank_score=`{chunk.get('score')}`\n"
                f"  matched_phrases: `{chunk.get('matched_phrases')}`\n"
                f"  missing_keywords: `{chunk.get('missing_keywords')}`\n"
                f"  first500: {first_500}\n"
                f"  extracted_preview: {first_500}\n"
                f"  sent: {sent_excerpt}"
            )
        lines.append("")
        if quote_evidence:
            lines.append("Extracted quote objects:")
            for item in quote_evidence[:12]:
                lines.append(f"- author=`{item.author or 'unknown'}` doc=`{item.pdf_title}` quote={item.quote[:350]}")
            lines.append("")
        lines.append("Selected context block sent to LLM:")
        lines.append(_clip_text(knowledge, 2200))
        text = "\n".join(lines)
        pages = []
        while text:
            pages.append(text[:MAX_DISCORD_LEN])
            text = text[MAX_DISCORD_LEN:]
        return pages[:5]

    @app_commands.command(name="hvhn_debug_retrieval", description="Debug retrieval PDF/manual/feedback/web cho Then (Admin)")
    async def debug_retrieval(self, interaction: discord.Interaction, query: str):
        if not self._is_admin(interaction):
            await interaction.response.send_message("Ban can role HVHN Admin hoac quyen Manage Server.", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)
        try:
            pages = await asyncio.wait_for(self._run_debug_retrieval(query), timeout=DEBUG_COMMAND_TIMEOUT_SECONDS)
        except asyncio.TimeoutError:
            print(f"[debug] hvhn_debug_retrieval timeout query={query[:180]!r}", flush=True)
            await interaction.followup.send("Debug retrieval timeout. Xem Render logs `[debug]` de biet diem ket.", ephemeral=True)
            return
        except Exception as exc:
            print(f"[debug] hvhn_debug_retrieval exception={type(exc).__name__}: {exc}", flush=True)
            await interaction.followup.send(f"Debug retrieval loi: `{type(exc).__name__}: {str(exc)[:1200]}`", ephemeral=True)
            return
        for i, page in enumerate(pages, start=1):
            suffix = f"\n\n(page {i}/{len(pages)})" if len(pages) > 1 else ""
            await interaction.followup.send(page + suffix, ephemeral=True)

    @app_commands.command(name="ai_feedback_stats", description="Xem thống kê feedback AI (Admin)")
    async def feedback_stats(self, interaction: discord.Interaction):
        if not self._is_admin(interaction):
            await interaction.response.send_message("Bạn cần role HVHN Admin hoặc quyền Manage Server.", ephemeral=True)
            return
        rows = await self.bot.db.fetch("SELECT rating, count(*) AS n FROM ai_feedback GROUP BY rating ORDER BY rating")
        total_k = await self.bot.db.fetchval("SELECT count(*) FROM ai_knowledge WHERE approved = TRUE")
        text = "\n".join(f"`{row['rating']}`: {row['n']}" for row in rows) or "Chưa có feedback."
        pending = await self.bot.db.fetchval(
            "SELECT count(*) FROM ai_feedback WHERE rating='needs_fix' AND correction IS NOT NULL AND approved=FALSE")
        await interaction.response.send_message(
            f"Tri thức đã duyệt: `{total_k}`\nFeedback:\n{text}\nGóp ý CHỜ DUYỆT: `{pending}` (dùng /ai_feedback_duyet)",
            ephemeral=True)

    @app_commands.command(name="ai_feedback_duyet",
                          description="(Admin) Duyệt góp ý: nhập số id, hoặc 'all' để duyệt hết chờ, 'xem' để liệt kê")
    async def feedback_duyet(self, interaction: discord.Interaction, muc: str):
        if not self._is_admin(interaction):
            await interaction.response.send_message("Bạn cần role HVHN Admin hoặc quyền Manage Server.", ephemeral=True)
            return
        muc = (muc or "").strip().lower()
        if muc == "xem":
            rows = await self.bot.db.fetch(
                "SELECT id, left(correction, 120) c FROM ai_feedback "
                "WHERE rating='needs_fix' AND correction IS NOT NULL AND approved=FALSE ORDER BY id DESC LIMIT 15")
            if not rows:
                await interaction.response.send_message("Không có góp ý nào đang chờ duyệt.", ephemeral=True)
                return
            body = "\n".join(f"`#{r['id']}` {r['c']}" for r in rows)
            await interaction.response.send_message(f"Góp ý chờ duyệt (mới nhất):\n{body}", ephemeral=True)
            return
        if muc == "all":
            n = await self.bot.db.execute(
                "UPDATE ai_feedback SET approved=TRUE WHERE rating='needs_fix' AND correction IS NOT NULL AND approved=FALSE")
            await interaction.response.send_message(f"Đã duyệt tất cả góp ý đang chờ ({n}).", ephemeral=True)
            return
        if muc.isdigit():
            n = await self.bot.db.execute("UPDATE ai_feedback SET approved=TRUE WHERE id=$1", int(muc))
            await interaction.response.send_message(f"Đã duyệt góp ý #{muc} ({n}).", ephemeral=True)
            return
        await interaction.response.send_message("Cú pháp: `/ai_feedback_duyet xem` | `all` | `<số id>`.", ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(AI(bot))

