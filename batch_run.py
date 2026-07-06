"""Build lại TOÀN BỘ: mọi tài liệu trong docs/ x mọi khách trong clients.csv.
Dùng khi mới cài đặt lần đầu, hoặc muốn render lại từ đầu.
Việc thường ngày (thêm 1 tài liệu / thêm 1 khách) dùng add_doc.py / add_client.py cho nhanh.
"""
from hvhn_batch import list_docs, load_clients, render_batch, write_new_rows_csv


def main():
    docs = list_docs()
    clients = load_clients()
    rows = render_batch(docs, clients)
    write_new_rows_csv(rows)


if __name__ == "__main__":
    main()
