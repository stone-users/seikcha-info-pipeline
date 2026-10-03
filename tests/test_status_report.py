# ============================================================
# test_status_report.py — 状态报告纯函数测试
# （derive_modes 从 evidence 派生链路级别 / build_status 结构 /
#   build_history 历史聚合与坏文件容忍 / source_entry 配色档）
# ============================================================
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "pipeline"))

from status_report import (build_history, build_status, derive_modes,
                           source_entry, st_max)


def _ev(source: str, note: str) -> dict:
    return {"source": source, "url": "https://example.org", "note": note}


def _snap(evidence: dict, corridors: dict | None = None,
          st: dict | None = None, date: str = "2026-10-03") -> dict:
    return {
        "date": date,
        "generated_at": "2026-10-03T09:00:00+08:00",
        "pipeline_version": "1.0",
        "corridors": corridors if corridors is not None else
        {"A": {"fr03": "段基准", "fr15": "平", "ct04": 1, "ct05": "常规", "ct06": "正常"}},
        "evidence": evidence,
        "st_suggestion": st if st is not None else {"A": {"suggestion": "S1", "basis": "ct04=1"}},
    }


class TestDeriveModes(unittest.TestCase):
    """从快照 evidence 派生各因子数据链路级别。"""

    def test_acled_oauth(self):
        m = derive_modes(_snap({
            "fr15": [_ev("Open-Meteo", "未来72h沿线最不利点 仰光 累积降雨 12.0mm → 平")],
            "fr03": [_ev("ACLED（OAuth）", "月化计数")],
            "ct04": [_ev("ACLED（OAuth）", "比值")],
            "ct05": [_ev("GDELT", "走廊A 72h：毁阻域名0 遇袭域名0 → 常规。无报道")],
            "ct06": [_ev("GDELT", "口岸木姐 72h：关停域名0 拥堵域名0 重开域名0 → 正常。无报道")],
        }))
        self.assertEqual(m, {"fr15": "openmeteo", "fr03": "acled-oauth", "ct04": "acled-oauth",
                             "ct05": "gdelt-news", "ct06": "gdelt-news"})

    def test_gdelt_proxy_when_acled_down(self):
        m = derive_modes(_snap({
            "fr15": [_ev("Open-Meteo", "未来72h沿线最不利点 仰光 累积降雨 0.0mm → 平")],
            "fr03": [_ev("ACLED", "不可用：Cloudflare 403")],
            "ct04": [_ev("GDELT", "走廊B 媒体覆盖比 1.2 → 1")],
        }))
        self.assertEqual(m["fr03"], "baseline")
        self.assertEqual(m["ct04"], "gdelt-proxy")

    def test_fr15_all_failed(self):
        m = derive_modes(_snap({"fr15": [_ev("Open-Meteo", "抓取失败，本日该走廊按基准档: timeout")]}))
        self.assertEqual(m["fr15"], "baseline")

    def test_news_all_failed_is_baseline(self):
        m = derive_modes(_snap({
            "ct05": [_ev("GDELT", f"走廊{c} 基础设施新闻抓取失败 → ct05 落基准档 '常规'")
                     for c in "ABCDEFGH"],
            "ct06": [_ev("GDELT", "口岸新闻抓取失败（限流/网络）→ ct06 全口岸落基准档 '正常'")],
        }))
        self.assertEqual(m["ct05"], "baseline")
        self.assertEqual(m["ct06"], "baseline")

    def test_news_partial_failure_still_gdelt(self):
        evs = [_ev("GDELT", f"走廊{c} 72h：毁阻域名0 遇袭域名0 → 常规。无报道") for c in "ABCDEFG"]
        evs.append(_ev("GDELT", "走廊H 基础设施新闻抓取失败 → ct05 落基准档 '常规'"))
        m = derive_modes(_snap({"ct05": evs}))
        self.assertEqual(m["ct05"], "gdelt-news")

    def test_empty_evidence_is_baseline(self):
        m = derive_modes(_snap({}))
        self.assertEqual(set(m.values()), {"baseline"})


