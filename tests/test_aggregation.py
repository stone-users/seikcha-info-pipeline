# ============================================================
# test_aggregation.py — ACLED 事件聚合纯逻辑测试（admin1 映射/armed 分类/窗口边界）
# ============================================================
import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "pipeline"))

import unittest

from fetch_acled import _aggregate

DAY = date(2026, 10, 3)


def ev(d: date, etype: str, admin1: str) -> dict:
    return {"event_date": d.isoformat(), "event_type": etype, "admin1": admin1}


class TestAggregate(unittest.TestCase):
    def test_armed_counts_7d_and_90d(self):
        events = [
            ev(DAY, "Battles", "Yangon"),                    # 今天 → 90d+1, 7d+1
            ev(DAY - timedelta(days=6), "Air/drone strike", "Mandalay"),  # 界内 → 7d
            ev(DAY - timedelta(days=7), "Battles", "Mandalay"),  # day-7 不在近7日 → 仅 90d
            ev(DAY - timedelta(days=89), "Explosion/Remote violence", "Yangon"),  # 90d
        ]
        stats, note = _aggregate(events, DAY)
        for corr in ("A", "E", "F"):  # 仅 Yangon 命中的走廊 → 2 条 Yangon 武装事件
            self.assertEqual(stats[corr]["armed_90d"], 2, corr)
            self.assertEqual(stats[corr]["armed_7d"], 1, corr)
        for corr in ("C", "D"):  # 仅 Mandalay 命中的走廊 → 2 条 Mandalay 武装事件
            self.assertEqual(stats[corr]["armed_90d"], 2, corr)
            self.assertEqual(stats[corr]["armed_7d"], 1, corr)
        # B 走廊：Yangon 与 Mandalay 双命中 → 2+2
        self.assertEqual(stats["B"]["armed_90d"], 4)
        self.assertEqual(stats["B"]["armed_7d"], 2)
        self.assertIn("命中走廊", note)

    def test_nonarmed_30d_window(self):
        events = [
            ev(DAY, "Theft", "Yangon"),
            ev(DAY - timedelta(days=29), "Riot", "Yangon"),      # 界内
            ev(DAY - timedelta(days=31), "Protest", "Yangon"),   # 出界
        ]
        stats, _ = _aggregate(events, DAY)
        self.assertEqual(stats["B"]["nonarmed_30d"], 2)

    def test_other_type_ignored(self):
        stats, note = _aggregate([ev(DAY, "Strategic developments", "Yangon")], DAY)
        self.assertEqual(stats["B"]["armed_90d"], 0)
        self.assertEqual(stats["B"]["nonarmed_30d"], 0)

    def test_unknown_admin_ignored(self):
        stats, note = _aggregate([ev(DAY, "Battles", "Kachin")], DAY)  # Kachin 只命中 D/H
        self.assertEqual(stats["D"]["armed_90d"], 1)
        self.assertEqual(stats["H"]["armed_90d"], 1)
        self.assertEqual(stats["B"]["armed_90d"], 0)

    def test_bad_dates_skipped(self):
        events = [{"event_date": "garbage", "event_type": "Battles", "admin1": "Yangon"}]
        stats, _ = _aggregate(events, DAY)
        self.assertEqual(stats["B"]["armed_90d"], 0)


if __name__ == "__main__":
    unittest.main()
