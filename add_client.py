"""Thêm 1 KHÁCH MỚI, tự thêm vào clients.csv + render watermark TOÀN BỘ tài liệu hiện có trong docs/ cho riêng khách này.
Dùng: python add_client.py "Họ Tên" email@gmail.com
"""
import sys

from hvhn_batch import append_client, list_docs, render_batch, write_new_rows_csv


def main():
    if len(sys.argv) != 3:
        print('Dùng: python add_client.py "Họ Tên" email@gmail.com')
        sys.exit(1)

    name, email = sys.argv[1], sys.argv[2]
    append_client(name, email)
    print(f"Đã thêm khách vào clients.csv: {name} - {email}")

    docs = list_docs()
    rows = render_batch(docs, [{"name": name, "email": email}])
    write_new_rows_csv(rows)


if __name__ == "__main__":
    main()
