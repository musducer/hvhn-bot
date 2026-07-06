"""Thêm 1 tài liệu MỚI, tự render watermark cho TOÀN BỘ khách hiện có trong clients.csv.
Dùng: python add_doc.py "đường dẫn file pdf mới"
"""
import os
import shutil
import sys

from hvhn_batch import DOCS_DIR, load_clients, render_batch, write_new_rows_csv


def main():
    if len(sys.argv) != 2:
        print('Dùng: python add_doc.py "đường dẫn file pdf mới"')
        sys.exit(1)

    src = sys.argv[1]
    os.makedirs(DOCS_DIR, exist_ok=True)
    dest = os.path.join(DOCS_DIR, os.path.basename(src))
    shutil.copy2(src, dest)
    print(f"Đã lưu vào kho tài liệu: {dest}")

    clients = load_clients()
    rows = render_batch([dest], clients)
    write_new_rows_csv(rows)


if __name__ == "__main__":
    main()
