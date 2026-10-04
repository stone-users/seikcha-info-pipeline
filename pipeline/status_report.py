# ============================================================
# status_report.py — 每日运行状态报告（GitHub Pages 状态页数据层）
# 产物：
#   status/status.json   今日运行状态（各数据源链路级别/成败/告警/耗时 + 今日评分 + ST-01 建议 + 证据）
#   status/history.json  近30天历史摘要（从 snapshots/*.json 派生，每日一行）
# 纪律：状态文件生成失败不得阻塞快照发布（调用方 try/except）；
#       历史派生只读快照 evidence，不改评分。
# ============================================================
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

TZ8 = timezone(timedelta(hours=8))
HISTORY_DAYS = 30
SOURCES = ("fr15", "fr03", "ct04", "ct05", "ct06")

MODE_LABELS = {
    "openmeteo": "Open-Meteo 实时",
    "hdx-real": "ACLED 公开月度表（HDX）",
    "acled-oauth": "ACLED 官方（OAuth）",
    "acled-cache": "ACLED（浏览器缓存）",
    "mock": "MOCK 联调数据",
    "gdelt-proxy": "GDELT 媒体代理",
    "gdelt-news": "GDELT 新闻检索",
    "gnews-rss": "Google News RSS 备源",
    "baseline": "基准档兜底",
}

# 状态页配色档：real=真实数据(绿) / degraded=降级链仍真实(琥珀) / fallback=兜底或联调(红)
_REAL = ("openmeteo", "acled-oauth", "hdx-real")
_DEGRADED = ("acled-cache", "gdelt-proxy", "gdelt-news", "gnews-rss")


def mode_grade(mode: str) -> str:
    if mode in _REAL:
        return "real"
    if mode in _DEGRADED:
        return "degraded"
    return "fallback"


def mode_label(mode: str) -> str:
    return MODE_LABELS.get(mode, mode)


def source_entry(mode: str, ok: bool, detail: str) -> dict:
    """单数据源状态条目（build_snapshot 组装今日 sources 用）。"""
    return {"mode": mode, "ok": bool(ok), "grade": mode_grade(mode),
            "label": mode_label(mode), "detail": detail}


def derive_modes(snap: dict) -> dict[str, str]:
    """从快照 evidence 派生各因子数据链路级别（用于历史回溯；今日运行用显式 sources 更精确）。"""
    ev = snap.get("evidence") or {}
    modes: dict[str, str] = {}

    fr15 = ev.get("fr15") or []
    modes["fr15"] = ("openmeteo"
                     if any(e.get("note", "").startswith("未来72h") for e in fr15)
                     else "baseline")

    fr03 = " ".join(e.get("source", "") for e in (ev.get("fr03") or []))
    if "HDX" in fr03:
        fr03m = "hdx-real"
    elif "OAuth" in fr03:
        fr03m = "acled-oauth"
    elif "缓存" in fr03:
        fr03m = "acled-cache"
    elif "mock" in fr03.lower():
        fr03m = "mock"
    else:
        fr03m = "baseline"
    modes["fr03"] = fr03m

    ct04 = ev.get("ct04") or []
    if fr03m in ("acled-oauth", "acled-cache", "mock"):
        modes["ct04"] = fr03m
    elif any("GDELT" in e.get("source", "") for e in ct04):
        modes["ct04"] = "gdelt-proxy"
    else:
        modes["ct04"] = "baseline"

    for f in ("ct05", "ct06"):
        es = ev.get(f) or []
        modes[f] = ("gdelt-news" if any(e.get("source") == "GDELT" for e in es)
                    else "gnews-rss" if any(e.get("source") == "Google News RSS" for e in es)
                    else "baseline")
    return modes


def st_max(snap: dict) -> str:
    """全走廊 ST-01 建议最高档（S3>S2>S1>S0）。"""
    order = {"S0": 0, "S1": 1, "S2": 2, "S3": 3}
    best = "S0"
    for s in (snap.get("st_suggestion") or {}).values():
        v = s.get("suggestion")
        if v in order and order[v] > order[best]:
            best = v
    return best


def build_status(snap: dict, sources: dict, warnings: list[str], duration_s: float) -> dict:
    """今日状态 dict（status.json 内容）。"""
    return {
        "date": snap["date"],
        "generated_at": snap["generated_at"],
        "pipeline_version": snap["pipeline_version"],
        "run": {"duration_s": round(float(duration_s), 1), "warnings": list(warnings)},
        "sources": {f: sources[f] for f in SOURCES},
        "corridors": snap["corridors"],
        "st_suggestion": snap.get("st_suggestion", {}),
        "evidence": snap.get("evidence", {}),
    }


def build_history(snapshots_dir: Path, days: int = HISTORY_DAYS) -> dict:
    """聚合快照目录 → 近 N 天历史（按日期升序取末尾）。坏文件跳过不阻塞。"""
    rows: list[dict] = []
    for p in sorted(snapshots_dir.glob("????-??-??.json")):
        try:
            snap = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if not isinstance(snap, dict) or not isinstance(snap.get("corridors"), dict):
            continue
        rows.append({
            "date": snap.get("date") or p.stem,
            "sources": derive_modes(snap),
            "levels": snap["corridors"],
            "st_max": st_max(snap),
        })
    return {
        "generated_at": datetime.now(TZ8).isoformat(timespec="seconds"),
        "days": rows[-days:],
    }


def write_status_files(root: Path, snap: dict, sources: dict,
                       warnings: list[str], duration_s: float) -> tuple[Path, Path]:
    """写 status/status.json + status/history.json；返回文件路径（IO 异常向上抛，调用方兜底）。"""
    status_dir = root / "status"
    status_dir.mkdir(parents=True, exist_ok=True)
    status_path = status_dir / "status.json"
    history_path = status_dir / "history.json"
    status_path.write_text(
        json.dumps(build_status(snap, sources, warnings, duration_s),
                   ensure_ascii=False, indent=2),
        encoding="utf-8")
    history_path.write_text(
        json.dumps(build_history(root / "snapshots"), ensure_ascii=False, indent=2),
        encoding="utf-8")
    return status_path, history_path
