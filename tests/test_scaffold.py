import unittest
from cogs.ai import Scaffold, RAGPlan, _plain_ascii


def _plan(genre, level="THUONG", write_essay=False):
    return RAGPlan(intent="ANALYSIS", genre=genre, level=level, write_essay=write_essay)


def _compare_plan(genre="NONE", level="THUONG"):
    return RAGPlan(intent="COMPARE", genre=genre, level=level)


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

    def test_nlxh_has_no_literary_evidence(self):
        for lvl in ("THUONG", "HSG"):
            block = Scaffold.for_plan(_plan("NLXH", level=lvl))
            self.assertNotIn("dẫn chứng văn học", block.replace("không dùng dẫn chứng văn học", ""))

    def test_default_is_outline(self):
        block = Scaffold.for_plan(_plan("NLVH"))
        self.assertIn("dàn ý chi tiết", block)

    def test_hsg_nlxh_outline_has_product_contract(self):
        plan = RAGPlan(intent="OUTLINE", genre="NLXH", level="HSG")
        block = Scaffold.for_plan(plan)
        self.assertIn("HOP DONG DAU RA - DAN Y", block)
        self.assertIn("Kho chat lieu", block)
        self.assertIn("phan de/gioi han", block)
        self.assertIn("khong tom tat tai lieu", block)

    def test_write_essay_switches_to_essay(self):
        block = Scaffold.for_plan(_plan("NLVH", write_essay=True))
        self.assertIn("bài văn hoàn chỉnh", block)

    def test_compare_has_scaffold_even_without_genre(self):
        block = Scaffold.for_plan(_compare_plan())
        self.assertIn("SO SANH", block)
        self.assertIn("A -> B", block)
        self.assertIn("hoan canh sang tac", block)

    def test_compare_nlvh_keeps_literary_depth(self):
        block = Scaffold.for_plan(_compare_plan("NLVH", "HSG"))
        self.assertIn("SO SANH", block)
        self.assertIn("ly luan van hoc", _plain_ascii(block).lower())


if __name__ == "__main__":
    unittest.main()
