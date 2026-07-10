"""Gemini embeddings cho tra cuu ngu nghia (hybrid voi tu khoa).

- Sinh embedding CHAY TREN BOT (Render co GEMINI_API_KEYS), khong chay o watcher.
- Model text-embedding-004 (768 chieu). Loi/thieu key -> tra None, goi ben ngoai lui ve tu khoa.
"""
import asyncio
import json

import aiohttp

EMBED_MODEL = "text-embedding-004"
EMBED_DIM = 768
_ENDPOINT = "https://generativelanguage.googleapis.com/v1beta/models/{model}:{method}?key={key}"
_TIMEOUT = aiohttp.ClientTimeout(total=30)
_MAX_BATCH = 96  # gioi han batchEmbedContents


def vec_literal(values) -> str:
    """list[float] -> '[0.1,0.2,...]' cho pgvector."""
    return "[" + ",".join(f"{float(v):.6f}" for v in values) + "]"


def _parse_batch(payload: dict) -> list[list[float]] | None:
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


_last_error = ""


def last_error() -> str:
    return _last_error


async def _post(session: aiohttp.ClientSession, url: str, body: dict) -> dict | None:
    global _last_error
    try:
        async with session.post(url, json=body, timeout=_TIMEOUT) as resp:
            if resp.status != 200:
                text = (await resp.text())[:400]
                _last_error = f"HTTP {resp.status}: {text}"
                print(f"[embed] {_last_error}", flush=True)
                return None
            return await resp.json()
    except (aiohttp.ClientError, asyncio.TimeoutError, json.JSONDecodeError) as exc:
        _last_error = f"{type(exc).__name__}: {exc}"
        print(f"[embed] {_last_error}", flush=True)
        return None


async def probe(keys: list[str]) -> str:
    """Thu nhung 1 chuoi ngan; tra ve 'OK' hoac mo ta loi de hien cho admin."""
    out = await embed_texts(keys, ["kiểm tra"], task_type="RETRIEVAL_QUERY")
    if out and out[0]:
        return f"OK (dim={len(out[0])})"
    return last_error() or "khong ro (None)"


async def embed_texts(keys: list[str], texts: list[str], *, task_type: str = "RETRIEVAL_DOCUMENT") -> list[list[float]] | None:
    """Nhung nhieu doan. Tra ve list vector cung do dai texts, hoac None neu that bai hoan toan.

    task_type: RETRIEVAL_DOCUMENT khi luu, RETRIEVAL_QUERY khi tra cuu.
    """
    keys = [k for k in (keys or []) if k]
    texts = [t if (t and t.strip()) else " " for t in (texts or [])]
    if not keys or not texts:
        return None
    results: list[list[float]] = []
    async with aiohttp.ClientSession() as session:
        for start in range(0, len(texts), _MAX_BATCH):
            chunk = texts[start:start + _MAX_BATCH]
            body = {
                "requests": [
                    {
                        "model": f"models/{EMBED_MODEL}",
                        "content": {"parts": [{"text": t[:8000]}]},
                        "taskType": task_type,
                    }
                    for t in chunk
                ]
            }
            got = None
            for key in keys:  # xoay key khi loi/rate-limit
                url = _ENDPOINT.format(model=EMBED_MODEL, method="batchEmbedContents", key=key)
                payload = await _post(session, url, body)
                if payload is not None:
                    got = _parse_batch(payload)
                    if got is not None and len(got) == len(chunk):
                        break
                    got = None
            if got is None:
                return None
            results.extend(got)
    return results


async def embed_query(keys: list[str], text: str) -> list[float] | None:
    out = await embed_texts(keys, [text], task_type="RETRIEVAL_QUERY")
    return out[0] if out else None
