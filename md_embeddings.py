"""Embeddings cho tra cuu ngu nghia (hybrid voi tu khoa).

Ho tro nhieu provider, chon qua HVHN_EMBED_PROVIDER (voyage|gemini) hoac tu dong:
- voyage: VOYAGE_API_KEYS, model voyage-3.5-lite (1024 chieu) — ngan sach free lon, khong lo quota/ngay.
- gemini: GEMINI_API_KEYS, model gemini-embedding-001 (ep 768 chieu) — free tier ~100 req/phut.
Sinh embedding CHAY TREN BOT. Loi/thieu key -> None, ben goi lui ve tu khoa.
"""
import asyncio
import json
import os

import aiohttp

_TIMEOUT = aiohttp.ClientTimeout(total=45)
_MAX_BATCH = 96

# ---- cau hinh provider ----
_VOYAGE_MODEL = os.getenv("HVHN_VOYAGE_MODEL", "voyage-3.5-lite")
_VOYAGE_DIM = int(os.getenv("HVHN_VOYAGE_DIM", "1024"))
_VOYAGE_URL = "https://api.voyageai.com/v1/embeddings"

_GEMINI_MODELS = ("gemini-embedding-001", "text-embedding-004", "embedding-001")
_GEMINI_DIM = 768
_GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:batchEmbedContents?key={key}"
_gemini_working_model = None

_last_error = ""
_last_status = 0

# Backwards-compatible public constant. Stored vectors use active_dim().
EMBED_DIM = _GEMINI_DIM


def _keys(env: str) -> list[str]:
    return [k.strip() for k in os.getenv(env, "").split(",") if k.strip()]


def active_provider() -> str:
    pref = os.getenv("HVHN_EMBED_PROVIDER", "").strip().lower()
    if pref == "voyage" and _keys("VOYAGE_API_KEYS"):
        return "voyage"
    if pref == "gemini" and _keys("GEMINI_API_KEYS"):
        return "gemini"
    if _keys("VOYAGE_API_KEYS"):
        return "voyage"
    if _keys("GEMINI_API_KEYS"):
        return "gemini"
    return ""


def active_dim() -> int:
    return _VOYAGE_DIM if active_provider() == "voyage" else _GEMINI_DIM


def has_keys() -> bool:
    return active_provider() != ""


def last_error() -> str:
    return _last_error


def rate_limited_last() -> bool:
    return _last_status == 429


def vec_literal(values) -> str:
    return "[" + ",".join(f"{float(v):.6f}" for v in values) + "]"


async def _post(session, url, body, headers=None):
    """Tra ve (status, payload|None). status=0 khi loi mang."""
    global _last_error, _last_status
    try:
        async with session.post(url, json=body, headers=headers, timeout=_TIMEOUT) as resp:
            _last_status = resp.status
            if resp.status == 200:
                return 200, await resp.json()
            text = (await resp.text())[:300]
            _last_error = f"HTTP {resp.status}: {text}"
            print(f"[embed] {_last_error}", flush=True)
            return resp.status, None
    except (aiohttp.ClientError, asyncio.TimeoutError, json.JSONDecodeError) as exc:
        _last_status = 0
        _last_error = f"{type(exc).__name__}: {exc}"
        print(f"[embed] {_last_error}", flush=True)
        return 0, None


# ---------- Voyage ----------
async def _voyage_batch(session, keys, chunk, input_type):
    body = {"input": chunk, "model": _VOYAGE_MODEL, "input_type": input_type, "output_dimension": _VOYAGE_DIM}
    for key in keys:
        headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
        status, payload = await _post(session, _VOYAGE_URL, body, headers=headers)
        if status == 200 and payload:
            data = payload.get("data")
            if isinstance(data, list) and len(data) == len(chunk):
                ordered = sorted(data, key=lambda d: d.get("index", 0))
                out = [d.get("embedding") for d in ordered]
                if all(out):
                    return out
        elif status == 429:
            continue  # thu key khac
    return None


# ---------- Gemini ----------
def _gemini_request(model, text, task_type):
    req = {"model": f"models/{model}", "content": {"parts": [{"text": text[:8000]}]}, "taskType": task_type}
    if model == "gemini-embedding-001":
        req["outputDimensionality"] = _GEMINI_DIM
    return req


def _parse_gemini(payload):
    embs = payload.get("embeddings")
    if not isinstance(embs, list):
        return None
    out = []
    for e in embs:
        vals = (e or {}).get("values")
        if not vals:
            return None
        out.append([float(x) for x in vals])
    return out


# Compatibility alias for deployments/tests written before provider support.
_parse_batch = _parse_gemini


async def _gemini_batch(session, keys, chunk, task_type):
    global _gemini_working_model
    order = ([_gemini_working_model] if _gemini_working_model else []) + \
            [m for m in _GEMINI_MODELS if m != _gemini_working_model]
    for model in order:
        body = {"requests": [_gemini_request(model, t, task_type) for t in chunk]}
        rate_limited = False
        for key in keys:
            url = _GEMINI_URL.format(model=model, key=key)
            status, payload = await _post(session, url, body)
            if status == 200 and payload:
                parsed = _parse_gemini(payload)
                if parsed and len(parsed) == len(chunk):
                    _gemini_working_model = model
                    return parsed
            elif status == 429:
                _gemini_working_model = model  # model dung, het quota tam
                rate_limited = True
            elif status == 404:
                break  # model khong ton tai -> model khac
        if rate_limited:
            return None
    return None


async def embed_texts(texts, *, task_type: str = "RETRIEVAL_DOCUMENT"):
    """Nhung nhieu doan. Tra ve list vector (cung do dai texts) hoac None."""
    provider = active_provider()
    texts = [t if (t and t.strip()) else " " for t in (texts or [])]
    if not provider or not texts:
        return None
    voyage_type = "query" if task_type == "RETRIEVAL_QUERY" else "document"
    keys = _keys("VOYAGE_API_KEYS") if provider == "voyage" else _keys("GEMINI_API_KEYS")
    results = []
    async with aiohttp.ClientSession() as session:
        for start in range(0, len(texts), _MAX_BATCH):
            chunk = texts[start:start + _MAX_BATCH]
            if provider == "voyage":
                got = await _voyage_batch(session, keys, chunk, voyage_type)
            else:
                got = await _gemini_batch(session, keys, chunk, task_type)
            if got is None:
                return None
            results.extend(got)
    return results


async def embed_query(text: str):
    out = await embed_texts([text], task_type="RETRIEVAL_QUERY")
    return out[0] if out else None


async def probe() -> str:
    prov = active_provider()
    if not prov:
        return "chua cau hinh key (VOYAGE_API_KEYS hoac GEMINI_API_KEYS)"
    out = await embed_texts(["kiểm tra"], task_type="RETRIEVAL_QUERY")
    if out and out[0]:
        return f"OK provider={prov} dim={len(out[0])}"
    return f"{prov}: {last_error() or 'None'}"
