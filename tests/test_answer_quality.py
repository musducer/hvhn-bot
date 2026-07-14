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

    # === Bia trich dan + khung van mau (a)/(b)/(c)/(d): loi Nguyen Binh 2026-07-12 ===
    ABCD_SCAFFOLD_ANSWER = (
        "Toi luon cam thay tho Nguyen Binh nhu mot tieng gio nhe.\n\n"
        "Ngon ngu dan gian\n"
        "(a) Nhan tu: ngon ngu binh dan. (b) Trich dan: \"Me con ngoi ben bep lua, nang chieu roi tren mai tranh\" "
        "(tu bai Me con). (c) Phan tich: cau tho dung tu quen thuoc. (d) Khai quat: tho Nguyen Binh thanh cau noi.\n\n"
        "Cau truc song song\n"
        "(a) Nhan tu: diep tu. (b) Trich dan: \"Mua xuan den, xuan den, rung xanh lai khe hat\" (tu bai Mua xuan). "
        "(c) Phan tich: lap lai tao nhip. (d) Khai quat: diep tu la cay cau nhip dieu.\n\n"
        "Ket luan: tho Nguyen Binh la mot ban hoa ca dan gian."
    )

    def test_abcd_scaffold_is_flagged_as_template(self):
        defects = AI._ai_flavored_style_defects(self.ABCD_SCAFFOLD_ANSWER)
        self.assertTrue(any("KHUNG VAN MAU" in d for d in defects))

    def test_abcd_scaffold_is_not_mistaken_for_librarian(self):
        self.assertFalse(AI._looks_like_librarian_dump(self.ABCD_SCAFFOLD_ANSWER))

    def test_ungrounded_long_quotes_are_flagged_as_fabricated(self):
        # Khong co evidence nao ma van dat cau tho dai trong ngoac kep -> bia.
        self.assertTrue(AI._has_unverified_long_quotes(self.ABCD_SCAFFOLD_ANSWER, ""))

    def test_drop_sentences_removes_fabricated_quotes(self):
        stripped = AI._drop_sentences_with_unverified_quotes(self.ABCD_SCAFFOLD_ANSWER, "")
        # Cac cau tho + ten tac pham bia phai bi cat, khong con quote khong xac minh.
        self.assertNotIn("bai Me con", stripped)
        self.assertNotIn("bai Mua xuan", stripped)
        self.assertNotIn("bep lua, nang chieu", stripped)
        self.assertFalse(AI._has_unverified_long_quotes(stripped, ""))
        # Van giu duoc phan van xuoi (khong xoa sach bai).
        self.assertIn("Nguyen Binh", stripped)

    def test_short_quoted_title_is_not_treated_as_fabricated(self):
        answer = 'Phong cach Nguyen Binh gan voi "chan que", mot khai niem quen thuoc trong tho ong.'
        self.assertFalse(AI._has_unverified_long_quotes(answer, ""))

    def test_known_literary_fact_errors_are_flagged(self):
        answer = (
            "Trong cac tieu thuyet hien dai nhu Lao Hac hay Chiec thuyen ngoai xa, ta thay chat dan gian. "
            "Nhan vat Ly Thong trong Truyen Kieu la mot sang che cua Nguyen Du, gan voi truyen thuyet Tho Tinh Ly. "
            "Nhung ban moi cua Chinh phu nga ruou lai duoc dan gian hoa."
        )
        defects = AI._known_literary_fact_defects(answer)
        self.assertGreaterEqual(len(defects), 5)
        self.assertTrue(any("Ly Thong" in defect for defect in defects))
        self.assertTrue(any("Lao Hac" in defect for defect in defects))
        self.assertTrue(any("Chiec thuyen ngoai xa" in defect for defect in defects))
        self.assertTrue(any("Chinh phu ngam" in defect for defect in defects))

    def test_drop_sentences_with_known_fact_errors(self):
        answer = (
            "Van hoc dan gian co quan he gan bo voi van hoc viet. "
            "Nhan vat Ly Thong trong Truyen Kieu la mot sang che cua Nguyen Du. "
            "Van hoc viet tiep thu chat lieu dan gian roi tai tao thanh nhung gia tri moi."
        )
        cleaned = AI._drop_sentences_with_known_fact_errors(answer)
        self.assertNotIn("Ly Thong", cleaned)
        self.assertNotIn("Truyen Kieu la mot sang che", cleaned)
        self.assertIn("Van hoc dan gian", cleaned)
        self.assertIn("tai tao", cleaned)


if __name__ == "__main__":
    unittest.main()
