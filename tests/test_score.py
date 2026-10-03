# ============================================================
# test_score.py — 评分卡阈值边界全覆盖（唯一权威 = factor_tables.json → rating_cards）
# 运行：python -m unittest discover -s tests -v   （在 info-pipeline/ 根目录）
# ============================================================
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "pipeline"))

import unittest

from score import BASELINE, score_ct04, score_fr03, score_fr15


class TestFR03(unittest.TestCase):
    """FR03: 月化非武装事件数 <5→低 | 5-15→中 | 15-30→高 | >30→极高"""

    def test_bands(self):
        self.assertEqual(score_fr03(0), "低")
        self.assertEqual(score_fr03(4.9), "低")
        self.assertEqual(score_fr03(5), "中")
        self.assertEqual(score_fr03(14.9), "中")
        self.assertEqual(score_fr03(15), "高")
        self.assertEqual(score_fr03(30), "高")
        self.assertEqual(score_fr03(30.1), "极高")
        self.assertEqual(score_fr03(200), "极高")

    def test_invalid(self):
        with self.assertRaises(ValueError):
            score_fr03(-1)
        with self.assertRaises(ValueError):
            score_fr03("10")
        with self.assertRaises(ValueError):
            score_fr03(None)


class TestFR15(unittest.TestCase):
    """FR15: 未来72h预报降雨 <10→好 | 10-50→平 | 50-150→暴雨 | >150→极端"""

    def test_bands(self):
        self.assertEqual(score_fr15(0), "好")
        self.assertEqual(score_fr15(9.9), "好")
        self.assertEqual(score_fr15(10), "平")
        self.assertEqual(score_fr15(49.9), "平")
        self.assertEqual(score_fr15(50), "暴雨")
        self.assertEqual(score_fr15(150), "暴雨")
        self.assertEqual(score_fr15(150.1), "极端")
        self.assertEqual(score_fr15(600), "极端")

    def test_invalid(self):
        with self.assertRaises(ValueError):
            score_fr15(-0.1)


class TestCT04(unittest.TestCase):
    """CT04: r<0.7→0 | 0.7-1.5→1 | 1.5-3→2 | >3→3"""

    def test_bands(self):
        self.assertEqual(score_ct04(0.0), 0)
        self.assertEqual(score_ct04(0.69), 0)
        self.assertEqual(score_ct04(0.7), 1)
        self.assertEqual(score_ct04(1.49), 1)
        self.assertEqual(score_ct04(1.5), 2)
        self.assertEqual(score_ct04(3), 2)
        self.assertEqual(score_ct04(3.01), 3)
        self.assertEqual(score_ct04(99), 3)

    def test_invalid(self):
        with self.assertRaises(ValueError):
            score_ct04(-0.5)


class TestBaseline(unittest.TestCase):
    """基准档必须与 webapp INFO_DEFAULTS 逐字一致（HANDOFF §4.1）。"""

    def test_matches_info_defaults(self):
        self.assertEqual(
            BASELINE,
            {"fr03": "段基准", "fr15": "平", "ct04": 1, "ct05": "常规", "ct06": "正常"},
        )


if __name__ == "__main__":
    unittest.main()
