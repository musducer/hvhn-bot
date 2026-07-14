import unittest
from cogs.ai import Planner


class CompositionClassifierTest(unittest.TestCase):
    def test_nlxh_detected(self):
        p = Planner.build("Suy nghĩ về hiện tượng vô cảm trong đời sống hiện nay")
        self.assertEqual(p.genre, "NLXH")
        self.assertEqual(p.level, "THUONG")
        self.assertFalse(p.write_essay)

    def test_nlvh_detected(self):
        p = Planner.build("Phân tích nhân vật Chí Phèo trong tác phẩm cùng tên")
        self.assertEqual(p.genre, "NLVH")

    def test_literary_detail_question_is_not_nlxh(self):
        p = Planner.build(
            'Suy nghi ve chi tiet nhung nhau thai trong truyen ngan "Tuong ve huu" cua Nguyen Huy Thiep'
        )
        self.assertEqual(p.genre, "NLVH")

    def test_hsg_signal(self):
        p = Planner.build("Đề thi HSG: Bàn về ý kiến cho rằng thơ là tiếng nói của tâm hồn")
        self.assertEqual(p.level, "HSG")

    def test_nlvh_nhan_dinh_is_hsg(self):
        p = Planner.build("Chứng minh nhận định: nghệ thuật là địa hạt của cái độc đáo qua một tác phẩm")
        self.assertEqual(p.genre, "NLVH")
        self.assertEqual(p.level, "HSG")

    def test_write_essay_flag(self):
        p = Planner.build("Viết bài văn phân tích bài thơ Sóng của Xuân Quỳnh")
        self.assertTrue(p.write_essay)

    def test_outline_wins_over_viet_bai_inside_prompt(self):
        p = Planner.build(
            'Lập dàn ý chi tiết cho đề bài HSG: Viết bài văn nghị luận xã hội với chủ đề "Tìm mình trong kẻ khác".'
        )
        self.assertEqual(p.intent, "OUTLINE")
        self.assertEqual(p.genre, "NLXH")
        self.assertEqual(p.level, "HSG")
        self.assertFalse(p.write_essay)

    def test_plain_question_is_none(self):
        p = Planner.build("Xuân Diệu sinh năm bao nhiêu")
        self.assertEqual(p.genre, "NONE")
