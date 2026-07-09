import unittest
from cogs.ai import Scaffold, RAGPlan


def _plan(genre, level="THUONG", write_essay=False):
    return RAGPlan(intent="ANALYSIS", genre=genre, level=level, write_essay=write_essay)


class ScaffoldTest(unittest.TestCase):
    def test_none_is_empty(self):
        self.assertEqual(Scaffold.for_plan(_plan("NONE")), "")

    def test_nlxh_has_phan_bien_and_bai_hoc(self):
        block = Scaffold.for_plan(_plan("NLXH"))
        self.assertIn("Phản biện", block)
        self.assertIn("Bài học", block)

    def test_nlvh_has_he_thong_luan_diem(self):
        block = Scaffold.for_plan(_plan("NLVH"))
        self.assertIn("Hệ thống luận điểm", block)

    def test_hsg_nlvh_mentions_ly_luan(self):
        block = Scaffold.for_plan(_plan("NLVH", level="HSG"))
        self.assertIn("lý luận văn học", block)
        self.assertIn("so sánh", block.lower())

    def test_hsg_nlxh_mentions_da_tang(self):
        block = Scaffold.for_plan(_plan("NLXH", level="HSG"))
        self.assertIn("đa tầng", block)

    def test_default_is_outline(self):
        block = Scaffold.for_plan(_plan("NLVH"))
        self.assertIn("dàn ý chi tiết", block)

    def test_write_essay_switches_to_essay(self):
        block = Scaffold.for_plan(_plan("NLVH", write_essay=True))
        self.assertIn("bài văn hoàn chỉnh", block)


if __name__ == "__main__":
    unittest.main()
