"""
SCRIPT CANH (chạy trên PC). Đọc đơn từ điện thoại (qua Google Form -> Drive -> mirror),
tự render watermark rồi đẩy lại Drive để phân phối. Chạy: python watcher.py
Hoặc bấm đúp run_watcher.bat. Cứ để chạy khi PC bật; đơn tới lúc nào xử lúc đó.
"""
import os
import time
import shutil
import traceback
import asyncio
import json
import uuid
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import requests
import asyncpg
from dotenv import load_dotenv

from hvhn_batch import (
    MIRROR_SOURCE, DOCS_DIR, load_clients, append_client,
    list_docs, render_batch, write_new_rows_csv, remove_client, remove_doc,
)
from pdf_knowledge import (
    PDF_KNOWLEDGE_SCHEMA,
    index_pdf_path,
    remove_pdf_document_by_title,
    sync_pdf_folder,
)

# Các folder đơn hàng (nằm cạnh folder Source, do Apps Script tạo + Form/menu ghi vào)
MIRROR_PARENT = os.path.dirname(MIRROR_SOURCE)
JOBS_KHACH = os.path.join(MIRROR_PARENT, "_don_them_khach")
INCOMING_DOCS = os.path.join(MIRROR_PARENT, "_don_them_tai_lieu")
PROCESSED_DOCS = os.path.join(MIRROR_PARENT, "_da_xu_ly_tai_lieu")  # lưu trữ PDF gốc đã xử lý
XOA_KHACH = os.path.join(MIRROR_PARENT, "_don_xoa_khach")           # đơn xoá khách (email)
XOA_TAILIEU = os.path.join(MIRROR_PARENT, "_don_xoa_tai_lieu")      # đơn xoá tài liệu (tên gốc)
SHEET_XOA_KHACH = os.path.join(MIRROR_PARENT, "_don_sheet_xoa_khach")       # Discord -> Apps Script xoá Sheet/Drive
SHEET_XOA_TAILIEU = os.path.join(MIRROR_PARENT, "_don_sheet_xoa_tai_lieu")  # Discord -> Apps Script xoá Sheet/Drive
SHEET_GIAHAN_KHACH = os.path.join(MIRROR_PARENT, "_don_sheet_giahan_khach") # Discord -> Apps Script gia hạn
SHEET_STATUS_FILE = os.path.join(MIRROR_PARENT, "_sheet_status", "sheet_status.json")

POLL_SECONDS = 30
PDF_SYNC_SECONDS = 600
LAST_PDF_SYNC = 0

load_dotenv()
DATABASE_URL = os.getenv("DATABASE_URL")
BOT_DOCS_DIR = os.getenv("HVHN_BOT_DOCS_DIR", os.path.join(os.path.dirname(os.path.abspath(__file__)), "bot_docs"))
STALE_PROCESSING_MINUTES = int(os.getenv("HVHN_STALE_PROCESSING_MINUTES", "30"))

DOC_JOB_SCHEMA = """
CREATE TABLE IF NOT EXISTS hvhn_doc_jobs (
    id SERIAL PRIMARY KEY,
    job_type TEXT NOT NULL,
    text_payload TEXT,
    file_name TEXT,
    file_data BYTEA,
    requested_by BIGINT,
    status TEXT NOT NULL DEFAULT 'pending',
    error TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    processed_at TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS hvhn_runtime_status (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS hvhn_clients_cache (
    email TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    doc_count INTEGER NOT NULL DEFAULT 0,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS hvhn_docs_cache (
    doc_name TEXT PRIMARY KEY,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS hvhn_sheet_clients (
    email TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    grant_date TEXT,
    expiry_date TEXT,
    days_left INTEGER,
    status TEXT,
    doc_count INTEGER NOT NULL DEFAULT 0,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS hvhn_sheet_docs (
    doc_name TEXT PRIMARY KEY,
    client_count INTEGER NOT NULL DEFAULT 0,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
"""

DOC_JOB_SCHEMA += PDF_KNOWLEDGE_SCHEMA


def _ts():
    return time.strftime("%Y%m%d_%H%M%S")


