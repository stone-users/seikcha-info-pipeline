# ============================================================
# fetch_acled.py — FR03 治安热度 / CT04 冲突波动供数（ACLED）
# ACLED 2024 后改为 OAuth 账号密码认证（acledR 同款流程，无 key）：
#   POST https://acleddata.com/oauth/token  (grant_type=password, client_id=acled)
#   GET  https://acleddata.com/api/acled/read?_format=json  (Authorization: Bearer)
# 两条现实约束（2026-10 实测）：
#   ① acleddata.com 全站被 Cloudflare 托管质询拦截，纯服务端 HTTP 客户端（urllib/curl/
#      curl_cffi chrome 指纹）均 403——只有真浏览器能过。因此服务端 OAuth 请求失败时
#      **必须**优雅降级到 GDELT，不得重试硬闯；
#   ② 免费档账号有"最近12个月数据封存"（date_recency），近期事件需申请全量访问
#      （access@acleddata.com，学术免费）。
# 因此供数优先级：
#   ① 浏览器辅助缓存 cache/acled_events_cache.json（agent 驱动登录浏览器页内导出的
#      90 天 slim 事件，绕 CF 且绕封存——取决于账号权限）；
#   ② OAuth 直连（网络环境不受 CF 拦截时可用）；
#   ③ 都不行 → 返回 stats=None，由 build_snapshot 落 GDELT 分支。
# 口径：FR03=走廊 admin1 非武装事件近30日计数（月化）；CT04 r=近7日÷(近90日×7/90)。
# 分类词表（fetch 层证据初判，可校准）；score 层阈值不动。
# ============================================================
import json
import os
import random
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, timedelta
from pathlib import Path

from corridors import CORRIDOR_ADMIN1, CORRIDOR_IDS

OAUTH_URL = "https://acleddata.com/oauth/token"
READ_URL = "https://acleddata.com/api/acled/read?_format=json"
CACHE_PATH = Path(__file__).resolve().parent.parent / "cache" / "acled_events_cache.json"

ARMED_KEYWORDS = (
    "battle", "explosion", "remote violence", "violence against civil",
    "airstrike", "air/drone strike", "shelling", "drone strike", "grenade", "ied",
)
NONARMED_KEYWORDS = (
    "theft", "robbery", "extortion", "riot", "mob", "protest", "strike", "looting",
)


class AcledUnavailable(RuntimeError):
    """ACLED 不可达（Cloudflare 拦截/凭证失效等）——调用方应降级而非重试。"""


def _classify(event_type: str) -> str:
    t = (event_type or "").lower()
    if any(k in t for k in ARMED_KEYWORDS):
        return "armed"
    if any(k in t for k in NONARMED_KEYWORDS):
        return "nonarmed"
    return "other"


# ---- ① 浏览器辅助缓存 ----

def _load_cache(day: date) -> tuple[list[dict], str] | None:
    """读浏览器导出的事件缓存；覆盖窗口完整且非空才可用。返回 (events, note) 或 None。"""
    if not CACHE_PATH.exists():
        return None
    try:
        c = json.loads(CACHE_PATH.read_text(encoding="utf-8"))
        events = c.get("events") or []
        win = c.get("window") or ["", ""]
        if not events:
            return None
        if not (win[0] <= (day - timedelta(days=90)).isoformat() and win[1] >= day.isoformat()):
            return None
        note = (f"浏览器辅助缓存（{c.get('fetched_at', '?')} 抓取，窗口 {win[0]}~{win[1]}，"
                f"{len(events)} 条事件）")
        return events, note
    except (json.JSONDecodeError, OSError, KeyError):
        return None


# ---- ② OAuth 直连 ----

def _oauth_token(email: str, password: str) -> str:
    body = urllib.parse.urlencode({
        "grant_type": "password", "client_id": "acled",
        "username": email, "password": password, "scope": "",
    }).encode()
    req = urllib.request.Request(OAUTH_URL, data=body, headers={
        "Content-Type": "application/x-www-form-urlencoded",
        "Accept": "application/json",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) seikcha-info-pipeline/1.0",
    })
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            tj = json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        raise AcledUnavailable(f"oauth/token HTTP {e.code}（Cloudflare 质询或凭证错误）") from e
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError) as e:
        raise AcledUnavailable(f"oauth/token 网络失败: {e}") from e
    tok = tj.get("access_token")
    if not tok:
        raise AcledUnavailable(f"oauth/token 响应无 access_token: {sorted(tj.keys())}")
    return tok


