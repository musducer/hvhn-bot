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
from pathlib import Path

import asyncpg
from dotenv import load_dotenv

from hvhn_batch import (
    MIRROR_SOURCE, DOCS_DIR, load_clients, append_client,
    list_docs, render_batch, write_new_rows_csv, remove_client, remove_doc,
)

# Các folder đơn hàng (nằm cạnh folder Source, do Apps Script tạo + Form/menu ghi vào)
MIRROR_PARENT = os.path.dirname(MIRROR_SOURCE)
JOBS_KHACH = os.path.join(MIRROR_PARENT, "_don_them_khach")
INCOMING_DOCS = os.path.join(MIRROR_PARENT, "_don_them_tai_lieu")
PROCESSED_DOCS = os.path.join(MIRROR_PARENT, "_da_xu_ly_tai_lieu")  # lưu trữ PDF gốc đã xử lý
XOA_KHACH = os.path.join(MIRROR_PARENT, "_don_xoa_khach")           # đơn xoá khách (email)
XOA_TAILIEU = os.path.join(MIRROR_PARENT, "_don_xoa_tai_lieu")      # đơn xoá tài liệu (tên gốc)

POLL_SECONDS = 30

load_dotenv()
DATABASE_URL = os.getenv("DATABASE_URL")

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
"""


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
    return f"{prefix}_{_ts()}_{_safe_stem(label)}{suffix}"


def _write_atomic(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_name(path.name + ".part")
    with open(tmp_path, "wb") as f:
        f.write(data)
    os.replace(tmp_path, path)


async def _fetch_discord_jobs():
    if not DATABASE_URL:
        return []
    conn = await asyncpg.connect(DATABASE_URL)
    try:
        await conn.execute(DOC_JOB_SCHEMA)
        async with conn.transaction():
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
        target = os.path.join(INCOMING_DOCS, _job_name("discord_tailieu", os.path.splitext(filename)[0], ".pdf"))
        _write_atomic(target, bytes(job["file_data"] or b""))
    elif job_type == "remove_client":
        email = (job["text_payload"] or "").strip()
        _write_atomic(os.path.join(XOA_KHACH, _job_name("discord_xoa_khach", email, ".txt")), email.encode("utf-8"))
    elif job_type == "remove_document":
        doc_base = os.path.splitext((job["text_payload"] or "").strip())[0]
        _write_atomic(os.path.join(XOA_TAILIEU, _job_name("discord_xoa_tailieu", doc_base, ".txt")), doc_base.encode("utf-8"))
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
                print(f"[XOÁ TÀI LIỆU] {doc_base} -> {'đã gỡ' if remove_doc(doc_base) else 'không có trong docs/'}")
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
        except Exception:
            traceback.print_exc()
        time.sleep(POLL_SECONDS)


if __name__ == "__main__":
    main()
