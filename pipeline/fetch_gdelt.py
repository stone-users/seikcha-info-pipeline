# ============================================================
# fetch_gdelt.py — CT04 冲突波动无 key 备源（GDELT DOC 2.0 API，免注册）
# 定位：ACLED 凭证缺失时的降级源。ct04 的输入是"近7日÷近90日基线"的**比值**，
#   比值对计量单位不敏感（事件数或媒体覆盖强度均可），因此 GDELT 的
#   timelinevol 覆盖量序列可直接代入同一评分卡，不需要任何重新标定。
#   fr03（月化事件数）是绝对计数，媒体覆盖份额不可比 → 不用 GDELT 出 fr03，
#   无 ACLED 时 fr03 按段基准回退（引擎取段档案档）。
# 口径与纪律：
#   - 查询 = 走廊沿线城市英文名 × 武装冲突关键词 × sourcelang:eng；
#   - 媒体沉默≠安全：90日内非零信号 < MIN_NONZERO_DAYS → 视为无信号，落基准档并留痕；
#   - GDELT 限流严格（429）：单走廊串行 + 间隔 + 递增退避，每日 8 次请求在配额内；
#   - 证据 note 记录查询词、7日/90日窗口覆盖和、r 值——留痕可复核。
# ============================================================
import json
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, timedelta

from score import score_ct04

API = "https://api.gdeltproject.org/api/v2/doc/doc"
ARMED = "(clash OR airstrike OR shelling OR ambush OR artillery OR offensive)"
MIN_NONZERO_DAYS = 5  # 90日窗口内非零天数低于此 → 无信号（媒体沉默≠安全）
URL_SHORT = "https://api.gdeltproject.org/api/v2/doc/doc?mode=timelinevol"

# 走廊查询词：城市英文名（与 cities.ts en 字段一致；显式列出，可审计）
CORRIDOR_QUERY = {
    "A": '"Myawaddy" OR "Kawkareik" OR "Hpa-an" OR "Thaton" OR "Kyaikto"',
    "B": '"Naypyidaw" OR "Meiktila" OR "Mandalay"',
    "C": '"Muse" OR "Lashio" OR "Kutkai" OR "Kyaukme"',
    "D": '"Shwebo" OR "Ye-U" OR "Katha" OR "Myitkyina"',
    "E": '"Pathein" OR "Hline"',
    "F": '"Dawei" OR "Myeik" OR "Mawlamyine"',
    "G": '"Kyaukpyu" OR "Ann" OR "Magway"',
    "H": '"Lweje" OR "Bhamo"',
}


def _get_timeline(query: str) -> list[dict] | None:
    """timelinevol 序列（约90日×每日覆盖强度）；429/空响应退避重试，最终失败返回 None。
    退避 5/10/20s：快速失败优于长挂（用户口径），全走廊最坏 ~3 分钟封顶。"""
    url = f"{API}?query={urllib.parse.quote(query)}&mode=timelinevol&timespan=3m&format=json"
    delays = [5, 10, 20]
    for attempt in range(4):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 seikcha-info-pipeline/1.0"})
            with urllib.request.urlopen(req, timeout=30) as r:
                data = json.loads(r.read().decode("utf-8"))
            return data["timeline"][0]["data"]
        except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError, OSError,
                KeyError, IndexError, ValueError) as e:
            if attempt == 3:
                return None
            time.sleep(delays[attempt])
    return None


def ratio_from_series(points: list[dict], day: date) -> tuple[float | None, int, float, float]:
    """(r, 非零天数, 7日和, 90日和)。无信号（非零天数<MIN 或 90日和=0）→ r=None。
    r = sum7 / (mean_per_day * 7)，mean_per_day = sum90 / n（n=序列天数）。
    纯函数，tests/test_gdelt.py 覆盖。"""
    d7 = day - timedelta(days=7)  # "近7日"=day-6..day（严格7天）
    s7 = 0.0
    s90 = 0.0
    nonzero = 0
    for p in points:
        raw = str(p.get("date", ""))
        try:
            pd_ = date.fromisoformat(f"{raw[0:4]}-{raw[4:6]}-{raw[6:8]}")
        except ValueError:
            continue
        v = float(p.get("value", 0) or 0)
        s90 += v
        if v > 0:
            nonzero += 1
        if pd_ > d7:
            s7 += v
    if nonzero < MIN_NONZERO_DAYS or s90 <= 0:
        return None, nonzero, s7, s90
    mean_daily = s90 / max(len(points), 1)
    denom = mean_daily * 7
    if denom <= 0:
        return None, nonzero, s7, s90
    return s7 / denom, nonzero, s7, s90


def corridor_ct04(corr: str, day: date) -> tuple[int | None, list[dict]]:
    """走廊 ct04 档 + 证据。返回 (档位|None, evidence)；None=无信号/抓取失败 → 调用方落基准档。"""
    cities = CORRIDOR_QUERY.get(corr)
    if not cities:
        return None, [{"source": "GDELT", "url": URL_SHORT, "note": f"走廊 {corr} 无查询词映射"}]
    query = f"({cities}) {ARMED} sourcelang:eng"
    points = _get_timeline(query)
    if points is None:
        return None, [{"source": "GDELT", "url": URL_SHORT,
                       "note": f"抓取失败（限流/网络），走廊{corr} ct04 本日落基准档。query={query}"}]
    r, nonzero, s7, s90 = ratio_from_series(points, day)
    if r is None:
        return None, [{"source": "GDELT", "url": URL_SHORT,
                       "note": f"媒体信号不足（90日非零{nonzero}天<{MIN_NONZERO_DAYS}），走廊{corr} ct04 落基准档（媒体沉默≠安全）。query={query}"}]
    level = score_ct04(r)
    baseline7 = s90 / max(len(points), 1) * 7
    return level, [{"source": "GDELT", "url": URL_SHORT,
                    "note": f"走廊{corr} 近7日覆盖和={s7:.4f} ÷ 基线折算7日={baseline7:.4f} → r={r:.2f} → ct04={level}（媒体覆盖代理口径）。query={query}"}]
