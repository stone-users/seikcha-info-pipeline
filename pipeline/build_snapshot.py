# ============================================================
# build_snapshot.py — 每日信息因子快照合成器（管道入口）
# 用法：
#   python pipeline/build_snapshot.py                 # 业务日期=今天(UTC+8)，ACLED 有 key 用真实数据
#   python pipeline/build_snapshot.py --date 2026-10-03 --mock-acled
#   python pipeline/build_snapshot.py --copy-to ../the-seikcha/webapp/public/snapshots
# 产物：
#   snapshots/YYYY-MM-DD.json  snapshots/latest.json  audit/YYYY-MM-DD.md
#   status/status.json  status/history.json（GitHub Pages 状态页数据，生成失败不阻塞发布）
# 纪律：schema 校验不过 = 中止不发布；缺数因子落基准档并在 evidence 留痕。
# ============================================================
import argparse
import json
import os
import shutil
import sys
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from corridors import CORRIDOR_CITIES, CORRIDOR_IDS, CORRIDOR_NAMES  # noqa: E402
from fetch_acled import fetch_security  # noqa: E402
from fetch_gdelt import corridors_ct04  # noqa: E402
from fetch_hdx import fetch_fr03_monthly, score_fr03_from_counts  # noqa: E402
from fetch_news import fetch_nodes_and_ports, st_suggestion_level  # noqa: E402
from fetch_openmeteo import corridor_fr15  # noqa: E402
from score import BASELINE, score_ct04, score_fr03  # noqa: E402
from status_report import source_entry, write_status_files  # noqa: E402
from validate import validate_snapshot  # noqa: E402

PIPELINE_VERSION = "1.0"
TZ8 = timezone(timedelta(hours=8))  # 业务日期按 UTC+8（团队与赛用时区），不依赖系统 tz 数据库


def business_date_today() -> date:
    return datetime.now(TZ8).date()


