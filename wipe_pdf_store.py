"""Xoa sach kho PDF cu cua bot AI (bang ai_pdf_* + thu muc bot_docs/).

Chay tay: python wipe_pdf_store.py  (go 'WIPE' de xac nhan, hoac --yes de bo prompt)
KHONG chay tu dong trong test/CI. Da chay lan dau 2026-07-10 (80 docs / 5147 chunks).
"""
import asyncio
import glob
import os
import shutil
import sys

import asyncpg
from dotenv import load_dotenv

load_dotenv()
BOT_DOCS_DIR = os.getenv("HVHN_BOT_DOCS_DIR", os.path.join(os.path.dirname(os.path.abspath(__file__)), "bot_docs"))


async def _wipe_db():
    url = os.getenv("DATABASE_URL")
    if not url:
        print("Thieu DATABASE_URL")
        return
    conn = await asyncpg.connect(url)
    try:
        await conn.execute("TRUNCATE ai_pdf_documents, ai_pdf_chunks")
        print("Da TRUNCATE ai_pdf_documents, ai_pdf_chunks")
    finally:
        await conn.close()


def _wipe_files():
    n = 0
    for p in glob.glob(os.path.join(BOT_DOCS_DIR, "*")):
        try:
            if os.path.isfile(p):
                os.remove(p)
            else:
                shutil.rmtree(p)
            n += 1
        except Exception as e:
            print(f"Loi xoa {p}: {e}")
    print(f"Da xoa {n} muc trong {BOT_DOCS_DIR}")


def main():
    if "--yes" not in sys.argv:
        print("CANH BAO: se XOA SACH kho PDF cu (bang ai_pdf_* + bot_docs/). Khong the hoan tac.")
        if input("Go 'WIPE' de xac nhan: ").strip() != "WIPE":
            print("Huy.")
            return
    asyncio.run(_wipe_db())
    _wipe_files()
    print("Hoan tat wipe kho PDF. AI gio chi doc kho .md.")


if __name__ == "__main__":
    main()