class TestStMax(unittest.TestCase):
    def test_max_across_corridors(self):
        snap = _snap({}, st={"A": {"suggestion": "S1"}, "B": {"suggestion": "S3"},
                             "C": {"suggestion": "S2"}})
        self.assertEqual(st_max(snap), "S3")

    def test_empty(self):
        self.assertEqual(st_max(_snap({}, st={})), "S0")


class TestSourceEntry(unittest.TestCase):
    def test_grades(self):
        self.assertEqual(source_entry("openmeteo", True, "")["grade"], "real")
        self.assertEqual(source_entry("acled-oauth", True, "")["grade"], "real")
        self.assertEqual(source_entry("gdelt-proxy", True, "")["grade"], "degraded")
        self.assertEqual(source_entry("gdelt-news", True, "")["grade"], "degraded")
        self.assertEqual(source_entry("acled-cache", True, "")["grade"], "degraded")
        self.assertEqual(source_entry("baseline", False, "")["grade"], "fallback")
        self.assertEqual(source_entry("mock", True, "")["grade"], "fallback")

    def test_ok_passthrough_and_label(self):
        e = source_entry("openmeteo", True, "8/8 走廊实时评分")
        self.assertTrue(e["ok"])
        self.assertEqual(e["label"], "Open-Meteo 实时")
        self.assertEqual(e["detail"], "8/8 走廊实时评分")


class TestBuildStatus(unittest.TestCase):
    def test_structure(self):
        snap = _snap({"fr15": [_ev("Open-Meteo", "未来72h沿线最不利点 仰光 累积降雨 0.0mm → 平")]})
        sources = {f: source_entry("baseline", False, "x") for f in
                   ("fr15", "fr03", "ct04", "ct05", "ct06")}
        st = build_status(snap, sources, ["告警A"], 12.34)
        self.assertEqual(set(st.keys()),
                         {"date", "generated_at", "pipeline_version", "run",
                          "sources", "corridors", "st_suggestion", "evidence"})
        self.assertEqual(st["run"]["duration_s"], 12.3)
        self.assertEqual(st["run"]["warnings"], ["告警A"])
        self.assertEqual(set(st["sources"].keys()), {"fr15", "fr03", "ct04", "ct05", "ct06"})
        self.assertEqual(st["evidence"]["fr15"][0]["source"], "Open-Meteo")


class TestBuildHistory(unittest.TestCase):
    def _write(self, d: Path, name: str, snap: dict):
        (d / name).write_text(json.dumps(snap, ensure_ascii=False), encoding="utf-8")

    def test_aggregation_sorted_and_bad_files_skipped(self):
        with tempfile.TemporaryDirectory() as td:
            d = Path(td)
            self._write(d, "2026-10-01.json", _snap({}, st={"A": {"suggestion": "S2"}}, date="2026-10-01"))
            self._write(d, "2026-10-02.json", _snap({}, st={"A": {"suggestion": "S1"}}, date="2026-10-02"))
            (d / "2026-10-03.json").write_text("{broken json", encoding="utf-8")   # 坏文件
            (d / "latest.json").write_text("{}", encoding="utf-8")                 # 非日期名，忽略
            h = build_history(d)
            self.assertEqual([r["date"] for r in h["days"]], ["2026-10-01", "2026-10-02"])
            self.assertEqual(h["days"][0]["st_max"], "S2")
            self.assertIn("sources", h["days"][0])

    def test_days_cap(self):
        with tempfile.TemporaryDirectory() as td:
            d = Path(td)
            for i in range(1, 6):
                self._write(d, f"2026-10-0{i}.json", _snap({}, date=f"2026-10-0{i}"))
            h = build_history(d, days=3)
            self.assertEqual([r["date"] for r in h["days"]],
                             ["2026-10-03", "2026-10-04", "2026-10-05"])


if __name__ == "__main__":
    unittest.main()
