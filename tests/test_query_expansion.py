import unittest
from cogs.ai import expand_query_terms


class QueryExpansionTest(unittest.TestCase):
    def test_gioi_thieu_expands_to_mo_bai(self):
        terms = expand_query_terms("làm sao viết đoạn giới thiệu cho hay")
        self.assertIn("mo bai", terms)   # cùng cụm với "gioi thieu"

    def test_mo_bai_expands_to_gioi_thieu(self):
        terms = expand_query_terms("cách mở bài ấn tượng")
        self.assertIn("gioi thieu", terms)

    def test_dan_y_expands_to_bo_cuc(self):
        terms = expand_query_terms("cho mình cái dàn ý")
        self.assertIn("bo cuc", terms)
        self.assertIn("luan diem", terms)

    def test_unrelated_query_keeps_own_terms(self):
        terms = expand_query_terms("phân tích nhân vật Chí Phèo")
        self.assertIn("chi pheo", " ".join(terms) if isinstance(terms, list) else terms)
        # khong keo theo cum mo bai
        self.assertNotIn("mo bai", terms)

    def test_no_duplicates(self):
        terms = expand_query_terms("mở bài mở bài")
        self.assertEqual(len(terms), len(set(terms)))


if __name__ == "__main__":
    unittest.main()
