import pikepdf
import sys

def encrypt_pdf(input_path, output_path, user_password="", owner_password="ChuyenDoiMatKhauManh123!@#"):
    pdf = pikepdf.open(input_path)
    
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
    
    pdf.save(
        output_path,
        encryption=pikepdf.Encryption(
            user=user_password,
            owner=owner_password,
            R=6,
            allow=permissions
        )
    )
    print(f"Đã mã hóa: {output_path}")

if __name__ == "__main__":
    input_file = r"D:\Download 2\HVHN ĐỘC QUYỀN\[ĐỀ HSG] - ĐỀ THAM KHẢO HSG9 TPHCM 1.pdf"
    output_file = r"D:\Download 2\HVHN ĐỘC QUYỀN\[ĐỀ HSG] - ĐỀ THAM KHẢO HSG9 TPHCM 1_encrypted.pdf"
    encrypt_pdf(input_file, output_file)