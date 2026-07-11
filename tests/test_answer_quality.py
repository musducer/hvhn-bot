import unittest

from cogs.ai import AI


class AnswerQualityTest(unittest.TestCase):
    def test_generic_literary_answer_is_flagged(self):
        answer = (
            "Muoi cua rung va Ong gia va bien ca deu mang den thong diep sau sac ve cuoc song con nguoi "
            "va moi quan he giua con nguoi voi thien nhien. Ca hai tac pham deu co gia tri va y nghia, "
            "su dung ngon ngu giau hinh anh, the hien su sang tao phong phu cua tac gia. "
            "Tac gia muon nhan manh tam quan trong cua viec bao ve moi truong va nhung trai nghiem song."
        )
        self.assertTrue(AI._looks_like_generic_literary_answer(answer))

    def test_specific_literary_answer_is_not_flagged(self):
        answer = (
            "Trong Ong gia va bien ca, Santiago don doc ra khoi, vat lon voi con ca kiem va dan ca map; "
            "bien ca vi the vua la khong gian lao dong vua la phep thu cua y chi. "
            "Trong Muoi cua rung, tinh huong di san va hinh anh rung day nhan vat vao mot khoanh khac tu van, "
            "lam bat len cau hoi dao duc ve cach con nguoi doi dien su song khac minh."
        )
        self.assertFalse(AI._looks_like_generic_literary_answer(answer))

    def test_weak_xuan_dieu_style_analysis_is_flagged(self):
        answer = (
            "Xuan Dieu la mot trong nhung nha tho tieu bieu cua phong trao Tho Moi, voi phong cach tho "
            "dac trung boi su lang man, tinh te va sau sac. Phong cach tho cua Xuan Dieu duoc the hien "
            "qua ngon ngu tho giau hinh anh va am thanh, bien phap tu tu tinh te, va cau truc tho linh hoat. "
            "Trong bai tho Loi ky nu, chung ta thay su khat khao tinh yeu va su hon nhien cua nguoi con gai. "
            "Nhung so sanh nay giup tao ra mot hinh anh ve tinh yeu nhu mot thu gi do dep va trong mo. "
            "Tong ket, nhung yeu to nay giup tao ra mot khong gian tho rong lon va sau sac."
        )
        self.assertTrue(AI._looks_like_weak_style_analysis(answer))

    def test_specific_style_analysis_is_not_flagged(self):
        answer = (
            "Qua Loi ky nu, phong cach Xuan Dieu hien ra o mot cai toi tru tinh vua ham song vua co don. "
            "Nhung hinh anh dem, ben vang, trang lanh va nhip cau ngan dai bat thuong lam cam giac tinh yeu "
            "tro thanh mot dong chay bon chon, khong yen. O day, nha tho khong chi ta tam trang ma bien "
            "khong gian thanh tam canh: canh vat cung mang cam giac lanh, vang, mong manh. Chinh su giao thoa "
            "giua cam giac, thoi gian va noi co don tao nen net rieng cua Xuan Dieu."
        )
        self.assertFalse(AI._looks_like_weak_style_analysis(answer))

    def test_unverified_poem_quote_is_flagged(self):
        answer = (
            'Trong bai Loi ky nu cua Xuan Dieu, cau "Mua do bui em em tren ben vang / '
            'Do bieng luoi nam mac duoi song troi" cho thay khong gian co don.'
        )
        evidence = "Tai lieu chi co noi dung khai quat ve phong cach Xuan Dieu, khong co cau tho nay."
        self.assertTrue(AI._has_unverified_long_quotes(answer, evidence))

    def test_verified_poem_quote_is_allowed(self):
        quote = "Mua do bui em em tren ben vang / Do bieng luoi nam mac duoi song troi"
        answer = f'Trong bai tho, cau "{quote}" goi khong gian vang lang.'
        evidence = f"[P1] Xuan Dieu - Loi ky nu\n{quote}\nNoi dung phan tich..."
        self.assertFalse(AI._has_unverified_long_quotes(answer, evidence))

    def test_dry_literary_report_style_is_flagged(self):
        answer = (
            "Bai tho Voi vang la mot tac pham tieu bieu cua Xuan Dieu. Ve noi dung, bai tho the hien "
            "tinh yeu cuoc song va khat vong song manh me. Ve nghe thuat, phong cach duoc the hien qua "
            "ngon ngu giau hinh anh, cac bien phap tu tu va cau truc linh hoat. Nhung yeu to nay tao ra mot "
            "khong gian tho sau sac. Tong ket, tac pham co gia tri lon va rat sau sac trong phong trao Tho Moi."
        )
        self.assertTrue(AI._looks_like_dry_literary_style(answer))

    def test_vivid_but_grounded_literary_style_is_allowed(self):
        answer = (
            "Trong Voi vang, phong cach Xuan Dieu bung len tu mot mach ngam vua ham song vua lo au. "
            "Bon dong mo dau keo cang cai toi tru tinh den muc muon can thiep vao nang va gio, nhu muon "
            "giu lai mau va huong truoc khi chung tan di. Nhip cau ngan, dong tu muon lap lai, va truong cam "
            "giac ve huong-sac-anh sang lam bai tho chuyen hoa thanh mot cuoc chay dua voi thoi gian, cuong nhiet "
            "ma van khac khoai."
        )
        self.assertFalse(AI._looks_like_dry_literary_style(answer))


if __name__ == "__main__":
    unittest.main()
