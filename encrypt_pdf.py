import os
import tempfile
import sys
import secrets

import pikepdf

def encrypt_pdf(input_path, output_path, user_password="", owner_password=None):  # nosec B107
    """Mã hóa PDF bằng owner password ngẫu nhiên nếu không được truyền rõ ràng.

    Không dùng mật khẩu mặc định cố định: ai biết mã nguồn có thể gỡ giới hạn PDF.
    """
    owner_password = owner_password or secrets.token_urlsafe(24)
    permissions = pikepdf.Permissions(
        extract=False,                # chặn copy text/hình thường
        accessibility=False,  # chặn copy qua screen reader (bit còn sót)
        modify_other=False,
        print_lowres=False,
        print_highres=False,
        modify_annotation=False,
        modify_assembly=False,
        modify_form=False,
    )
    
    output_dir = os.path.dirname(os.path.abspath(output_path))
    os.makedirs(output_dir, exist_ok=True)
    fd, pending = tempfile.mkstemp(prefix=f".{os.path.basename(output_path)}.", suffix=".part.pdf", dir=output_dir)
    os.close(fd)
    os.remove(pending)
    try:
        with pikepdf.open(input_path) as pdf:
            pdf.save(
                pending,
                encryption=pikepdf.Encryption(
                    user=user_password,
                    owner=owner_password,
                    R=6,
                    allow=permissions,
                ),
            )
        os.replace(pending, output_path)
    finally:
        try:
            os.remove(pending)
        except FileNotFoundError:
            pass
    print(f"Đã mã hóa: {output_path}")

if __name__ == "__main__":
    if len(sys.argv) != 3:
        raise SystemExit("Dùng: python encrypt_pdf.py <input.pdf> <output.pdf>")
    encrypt_pdf(sys.argv[1], sys.argv[2])
