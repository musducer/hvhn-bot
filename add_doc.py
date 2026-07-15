"""Thêm 1 tài liệu MỚI, tự render watermark cho TOÀN BỘ khách hiện có trong clients.csv.
Dùng: python add_doc.py "đường dẫn file pdf mới"
"""
import shutil
import sys
import uuid
from pathlib import Path

from hvhn_batch import DOCS_DIR, load_clients, render_batch, validate_pdf_source, write_new_rows_csv


def _unique_destination(source: Path) -> Path:
    root = Path(DOCS_DIR)
    root.mkdir(parents=True, exist_ok=True)
    if source.parent.resolve() == root.resolve():
        return source
    destination = root / source.name
    if not destination.exists():
        return destination
    for number in range(2, 1000):
        candidate = root / f"{source.stem}_{number}{source.suffix.lower()}"
        if not candidate.exists():
            return candidate
    raise RuntimeError("Kho tài liệu có quá nhiều file trùng tên")


def main():
    if len(sys.argv) != 2:
        print('Dùng: python add_doc.py "đường dẫn file pdf mới"')
        sys.exit(1)

    src = Path(sys.argv[1]).resolve()
    validate_pdf_source(str(src))
    dest = _unique_destination(src)
    if dest != src:
        pending = dest.with_name(f".{dest.name}.{uuid.uuid4().hex[:8]}.part")
        try:
            shutil.copy2(src, pending)
            pending.replace(dest)
        finally:
            try:
                pending.unlink()
            except FileNotFoundError:
                pass
    print(f"Đã lưu vào kho tài liệu: {dest}")

    clients = load_clients()
    rows = render_batch([str(dest)], clients)
    write_new_rows_csv(rows)


if __name__ == "__main__":
    main()
