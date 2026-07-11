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


if __name__ == "__main__":
    unittest.main()
