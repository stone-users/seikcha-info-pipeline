# ============================================================
# test_gdelt.py — GDELT 降级源的比值计算纯函数测试
# ============================================================
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "pipeline"))

import unittest

from fetch_gdelt import MIN_NONZERO_DAYS, ratio_from_series

DAY = date(2026, 10, 3)


def mk_series(values: list[float], end: str = "20261003") -> list[dict]:
    """values[i] = end 往前第 i 天的值（模拟90日序列，日期连续）。"""
    from datetime import timedelta

    d_end = date.fromisoformat(f"{end[0:4]}-{end[4:6]}-{end[6:8]}")
    pts = []
    for i, v in enumerate(values):
        d = d_end - timedelta(days=len(values) - 1 - i)
        pts.append({"date": d.strftime("%Y%m%d") + "T000000Z", "value": v})
    return pts


class TestRatio(unittest.TestCase):
    def test_flat_series_ratio_one(self):
        """90日全平（每天0.01）→ r=1 → 档1（0.7-1.5）。"""
        r, nz, s7, s90 = ratio_from_series(mk_series([0.01] * 90), DAY)
        self.assertIsNotNone(r)
        self.assertAlmostEqual(r, 1.0, places=6)
        self.assertEqual(nz, 90)
        self.assertAlmostEqual(s7, 0.07, places=9)

    def test_recent_spike(self):
        """近7日骤增3倍：r = s7 / (mean90×7)；基线为90日滚动均值（含近7日自身），
        故 r = (0.03×7×90) / (7×(83×0.01+7×0.03)) ≈ 2.597 → 档2。"""
        vals = [0.01] * 83 + [0.03] * 7
        expected = (0.03 * 7 * 90) / (7 * (83 * 0.01 + 7 * 0.03))
        r, _, s7, _ = ratio_from_series(mk_series(vals), DAY)
        self.assertAlmostEqual(r, expected, places=6)
        self.assertAlmostEqual(s7, 0.21, places=9)

    def test_silence_no_signal(self):
        """非零天数 < MIN_NONZERO_DAYS → None（媒体沉默≠安全）。"""
        vals = [0.0] * 85 + [0.02] * (MIN_NONZERO_DAYS - 1)
        r, nz, _, _ = ratio_from_series(mk_series(vals), DAY)
        self.assertIsNone(r)
        self.assertEqual(nz, MIN_NONZERO_DAYS - 1)

    def test_all_zero(self):
        r, _, _, s90 = ratio_from_series(mk_series([0.0] * 90), DAY)
        self.assertIsNone(r)
        self.assertEqual(s90, 0.0)

    def test_bad_dates_skipped(self):
        """坏日期行跳过，不崩。"""
        pts = mk_series([0.01] * 90) + [{"date": "garbage", "value": 9}]
        r, _, _, _ = ratio_from_series(pts, DAY)
        self.assertIsNotNone(r)


if __name__ == "__main__":
    unittest.main()
