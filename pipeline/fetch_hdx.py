# ============================================================
# fetch_hdx.py — FR03 治安因子供数（ACLED 官方公开月度表 · 联合国 HDX 分发）
# 来源：data.humdata.org "Myanmar - Conflict Events"（ACLED 官方维护，
#       免账号免 key，月度更新，Admin1/Admin2 × 月粒度事件计数）
# 口径：取数据中最近的完整月，Admin1 聚合"示威/骚乱（非武装）"事件数 →
#       corridors.py 的 CORRIDOR_ADMIN1 映射到走廊 → score.score_fr03 打档。
# 滞后披露：文件 as-of 滞后约 1 个月（FR03 评分卡=月化计数，粒度一致）。
# 缓存：cache/hdx_demo.xlsx（下载失败时用过期缓存，仍优于无数据）。
# ============================================================
import json
import urllib.request
import xml.etree.ElementTree as ET
import zipfile
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from corridors import CORRIDOR_ADMIN1, CORRIDOR_IDS
import score

HDX_PACKAGE_API = "https://data.humdata.org/api/3/action/package_show?id=myanmar-acled-conflict-data"
DEMO_RESOURCE_KEY = "demonstration"   # 非武装（示威/骚乱）月度表
UA = "Mozilla/5.0 seikcha-info-pipeline/1.0 (academic project)"
TZ8 = timezone(timedelta(hours=8))

MONTHS = {m: i + 1 for i, m in enumerate(
    ["January", "February", "March", "April", "May", "June",
     "July", "August", "September", "October", "November", "December"])}
NS = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"


def _http_get(url: str, timeout: int = 30) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def resolve_demo_url() -> str:
    """从 HDX API 动态解析示威事件月度表的当前下载 URL（as-of 日期会变，不能写死）。"""
    data = json.loads(_http_get(HDX_PACKAGE_API).decode("utf-8"))
    for r in data.get("result", {}).get("resources", []):
        if DEMO_RESOURCE_KEY in (r.get("name") or "").lower():
            return r["url"]
    raise RuntimeError("HDX 数据集中未找到 demonstration 资源")


def _download(url: str, cache_path: Path) -> None:
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    body = _http_get(url, timeout=60)
    if len(body) < 10000:
        raise RuntimeError(f"HDX 下载异常（{len(body)} 字节）")
    cache_path.write_bytes(body)


def parse_events_rows(xlsx_bytes: bytes) -> list[list[str]]:
    """标准库解析 XLSX（仅 inlineStr/v 单元格），返回数据 sheet 的行（含表头）。"""
    import io
    with zipfile.ZipFile(io.BytesIO(xlsx_bytes)) as z:
        shared: list[str] = []
        if "xl/sharedStrings.xml" in z.namelist():
            root = ET.fromstring(z.read("xl/sharedStrings.xml"))
            for si in root.findall(f"{NS}si"):
                shared.append("".join(t.text or "" for t in si.iter(f"{NS}t")))
        for sheet in sorted(n for n in z.namelist() if n.startswith("xl/worksheets/sheet")):
            rows: list[list[str]] = []
            for row in ET.fromstring(z.read(sheet)).iter(f"{NS}row"):
                cells: list[str] = []
                for c in row.findall(f"{NS}c"):
                    if c.get("t") == "inlineStr":
                        is_el = c.find(f"{NS}is")
                        cells.append("".join(t.text or "" for t in is_el.iter(f"{NS}t")) if is_el is not None else "")
                    else:
                        v = c.find(f"{NS}v")
                        cells.append(v.text if v is not None else "")
                rows.append(cells)
            if rows and "Admin1" in rows[0] and "Events" in rows[0]:  # 跳过授权说明 sheet
                return rows
    raise RuntimeError("XLSX 中未找到含 Admin1/Events 表头的数据 sheet")


def latest_full_month(rows: list[list[str]]) -> tuple[int, int]:
    """数据中最近完整月 → (year, month)。"""
    best = (0, 0)
    for r in rows[1:]:
        if len(r) < 9:
            continue
        m, y = MONTHS.get(r[6]), r[7]
        if m and y.isdigit():
            key = (int(y), m)
            if key > best:
                best = key
    if best == (0, 0):
        raise RuntimeError("月度表中未解析到任何 (Month, Year)")
    return best


def aggregate_month(rows: list[list[str]], year: int, month: int) -> dict[str, int]:
    """指定月的 Admin1 非武装事件合计。"""
    out: dict[str, int] = {}
    for r in rows[1:]:
        if len(r) < 9 or r[6] not in MONTHS or not r[7].isdigit():
            continue
        if int(r[7]) != year or MONTHS[r[6]] != month:
            continue
        try:
            n = int(float(r[8] or 0))
        except ValueError:
            continue
        a1 = (r[1] or "").strip()
        out[a1] = out.get(a1, 0) + n
    return out


def corridor_month_counts(admin1_counts: dict[str, int]) -> dict[str, int]:
    """Admin1 计数 → 走廊计数（同 CORRIDOR_ADMIN1 映射；一省可命中多走廊，如实重复计入）。"""
    admin_to_corrs: dict[str, list[str]] = {}
    for corr, names in CORRIDOR_ADMIN1.items():
        for n in names:
            admin_to_corrs.setdefault(n.lower(), []).append(corr)
    out = {c: 0 for c in CORRIDOR_IDS}
    for a1, n in admin1_counts.items():
        for corr in admin_to_corrs.get(a1.lower(), []):
            out[corr] += n
    return out


def fetch_fr03_monthly(cache_dir: Path) -> tuple[dict[str, int], list[dict], str]:
    """返回 (各走廊最近完整月非武装事件数, evidence, 月份描述 'YYYY-MM')。
    下载失败但有缓存 → 用缓存；两者皆失败 → 抛异常（调用方落段基准）。"""
    cache = cache_dir / "hdx_demo.xlsx"
    url = ""
    try:
        url = resolve_demo_url()
        _download(url, cache)
        src = "HDX 实时下载"
    except Exception as e:
        if not cache.exists():
            raise RuntimeError(f"HDX 下载失败且无缓存: {e}") from e
        src = f"HDX 本地缓存（下载失败: {e}）"
    rows = parse_events_rows(cache.read_bytes())
    year, month = latest_full_month(rows)
    admin1_counts = aggregate_month(rows, year, month)
    counts = corridor_month_counts(admin1_counts)
    matched = sum(admin1_counts.values())
    ev = [{
        "source": "ACLED 公开月度表（联合国HDX分发）",
        "url": url or "cache/hdx_demo.xlsx",
        "note": (f"{year}-{month:02d} 完整月非武装（示威/骚乱）事件：全国 admin1 合计 {matched} 条，"
                 f"映射走廊后 " + "、".join(f"{c}={counts[c]}" for c in CORRIDOR_IDS)
                 + f"；来源 {src}，月度粒度滞后约1个月（与 FR03 评分卡月化口径一致）"),
    }]
    return counts, ev, f"{year}-{month:02d}"


def score_fr03_from_counts(counts: dict[str, int]) -> dict[str, str]:
    """走廊计数 → 档位字典（score.score_fr03 规则出分）。"""
    return {c: score.score_fr03(counts.get(c, 0)) for c in CORRIDOR_IDS}