def build_snapshot(day: date, mock_acled: bool) -> tuple[dict, list[str], dict]:
    """合成快照 dict；返回 (快照, 汇总日志行, 各数据源状态)。"""
    warnings: list[str] = []
    evidence: dict[str, list[dict]] = {}

    # ---- FR15 天气（Open-Meteo，真实） ----
    corridors: dict[str, dict] = {}
    fr15_fail = 0
    for cid in CORRIDOR_IDS:
        level, ev = corridor_fr15(cid, CORRIDOR_CITIES[cid])
        if level is None:
            warnings.append(f"[{cid}] FR15 抓取失败 → 基准档 '平'")
            level = BASELINE["fr15"]
            fr15_fail += 1
        corridors.setdefault(cid, {})["fr15"] = level
        evidence.setdefault("fr15", []).extend(ev)

    # ---- FR03 / CT04：数据源降级链 ----
    #   ① 浏览器辅助缓存（agent 驱动登录浏览器页内导出，绕 Cloudflare）
    #   ② ACLED OAuth（账号密码；服务端可能被 Cloudflare 403 → 自动降级）
    #   ③ GDELT 媒体覆盖代理（免 key 真实信号，仅 ct04；fr03 是绝对事件计数、代理不可比 → 段基准）
    #   ④ --mock-acled 离线联调
    sec, sec_ev, sec_mode = fetch_security(day, mock=mock_acled)
    if sec is not None:
        evidence["fr03"] = list(sec_ev)
        evidence["ct04"] = list(sec_ev)
        if sec_mode == "mock":
            warnings.append("ACLED 处于 MOCK 模式（--mock-acled 联调）——快照不代表实况")
        fr03_entry = source_entry(
            sec_mode, True,
            "MOCK 联调数据（非实况）" if sec_mode == "mock" else "ACLED 官方事件计数（月化非武装）")
        ct04_entry = source_entry(sec_mode, True, "ACLED 官方计数 7日/90日 比值")
        for cid in CORRIDOR_IDS:
            s = sec.get(cid) or {}
            nonarmed = s.get("nonarmed_30d")
            armed7, armed90 = s.get("armed_7d"), s.get("armed_90d")
            if nonarmed is None:
                corridors[cid]["fr03"] = BASELINE["fr03"]  # '段基准'（引擎回退各段档案）
                warnings.append(f"[{cid}] FR03 计数缺失 → 段基准")
            else:
                corridors[cid]["fr03"] = score_fr03(nonarmed)
            if armed7 is None or armed90 is None:
                corridors[cid]["ct04"] = BASELINE["ct04"]
                warnings.append(f"[{cid}] CT04 计数缺失 → 基准档")
            else:
                base_daily = armed90 * 7.0 / 90.0
                r = (armed7 / base_daily) if base_daily > 0 else (0.0 if armed7 == 0 else 99.0)
                corridors[cid]["ct04"] = score_ct04(r)
    else:
        # 降级 → ③ GDELT：ct04 用媒体覆盖比值（真实）；两段式抓取（主跑+冷却重试）
        evidence["fr03"] = list(sec_ev)
        evidence["ct04"] = []
        gap = float(os.environ.get("GDELT_GAP", "10"))
        ct04_levels, ct04_ev = corridors_ct04(day, gap=gap)
        evidence["ct04"].extend(ct04_ev)
        ct04_real = sum(1 for v in ct04_levels.values() if v is not None)
        for cid in CORRIDOR_IDS:
            corridors[cid]["fr03"] = BASELINE["fr03"]
            v = ct04_levels.get(cid)
            corridors[cid]["ct04"] = BASELINE["ct04"] if v is None else v
        ct04_entry = source_entry(
            "gdelt-proxy", ct04_real > 0,
            f"GDELT 媒体覆盖代理（{ct04_real}/8 走廊真实评分）"
            if ct04_real > 0 else "GDELT 代理亦不可用 → 基准档")

        # ④ fr03：ACLED 官方公开月度表（联合国 HDX 分发，免账号免 key，滞后约1个月）
        try:
            counts, hdx_ev, month_desc = fetch_fr03_monthly(
                Path(__file__).resolve().parent.parent / "cache")
            levels = score_fr03_from_counts(counts)
            for cid in CORRIDOR_IDS:
                corridors[cid]["fr03"] = levels[cid]
            evidence["fr03"].extend(hdx_ev)
            fr03_entry = source_entry(
                "hdx-real", True,
                f"ACLED 公开月度表（HDX 分发）：{month_desc} 完整月 admin1 聚合，滞后约1个月")
        except Exception as e:
            warnings.append(f"HDX 月度表不可用 → fr03 按段基准: {e}")
            fr03_entry = source_entry("baseline", False, "HDX 月度表不可用 → 段基准")

    # ---- CT05 / CT06（GDELT 主源 + Google News RSS 备源；"关闭"须≥2独立信源佐证才触发禁售） ----
    ct05_map, ct06_map, ev5, ev6, mode5, mode6 = fetch_nodes_and_ports(
        gap=float(os.environ.get("GDELT_GAP", "10")))
    evidence["ct05"] = ev5
    evidence["ct06"] = ev6
    for cid in CORRIDOR_IDS:
        corridors[cid]["ct05"] = ct05_map.get(cid, BASELINE["ct05"])
        corridors[cid]["ct06"] = ct06_map.get(cid, BASELINE["ct06"])
    ct05_entry = source_entry(
        mode5, mode5 != "baseline",
        {"gdelt-news": "GDELT 新闻检索（全走廊合并单查）",
         "gnews-rss": "Google News RSS 备源（GDELT 限流时兜底）",
         "baseline": "双源（GDELT/RSS）均失败 → 基准档"}[mode5])
    ct06_entry = source_entry(
        mode6, mode6 != "baseline",
        {"gdelt-news": "GDELT 新闻检索（全口岸单查）",
         "gnews-rss": "Google News RSS 备源（GDELT 限流时兜底）",
         "baseline": "双源（GDELT/RSS）均失败 → 基准档"}[mode6])

    # ---- ST-01 每日建议（advisory：转移须人工批准+留痕，本管道不改 segments.json） ----
    st_sugg = {}
    for cid in CORRIDOR_IDS:
        c = corridors[cid]
        st_sugg[cid] = {
            "suggestion": st_suggestion_level(c["ct04"], c["ct05"], c["ct06"]),
            "basis": f"ct04={c['ct04']}, ct05={c['ct05']}, ct06={c['ct06']}",
        }

    snap = {
        "date": day.isoformat(),
        "generated_at": datetime.now(TZ8).isoformat(timespec="seconds"),
        "pipeline_version": PIPELINE_VERSION,
        "corridors": {cid: corridors[cid] for cid in CORRIDOR_IDS},
        "evidence": evidence,
        "st_suggestion": st_sugg,
    }
    validate_snapshot(snap)  # 不过即抛错，中止发布
    fr15_entry = source_entry(
        "openmeteo" if fr15_fail < len(CORRIDOR_IDS) else "baseline",
        fr15_fail < len(CORRIDOR_IDS),
        f"Open-Meteo 72h降雨 {len(CORRIDOR_IDS) - fr15_fail}/{len(CORRIDOR_IDS)} 走廊实时评分"
        if fr15_fail < len(CORRIDOR_IDS) else "抓取全部失败 → 基准档")
    sources = {"fr15": fr15_entry, "fr03": fr03_entry, "ct04": ct04_entry,
               "ct05": ct05_entry, "ct06": ct06_entry}
    return snap, warnings, sources


