# ============================================================
# test_news_rules.py — CT05/CT06 关键词规则与 ST-01 建议档纯函数测试
# ============================================================
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "pipeline"))

import unittest

from fetch_news import score_ct05_corridor, score_ct06_port, st_suggestion_level


class TestCT06(unittest.TestCase):
    """CT06: 关闭须≥2独立域名（反单源假新闻）；拥堵≥1；无证据=正常（中性）。"""

    def test_closed_needs_two_domains(self):
        self.assertEqual(score_ct06_port({"a.com"}, set()), "拥堵")
        self.assertEqual(score_ct06_port({"a.com", "b.com"}, set()), "关闭")
        self.assertEqual(score_ct06_port({"a.com", "b.com", "c.com"}, {"d.com"}), "关闭")

    def test_queue_single_domain(self):
        self.assertEqual(score_ct06_port(set(), {"x.com"}), "拥堵")
        self.assertEqual(score_ct06_port(set(), {"x.com", "y.com"}), "拥堵")

    def test_neutral_no_signal(self):
        self.assertEqual(score_ct06_port(set(), set()), "正常")


class TestCT05(unittest.TestCase):
    """CT05: 桥毁/阻断≥2独立域名→关闭；遇袭/受损≥1→收紧；无证据=常规（中性）。"""

    def test_closed_needs_two_domains(self):
        self.assertEqual(score_ct05_corridor({"a.com"}, set()), "收紧")
        self.assertEqual(score_ct05_corridor({"a.com", "b.com"}, set()), "关闭")

    def test_attack_single_domain(self):
        self.assertEqual(score_ct05_corridor(set(), {"n.com"}), "收紧")

    def test_neutral_no_signal(self):
        self.assertEqual(score_ct05_corridor(set(), set()), "常规")


class TestStSuggestion(unittest.TestCase):
    """ST-01 建议（advisory）：证实关闭→S3；冲突骤增/收紧→S2；其余→S1。"""

    def test_closure_suggests_s3(self):
        self.assertEqual(st_suggestion_level(1, "关闭", "常规"), "S3")
        self.assertEqual(st_suggestion_level(1, "常规", "关闭"), "S3")

    def test_escalation_suggests_s2(self):
        self.assertEqual(st_suggestion_level(3, "常规", "正常"), "S2")
        self.assertEqual(st_suggestion_level(1, "收紧", "正常"), "S2")
        self.assertEqual(st_suggestion_level(3, "收紧", "正常"), "S2")

    def test_quiet_suggests_s1(self):
        self.assertEqual(st_suggestion_level(0, "常规", "正常"), "S1")
        self.assertEqual(st_suggestion_level(1, "常规", "拥堵"), "S1")
        self.assertEqual(st_suggestion_level(2, "常规", "正常"), "S1")


if __name__ == "__main__":
    unittest.main()