def _stable(path, checks=3, gap=1.0):
    """Đợi file ổn định (Drive đồng bộ xong) — kích thước không đổi qua vài lần đo."""
    last = -1
    for _ in range(checks):
        try:
            size = os.path.getsize(path)
        except OSError:
            return False
        if size != last:
            last = size
            time.sleep(gap)
        else:
            return True
    return True


def _safe_stem(value, fallback="don"):
    bad = '<>:"/\\|?*'
    value = "".join("_" if ch in bad or ord(ch) < 32 else ch for ch in value).strip(" ._")
    return value[:120] or fallback


def _job_name(prefix, label, suffix):
    return f"{prefix}_{_ts()}_{_safe_stem(label)}_{uuid.uuid4().hex[:8]}{suffix}"


def _write_atomic(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_name(path.name + ".part")
    with open(tmp_path, "wb") as f:
        f.write(data)
    os.replace(tmp_path, path)


def _unique_path(folder, filename):
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    safe_name = _safe_stem(Path(filename).stem, "tai_lieu") + Path(filename).suffix.lower()
    path = folder / safe_name
    if not path.exists():
        return str(path)
    stem = path.stem
    suffix = path.suffix
    for i in range(2, 1000):
        candidate = folder / f"{stem}_{i}{suffix}"
        if not candidate.exists():
            return str(candidate)
    return str(folder / f"{stem}_{uuid.uuid4().hex[:8]}{suffix}")


def _drive_direct_url(url):
    parsed = urlparse(url.strip())
    if "drive.google.com" not in parsed.netloc:
        return url.strip()
    if "/file/d/" in parsed.path:
        file_id = parsed.path.split("/file/d/", 1)[1].split("/", 1)[0]
        return f"https://drive.google.com/uc?export=download&id={file_id}"
    qs = parse_qs(parsed.query)
    if "id" in qs and qs["id"]:
        return f"https://drive.google.com/uc?export=download&id={qs['id'][0]}"
    return url.strip()


def _download_pdf(url, filename, target_folder):
    target = _unique_path(target_folder, filename or "tai_lieu.pdf")
    direct_url = _drive_direct_url(url)
    with requests.Session() as session:
        resp = session.get(direct_url, stream=True, timeout=120)
        token = None
        for key, value in session.cookies.items():
            if key.startswith("download_warning"):
                token = value
                break
        if token:
            resp.close()
            resp = session.get(direct_url, params={"confirm": token}, stream=True, timeout=120)
        resp.raise_for_status()
        tmp = target + ".part"
        with open(tmp, "wb") as f:
            for chunk in resp.iter_content(chunk_size=1024 * 1024):
                if chunk:
                    f.write(chunk)
        with open(tmp, "rb") as f:
            head = f.read(5)
        if head != b"%PDF-":
            os.remove(tmp)
            raise ValueError("Link không tải ra PDF thật. Hãy đặt file Google Drive ở chế độ 'Anyone with the link can view' hoặc dùng Google Form upload.")
        os.replace(tmp, target)
    return target


async def _fetch_discord_jobs():
    if not DATABASE_URL:
        return []
    conn = await asyncpg.connect(DATABASE_URL)
    try:
        await conn.execute(DOC_JOB_SCHEMA)
        async with conn.transaction():
            await conn.execute(
                """
                UPDATE hvhn_doc_jobs
                SET status = 'pending', error = NULL
                WHERE status = 'processing'
                  AND processed_at IS NULL
                  AND created_at < now() - ($1::int * interval '1 minute')
                """,
                STALE_PROCESSING_MINUTES,
            )
            rows = await conn.fetch(
                """
                SELECT id, job_type, text_payload, file_name, file_data
                FROM hvhn_doc_jobs
                WHERE status = 'pending'
                ORDER BY created_at ASC
                LIMIT 10
                FOR UPDATE SKIP LOCKED
                """
            )
            ids = [row["id"] for row in rows]
            if ids:
                await conn.execute(
                    "UPDATE hvhn_doc_jobs SET status = 'processing' WHERE id = ANY($1::int[])",
                    ids,
                )
        return [dict(row) for row in rows]
    finally:
        await conn.close()


async def _mark_discord_job(job_id, status, error=None):
    if not DATABASE_URL:
        return
    conn = await asyncpg.connect(DATABASE_URL)
    try:
        await conn.execute(
            """
            UPDATE hvhn_doc_jobs
            SET status = $2, error = $3, processed_at = now()
            WHERE id = $1
            """,
            job_id,
            status,
            error,
        )
    finally:
        await conn.close()


def _materialize_discord_job(job):
    job_type = job["job_type"]
    if job_type == "add_client":
        payload = (job["text_payload"] or "").strip()
        label = payload.split("\t")[-1] if payload else str(job["id"])
        _write_atomic(os.path.join(JOBS_KHACH, _job_name("discord_khach", label, ".txt")), payload.encode("utf-8"))
    elif job_type == "add_document":
        filename = job["file_name"] or f"discord_tai_lieu_{job['id']}.pdf"
        if not filename.lower().endswith(".pdf"):
            raise ValueError("Tài liệu từ Discord không phải PDF")
        target = _unique_path(INCOMING_DOCS, filename)
        _write_atomic(target, bytes(job["file_data"] or b""))
    elif job_type == "add_document_url":
        url = (job["text_payload"] or "").strip()
        filename = job["file_name"] or f"tai_lieu_{job['id']}.pdf"
        _download_pdf(url, filename, INCOMING_DOCS)
    elif job_type == "add_bot_document":
        filename = job["file_name"] or f"bot_tai_lieu_{job['id']}.pdf"
        if not filename.lower().endswith(".pdf"):
            raise ValueError("Tài liệu bot từ Discord không phải PDF")
        os.makedirs(BOT_DOCS_DIR, exist_ok=True)
        target = _unique_path(BOT_DOCS_DIR, filename)
        _write_atomic(target, bytes(job["file_data"] or b""))
    elif job_type == "add_bot_document_url":
        url = (job["text_payload"] or "").strip()
        filename = job["file_name"] or f"bot_tai_lieu_{job['id']}.pdf"
        os.makedirs(BOT_DOCS_DIR, exist_ok=True)
        _download_pdf(url, filename, BOT_DOCS_DIR)
    elif job_type == "remove_client":
        email = (job["text_payload"] or "").strip()
        _write_atomic(os.path.join(SHEET_XOA_KHACH, _job_name("discord_sheet_xoa_khach", email, ".txt")), email.encode("utf-8"))
        _write_atomic(os.path.join(XOA_KHACH, _job_name("discord_xoa_khach", email, ".txt")), email.encode("utf-8"))
    elif job_type == "remove_document":
        doc_base = os.path.splitext((job["text_payload"] or "").strip())[0]
        _write_atomic(os.path.join(SHEET_XOA_TAILIEU, _job_name("discord_sheet_xoa_tailieu", doc_base, ".txt")), doc_base.encode("utf-8"))
        _write_atomic(os.path.join(XOA_TAILIEU, _job_name("discord_xoa_tailieu", doc_base, ".txt")), doc_base.encode("utf-8"))
    elif job_type == "renew_client":
        payload = (job["text_payload"] or "").strip()
        label = payload.split("\t")[0] if payload else str(job["id"])
        _write_atomic(os.path.join(SHEET_GIAHAN_KHACH, _job_name("discord_giahan_khach", label, ".txt")), payload.encode("utf-8"))
    else:
        raise ValueError(f"Loại đơn không hỗ trợ: {job_type}")


async def _xu_ly_don_discord():
    jobs = await _fetch_discord_jobs()
    for job in jobs:
        try:
            _materialize_discord_job(job)
            await _mark_discord_job(job["id"], "done")
            print(f"[DISCORD] đơn #{job['id']} -> đã chuyển vào folder xử lý")
        except Exception as exc:
            await _mark_discord_job(job["id"], "error", str(exc))
            print(f"[DISCORD] LỖI đơn #{job['id']}: {exc}")


def _count_files(folder, suffix=None):
    if not os.path.isdir(folder):
        return 0
    return sum(
        1 for name in os.listdir(folder)
        if suffix is None or name.lower().endswith(suffix)
    )


async def _sync_runtime_status():
    if not DATABASE_URL:
        return
    conn = await asyncpg.connect(DATABASE_URL)
    try:
        await conn.execute(DOC_JOB_SCHEMA)
        clients = load_clients()
        docs = [os.path.splitext(os.path.basename(p))[0] for p in list_docs()]
        bot_docs = [
            os.path.splitext(name)[0]
            for name in sorted(os.listdir(BOT_DOCS_DIR))
            if os.path.isdir(BOT_DOCS_DIR) and name.lower().endswith(".pdf")
        ] if os.path.isdir(BOT_DOCS_DIR) else []
        doc_count = len(docs)
        status = {
            "watcher_heartbeat": time.strftime("%Y-%m-%d %H:%M:%S"),
            "mirror_parent": MIRROR_PARENT,
            "mirror_ready": str(os.path.isdir(MIRROR_SOURCE)),
            "clients_count": str(len(clients)),
            "docs_count": str(doc_count),
            "bot_docs_count": str(len(bot_docs)),
            "queue_add_client": str(_count_files(JOBS_KHACH, ".txt")),
            "queue_add_document": str(_count_files(INCOMING_DOCS, ".pdf")),
            "queue_remove_client": str(_count_files(XOA_KHACH, ".txt")),
            "queue_remove_document": str(_count_files(XOA_TAILIEU, ".txt")),
            "queue_sheet_remove_client": str(_count_files(SHEET_XOA_KHACH, ".txt")),
            "queue_sheet_remove_document": str(_count_files(SHEET_XOA_TAILIEU, ".txt")),
            "queue_sheet_renew_client": str(_count_files(SHEET_GIAHAN_KHACH, ".txt")),
        }
        for key, value in status.items():
            await conn.execute(
                """
                INSERT INTO hvhn_runtime_status (key, value, updated_at)
                VALUES ($1, $2, now())
                ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, updated_at = now()
                """,
                key,
                value,
            )

        await conn.execute("TRUNCATE hvhn_clients_cache")
        if clients:
            await conn.executemany(
                """
                INSERT INTO hvhn_clients_cache (email, name, doc_count, updated_at)
                VALUES ($1, $2, $3, now())
                ON CONFLICT (email) DO UPDATE
                SET name = EXCLUDED.name, doc_count = EXCLUDED.doc_count, updated_at = now()
                """,
                [(c["email"].lower(), c["name"], doc_count) for c in clients],
            )

        await conn.execute("TRUNCATE hvhn_docs_cache")
        if docs:
            await conn.executemany(
                """
                INSERT INTO hvhn_docs_cache (doc_name, updated_at)
                VALUES ($1, now())
                ON CONFLICT (doc_name) DO UPDATE SET updated_at = now()
                """,
                [(d,) for d in docs],
            )

        if os.path.isfile(SHEET_STATUS_FILE):
            with open(SHEET_STATUS_FILE, encoding="utf-8") as f:
                snapshot = json.load(f)
            sheet_clients = snapshot.get("clients") or []
            sheet_docs = snapshot.get("docs") or []

            await conn.execute("TRUNCATE hvhn_sheet_clients")
            if sheet_clients:
                await conn.executemany(
                    """
                    INSERT INTO hvhn_sheet_clients
                        (email, name, grant_date, expiry_date, days_left, status, doc_count, updated_at)
                    VALUES ($1, $2, $3, $4, $5, $6, $7, now())
                    ON CONFLICT (email) DO UPDATE
                    SET name = EXCLUDED.name,
                        grant_date = EXCLUDED.grant_date,
                        expiry_date = EXCLUDED.expiry_date,
                        days_left = EXCLUDED.days_left,
                        status = EXCLUDED.status,
                        doc_count = EXCLUDED.doc_count,
                        updated_at = now()
                    """,
                    [
                        (
                            str(c.get("email", "")).lower(),
                            c.get("name") or "",
                            c.get("grant_date") or "",
                            c.get("expiry_date") or "",
                            c.get("days_left"),
                            c.get("status") or "",
                            int(c.get("doc_count") or 0),
                        )
                        for c in sheet_clients
                        if c.get("email") and c.get("name")
                    ],
                )

            await conn.execute("TRUNCATE hvhn_sheet_docs")
            if sheet_docs:
                await conn.executemany(
                    """
                    INSERT INTO hvhn_sheet_docs (doc_name, client_count, updated_at)
                    VALUES ($1, $2, now())
                    ON CONFLICT (doc_name) DO UPDATE
                    SET client_count = EXCLUDED.client_count, updated_at = now()
                    """,
                    [(d.get("doc_name") or "", int(d.get("client_count") or 0)) for d in sheet_docs if d.get("doc_name")],
                )
            await conn.execute(
                """
                INSERT INTO hvhn_runtime_status (key, value, updated_at)
                VALUES ('sheet_status_exported_at', $1, now())
                ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, updated_at = now()
                """,
                str(snapshot.get("exported_at") or ""),
            )
    except Exception:
        print("  LỖI đồng bộ trạng thái watcher:")
        traceback.print_exc()
    finally:
        await conn.close()


async def _set_runtime_status(key, value):
    if not DATABASE_URL:
        return
    conn = await asyncpg.connect(DATABASE_URL)
    try:
        await conn.execute(DOC_JOB_SCHEMA)
        await conn.execute(
            """
            INSERT INTO hvhn_runtime_status (key, value, updated_at)
            VALUES ($1, $2, now())
            ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, updated_at = now()
            """,
            key,
            str(value),
        )
    finally:
        await conn.close()


async def _index_pdf_for_ai(path):
    if not DATABASE_URL:
        return
    try:
        result = await index_pdf_path(DATABASE_URL, path)
        print(f"[AI PDF] {os.path.basename(path)} -> {result['chunks']} đoạn")
        await _set_runtime_status("ai_pdf_last_indexed", f"{result['title']} ({result['chunks']} đoạn)")
    except Exception:
        print("  LỖI nạp PDF vào kho tri thức AI:")
        traceback.print_exc()


async def _remove_pdf_from_ai(doc_base):
    if not DATABASE_URL:
        return
    try:
        await remove_pdf_document_by_title(DATABASE_URL, doc_base)
        await remove_pdf_document_by_title(DATABASE_URL, doc_base + ".pdf")
        await _set_runtime_status("ai_pdf_last_removed", doc_base)
    except Exception:
        print("  LỖI xóa PDF khỏi kho tri thức AI:")
        traceback.print_exc()


async def _sync_pdf_knowledge(force=False):
    global LAST_PDF_SYNC
    if not DATABASE_URL:
        return
    now = time.time()
    if not force and now - LAST_PDF_SYNC < PDF_SYNC_SECONDS:
        return
    LAST_PDF_SYNC = now
    try:
        exclusive = await sync_pdf_folder(DATABASE_URL, DOCS_DIR)
        bot_only = await sync_pdf_folder(DATABASE_URL, BOT_DOCS_DIR)
        await _set_runtime_status("ai_pdf_docs_indexed", exclusive["indexed"] + bot_only["indexed"])
        await _set_runtime_status("ai_pdf_exclusive_docs_indexed", exclusive["indexed"])
        await _set_runtime_status("ai_pdf_bot_docs_indexed", bot_only["indexed"])
        await _set_runtime_status("ai_pdf_last_sync", time.strftime("%Y-%m-%d %H:%M:%S"))
        changed = exclusive["changed"] + bot_only["changed"]
        if changed:
            print(f"[AI PDF] đồng bộ kho AI: doc quyen {exclusive['indexed']} file, bot {bot_only['indexed']} file, cap nhat {changed} file")
    except Exception:
        print("  LỖI đồng bộ kho PDF AI:")
        traceback.print_exc()


def xu_ly_don_them_khach():
    if not os.path.isdir(JOBS_KHACH):
        return
    jobs = [f for f in os.listdir(JOBS_KHACH) if f.lower().endswith(".txt")]
    for job in jobs:
        path = os.path.join(JOBS_KHACH, job)
        if not _stable(path):
            continue
        try:
            with open(path, encoding="utf-8") as f:
                line = f.read().strip()
            parts = line.replace(",", "\t").split("\t")
            name, email = parts[0].strip(), parts[1].strip()
            print(f"[KHÁCH] {name} - {email}")

            try:
                append_client(name, email)
            except ValueError:
                print("  (email đã có trong clients.csv, chỉ render lại)")

            rows = render_batch(list_docs(), [{"name": name, "email": email}])
            write_new_rows_csv(rows, filename=f"new_rows_khach_{_ts()}.csv")
            os.remove(path)
        except Exception:
            print("  LỖI xử lý đơn khách:")
            traceback.print_exc()


def xu_ly_don_them_tai_lieu():
    if not os.path.isdir(INCOMING_DOCS):
        return
    os.makedirs(PROCESSED_DOCS, exist_ok=True)
    pdfs = [f for f in os.listdir(INCOMING_DOCS) if f.lower().endswith(".pdf")]
    for pdf in pdfs:
        path = os.path.join(INCOMING_DOCS, pdf)
        if not _stable(path):
            continue
        try:
            print(f"[TÀI LIỆU] {pdf}")
            dest_doc = os.path.join(DOCS_DIR, pdf)
            os.makedirs(DOCS_DIR, exist_ok=True)
            shutil.copy2(path, dest_doc)  # lưu vào kho docs/ để khách mới sau này cũng nhận
            asyncio.run(_index_pdf_for_ai(dest_doc))

            clients = load_clients()
            rows = render_batch([dest_doc], clients)
            write_new_rows_csv(rows, filename=f"new_rows_tailieu_{_ts()}.csv")

            shutil.move(path, os.path.join(PROCESSED_DOCS, pdf))  # dọn khỏi hộp đơn
        except Exception:
            print("  LỖI xử lý đơn tài liệu:")
            traceback.print_exc()


def xu_ly_don_xoa_khach():
    """Đơn xoá khách: mỗi .txt chứa email -> gỡ khỏi clients.csv (để đừng render lại sau này)."""
    if not os.path.isdir(XOA_KHACH):
        return
    for job in [f for f in os.listdir(XOA_KHACH) if f.lower().endswith(".txt")]:
        path = os.path.join(XOA_KHACH, job)
        if not _stable(path):
            continue
        try:
            with open(path, encoding="utf-8") as f:
                email = f.read().strip()
            if email:
                print(f"[XOÁ KHÁCH] {email} -> {'đã gỡ' if remove_client(email) else 'không có trong csv'}")
            os.remove(path)
        except Exception:
            print("  LỖI xử lý đơn xoá khách:")
            traceback.print_exc()


def xu_ly_don_xoa_tai_lieu():
    """Đơn xoá tài liệu: mỗi .txt chứa tên gốc (không đuôi) -> gỡ khỏi kho docs/."""
    if not os.path.isdir(XOA_TAILIEU):
        return
    for job in [f for f in os.listdir(XOA_TAILIEU) if f.lower().endswith(".txt")]:
        path = os.path.join(XOA_TAILIEU, job)
        if not _stable(path):
            continue
        try:
            with open(path, encoding="utf-8") as f:
                doc_base = f.read().strip()
            if doc_base:
                removed = remove_doc(doc_base)
                print(f"[XOÁ TÀI LIỆU] {doc_base} -> {'đã gỡ' if removed else 'không có trong docs/'}")
                if removed:
                    asyncio.run(_remove_pdf_from_ai(doc_base))
            os.remove(path)
        except Exception:
            print("  LỖI xử lý đơn xoá tài liệu:")
            traceback.print_exc()


def main():
    print("=== HVHN watcher đang chạy. Nhấn Ctrl+C để dừng. ===")
    print(f"Hộp đơn khách:     {JOBS_KHACH}")
    print(f"Hộp đơn tài liệu:  {INCOMING_DOCS}\n")
    while True:
        try:
            asyncio.run(_xu_ly_don_discord())
            xu_ly_don_them_khach()
            xu_ly_don_them_tai_lieu()
            xu_ly_don_xoa_khach()
            xu_ly_don_xoa_tai_lieu()
            asyncio.run(_sync_runtime_status())
            asyncio.run(_sync_pdf_knowledge())
        except Exception:
            traceback.print_exc()
        time.sleep(POLL_SECONDS)


if __name__ == "__main__":
    main()