def _fetch_events(day: date, email: str, password: str) -> list[dict]:
    start = (day - timedelta(days=90)).isoformat()
    url = (f"{READ_URL}&country=Myanmar"
           f"&event_date={start}|{day.isoformat()}&event_date_where=BETWEEN&limit=0")
    tok = _oauth_token(email, password)
    req = urllib.request.Request(url, headers={
        "Authorization": f"Bearer {tok}",
        "Accept": "application/json",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) seikcha-info-pipeline/1.0",
    })
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            data = json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        raise AcledUnavailable(f"acled/read HTTP {e.code}") from e
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError) as e:
        raise AcledUnavailable(f"acled/read 网络失败: {e}") from e
    if not isinstance(data, dict) or "data" not in data:
        raise AcledUnavailable(f"acled/read 响应结构异常: {str(data)[:120]}")
    return data["data"]


# ---- 聚合（缓存与 OAuth 共用；纯逻辑，tests/test_aggregation.py 覆盖） ----

def _aggregate(events: list[dict], day: date) -> tuple[dict[str, dict], str]:
    """按走廊聚合 → {corr: {nonarmed_30d, armed_7d, armed_90d}} + 数据说明。"""
    admin_to_corrs: dict[str, list[str]] = {}
    for corr, names in CORRIDOR_ADMIN1.items():
        for n in names:
            admin_to_corrs.setdefault(n.lower(), []).append(corr)

    stats = {c: {"nonarmed_30d": 0, "armed_7d": 0, "armed_90d": 0} for c in CORRIDOR_IDS}
    d30 = day - timedelta(days=30)
    d7 = day - timedelta(days=7)  # "近7日"=day-6..day（严格7天，与 fetch_gdelt 口径一致）
    matched = 0
    for ev in events:
        admin = (ev.get("admin1") or "").strip().lower()
        corrs = admin_to_corrs.get(admin)
        if not corrs:
            continue
        matched += 1
        try:
            ed = date.fromisoformat(str(ev.get("event_date", ""))[:10])
        except ValueError:
            continue
        kind = _classify(ev.get("event_type", ""))
        for c in corrs:
            if kind == "armed":
                stats[c]["armed_90d"] += 1
                if ed > d7:
                    stats[c]["armed_7d"] += 1
            elif kind == "nonarmed" and ed >= d30:
                stats[c]["nonarmed_30d"] += 1
    note = f"ACLED 90日窗口事件 {len(events)} 条，命中走廊 admin1 {matched} 条"
    return stats, note


def _mock_stats(day: date) -> tuple[dict[str, dict], str]:
    """确定性伪数据（种子=日期），仅 --mock-acled 联调用。"""
    rng = random.Random(f"acled-mock-{day.isoformat()}")
    stats = {}
    for c in CORRIDOR_IDS:
        stats[c] = {
            "nonarmed_30d": rng.randint(0, 40),
            "armed_7d": rng.randint(0, 8),
            "armed_90d": rng.randint(20, 120),
        }
    return stats, "MOCK 数据（--mock-acled 端到端联调用；禁止对外宣称实时）"


# ---- 入口 ----

def fetch_security(day: date, mock: bool = False) -> tuple[dict[str, dict] | None, list[dict], str]:
    """返回 (stats|None, evidence, mode)。
    mode: mock / acled-cache / acled-oauth / fallback-gdelt / no-credentials。
    stats=None → 调用方落 GDELT 分支（evidence 里已写明原因）。"""
    if mock:
        stats, note = _mock_stats(day)
        return stats, [{"source": "ACLED(mock)", "url": READ_URL, "note": note}], "mock"

    cache = _load_cache(day)
    if cache is not None:
        events, note = cache
        stats, agg_note = _aggregate(events, day)
        return stats, [{"source": "ACLED（浏览器辅助缓存）", "url": "cache/acled_events_cache.json",
                        "note": f"{note}；{agg_note}"}], "acled-cache"

    email = os.environ.get("ACLED_EMAIL", "").strip()
    password = os.environ.get("ACLED_PASSWORD", "").strip()
    if email and password:
        try:
            events = _fetch_events(day, email, password)
            stats, agg_note = _aggregate(events, day)
            return stats, [{"source": "ACLED（OAuth）", "url": READ_URL,
                            "note": f"{agg_note}"}], "acled-oauth"
        except AcledUnavailable as e:
            return None, [{"source": "ACLED", "url": READ_URL,
                           "note": f"OAuth 直连不可用已降级 GDELT：{e}"}], "fallback-gdelt"

    return None, [{"source": "ACLED", "url": "https://acleddata.com/",
                    "note": "未配置 ACLED_EMAIL/ACLED_PASSWORD（且无浏览器缓存）→ GDELT 分支"}], "no-credentials"
