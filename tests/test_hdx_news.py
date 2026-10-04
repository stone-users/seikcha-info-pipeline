# ============================================================
# test_hdx_news.py — 三期新数据源测试
# （fetch_hdx 月度表纯函数 / fetch_news RSS 解析与走廊-口岸归因纯函数）
# ============================================================
import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "pipeline"))

from fetch_hdx import (aggregate_month, corridor_month_counts, latest_full_month,
                       parse_events_rows, score_fr03_from_counts)
from fetch_news import match_ct05, match_ct06, parse_gnews_rss, within_72h

HEADER = ["Country", "Admin1", "Admin2", "ISO3", "Admin2 Pcode", "Admin1 Pcode",
          "Month", "Year", "Events"]


def row(admin1: str, month: str, year: str, events: str) -> list[str]:
    return ["Myanmar", admin1, "X", "MMR", "P", "P", month, year, events]


NOW = datetime(2026, 10, 4, 12, 0, tzinfo=timezone.utc)


def rss_doc(items: list[str]) -> str:
    return ('<rss version="2.0"><channel>'
            + "".join(f"<item>{i}</item>" for i in items) + "</channel></rss>")


def rss_item(title: str, url: str, source: str, pub: str) -> str:
    return (f"<title>{title}</title><link>{url}</link>"
            f"<pubDate>{pub}</pubDate><source url=\"s\">{source}</source>")


class TestFetchHdx(unittest.TestCase):
    """HDX 月度表：最近完整月定位 / admin1 聚合 / 走廊映射 / 规则出分。"""

    def setUp(self):
        self.rows = [HEADER,
                     row("Yangon", "August", "2026", "3"),
                     row("Sagaing", "September", "2026", "6"),
                     row("Kachin", "September", "2026", "1"),
                     row("Yangon", "September", "2026", "0"),
                     row("Sagaing", "September", "2025", "99")]  # 旧年份不得计入

    def test_latest_full_month(self):
        self.assertEqual(latest_full_month(self.rows), (2026, 9))

    def test_aggregate_month_filters_window(self):
        counts = aggregate_month(self.rows, 2026, 9)
        self.assertEqual(counts.get("Sagaing"), 6)
        self.assertEqual(counts.get("Kachin"), 1)
        self.assertEqual(counts.get("Yangon"), 0)
        self.assertNotIn("Ayeyarwady", counts)  # 未出现省份无键

    def test_corridor_mapping(self):
        # 实际映射：Sagaing→D，Kachin→D+H
        counts = corridor_month_counts(aggregate_month(self.rows, 2026, 9))
        self.assertEqual(counts["D"], 7)   # Sagaing 6 + Kachin 1
        self.assertEqual(counts["H"], 1)   # Kachin
        self.assertEqual(counts["B"], 0)

    def test_parse_events_rows_skips_license_sheet(self):
        """双 sheet（授权说明+数据）时只返回含 Admin1/Events 表头的数据 sheet。"""
        import io
        import zipfile
        NS = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"

        def sheet_xml(rows: list[list[str]]) -> str:
            body = "".join(
                "<row>" + "".join(
                    f'<c t="inlineStr"><is><t>{c}</t></is></c>' for c in r)
                + "</row>" for r in rows)
            return (f'<worksheet xmlns="{NS[1:-1]}"><sheetData>{body}</sheetData></worksheet>')

        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as z:
            z.writestr("xl/worksheets/sheet1.xml", sheet_xml([["Licensing"]]))
            z.writestr("xl/worksheets/sheet2.xml", sheet_xml([HEADER, row("Sagaing", "September", "2026", "6")]))
        rows = parse_events_rows(buf.getvalue())
        self.assertEqual(rows[0], HEADER)
        self.assertEqual(len(rows), 2)

    def test_score_boundary(self):
        levels = score_fr03_from_counts({"A": 0, "D": 6, "H": 1})
        self.assertEqual(levels["A"], "低")
        self.assertEqual(levels["D"], "中")
        self.assertEqual(levels["H"], "低")


class TestGnewsRss(unittest.TestCase):
    """Google News RSS 备源：解析 / 72h 窗口 / 独立信源归因。"""

    def test_within_72h(self):
        fresh = format(NOW, "%a, %d %b %Y %H:%M:%S %z")
        stale = format(NOW - timedelta(hours=73), "%a, %d %b %Y %H:%M:%S %z")
        self.assertTrue(within_72h(fresh, NOW))
        self.assertFalse(within_72h(stale, NOW))
        self.assertFalse(within_72h("garbage", NOW))  # 解析失败=过期（保守）

    def test_parse_gnews_rss(self):
        fresh = format(NOW - timedelta(hours=5), "%a, %d %b %Y %H:%M:%S %z")
        stale = format(NOW - timedelta(days=10), "%a, %d %b %Y %H:%M:%S %z")
        doc = rss_doc([
            rss_item("Muse border crossing closed", "https://a.example/1", "Irrawaddy", fresh),
            rss_item("Old unrelated news", "https://b.example/2", "DVB", stale),
        ])
        arts = parse_gnews_rss(doc, NOW)
        self.assertEqual(len(arts), 1)
        self.assertEqual(arts[0]["domain"], "Irrawaddy")
        self.assertEqual(arts[0]["title"], "Muse border crossing closed")

    def test_parse_bad_xml_returns_empty(self):
        self.assertEqual(parse_gnews_rss("<not-xml", NOW), [])


class TestMatchAttribution(unittest.TestCase):
    """口岸/走廊归因纯函数（标题词匹配 + 独立信源集）。"""

    def test_match_ct06_close_two_domains(self):
        arts = [
            {"title": "Muse border crossing closed amid fighting", "domain": "irrawaddy.com", "url": "u1"},
            {"title": "Ruili trade gate shutdown continues", "domain": "dvb.com", "url": "u2"},
            {"title": "Myawaddy checkpoint closed", "domain": "irrawaddy.com", "url": "u3"},  # 同域→不计独立
        ]
        per_port = match_ct06(arts)
        self.assertEqual(per_port["PT-02"]["close"], {"irrawaddy.com", "dvb.com"})  # Muse+Ruili→PT-02
        self.assertEqual(per_port["PT-01"]["close"], {"irrawaddy.com"})

    def test_match_ct05_city_attribution_first_hit(self):
        arts = [
            {"title": "Bridge destroyed near Lashio", "domain": "a.com", "url": "u1"},
            {"title": "Highway blocked in Mandalay", "domain": "b.com", "url": "u2"},
            {"title": "Checkpoint attacked in Myitkyina", "domain": "c.com", "url": "u3"},
        ]
        per_corr = match_ct05(arts)
        self.assertEqual(per_corr["C"]["destroy"], {"a.com"})
        self.assertEqual(per_corr["B"]["destroy"], {"b.com"})
        self.assertEqual(per_corr["D"]["attack"], {"c.com"})

    def test_unrelated_article_ignored(self):
        per_corr = match_ct05([{"title": "Yangon fashion week opens", "domain": "x.com", "url": "u"}])
        self.assertTrue(all(not v["destroy"] and not v["attack"] for v in per_corr.values()))


if __name__ == "__main__":
    unittest.main()