def write_audit_md(snap: dict, warnings: list[str], path: Path) -> None:
    lines = [
        f"# 信息因子快照审计 · {snap['date']}",
        "",
        f"- 生成时间: {snap['generated_at']}（UTC+8）　管线版本: {snap['pipeline_version']}",
        "- 纪律: AI 只做证据抽取与初判，出分=评分卡规则（factor_tables.json → rating_cards）；"
        "本文件+git 提交历史即为评级变更留痕。",
        "",
        "| 走廊 | 名称 | fr03 治安 | fr15 天气 | ct04 波动 | ct05 节点 | ct06 口岸 |",
        "|---|---|---|---|---|---|---|",
    ]
    for cid in CORRIDOR_IDS:
        c = snap["corridors"][cid]
        lines.append(
            f"| {cid} | {CORRIDOR_NAMES[cid]} | {c['fr03']} | {c['fr15']} | {c['ct04']} | {c['ct05']} | {c['ct06']} |"
        )
    lines += ["", "## 证据", ""]
    for factor, evs in snap["evidence"].items():
        for e in evs:
            lines.append(f"- **{factor}** [{e['source']}] {e['note']}  \n  {e['url']}")
    if warnings:
        lines += ["", "## 告警", ""] + [f"- {w}" for w in warnings]
    if "st_suggestion" in snap:
        lines += [
            "", "## ST-01 人工定级参考（每日建议·不自动生效）", "",
            "| 走廊 | 信号建议 | 依据 |",
            "|---|---|---|",
        ]
        for cid in CORRIDOR_IDS:
            s = snap["st_suggestion"][cid]
            lines.append(f"| {cid} | {s['suggestion']} | {s['basis']} |")
        lines += [
            "",
            "判定口径：证实遇袭/桥毁封锁(ct05/ct06=关闭)→S3；冲突骤增(ct04=3)或节点遇袭收紧→S2；其余→S1。",
            "**转移须人工批准+留痕**（评分卡 ST01）；本建议不修改 segments.json，批准后由模型权威侧更新段档案。",
            "段档案当前档位以 `the-seikcha/database/model-core/segments.json` 为准（本管道不复制其数值）。",
        ]
    lines += ["", "## 披露", "",
              "- 媒体沉默≠安全：无证据走廊按基准档处理，不解读为安全。",
              "- ct05/ct06 来自 GDELT 新闻检索+关键词规则初判，\"关闭\"级须≥2独立域名佐证；证据 URL 见上。",
              "- 媒体滞后性：报道延迟意味着评级变化可能滞后于实况。",
              ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    ap = argparse.ArgumentParser(description="SEIKCHA 每日信息因子快照")
    ap.add_argument("--date", help="业务日期 YYYY-MM-DD（默认=今天 UTC+8）")
    ap.add_argument("--mock-acled", action="store_true", help="强制 ACLED mock 模式")
    ap.add_argument("--root", help="仓库根目录（默认=本文件上级的上级）")
    ap.add_argument("--copy-to", help="额外把 snapshots/ 复制到该目录（如 webapp/public/snapshots）")
    args = ap.parse_args()

    day = date.fromisoformat(args.date) if args.date else business_date_today()
    root = Path(args.root).resolve() if args.root else Path(__file__).resolve().parent.parent
    snap_dir = root / "snapshots"
    audit_dir = root / "audit"
    snap_dir.mkdir(parents=True, exist_ok=True)
    audit_dir.mkdir(parents=True, exist_ok=True)

    t0 = time.time()
    snap, warnings, sources = build_snapshot(day, mock_acled=args.mock_acled)

    out = snap_dir / f"{snap['date']}.json"
    out.write_text(json.dumps(snap, ensure_ascii=False, indent=2), encoding="utf-8")
    (snap_dir / "latest.json").write_text(json.dumps(snap, ensure_ascii=False, indent=2), encoding="utf-8")
    write_audit_md(snap, warnings, audit_dir / f"{snap['date']}.md")
    try:
        status_path, history_path = write_status_files(
            root, snap, sources, warnings, time.time() - t0)
        print(f"OK 状态页数据: {status_path.name}, {history_path.name}")
    except Exception as e:  # 状态页是展示层，绝不阻塞快照发布
        print(f"  ⚠ 状态文件生成失败（不影响快照发布）: {e}")
    if args.copy_to:
        dst = Path(args.copy_to)
        dst.mkdir(parents=True, exist_ok=True)
        shutil.copy2(out, dst / out.name)
        shutil.copy2(snap_dir / "latest.json", dst / "latest.json")

    print(f"OK 快照已发布: {out}")
    for cid in CORRIDOR_IDS:
        c = snap["corridors"][cid]
        print(f"  {cid} {CORRIDOR_NAMES[cid]:<14} fr03={c['fr03']:<4} fr15={c['fr15']:<3} "
              f"ct04={c['ct04']} ct05={c['ct05']} ct06={c['ct06']}")
    for f, s in sources.items():
        flag = "✓" if s["ok"] else "✗"
        print(f"  [{flag}] {f}  {s['label']} — {s['detail']}")
    for w in warnings:
        print(f"  ⚠ {w}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
