# ============================================================
# fetch_news.py — CT05 节点安全 / CT06 口岸运行供数（三期·双源架构）
# 主源：GDELT DOC artlist（免 key 结构化新闻检索）
# 备源：Google News RSS（免 key、限流极宽容；GDELT 429 时兜底）
# 出分：确定性关键词规则（AI 只做证据抽取与初判，出分=评分卡规则）。
# 纪律与保守口径：
#   - 媒体沉默≠安全：无证据 = 中性基准档（ct05='常规' / ct06='正常'）；
#     "通畅/正常0.7档"需正面证据，不因没报道而降保费；
#   - 反假新闻："关闭"（触发整段禁售）须 ≥2 个独立信源（域名/出版方）佐证；
#     单源只到"收紧/拥堵"；
#   - 每条信号留痕：文章标题+信源+URL 进 evidence，人工可复核。
# 评分卡（factor_tables.json → rating_cards，阈值不得改）：
#   CT05: 无异常→正常0.7 | 常规→1.0 | 遇袭未断行→收紧1.5 | 桥毁封锁→关闭(暂停)
#   CT06: 快速→通畅0.8 | 正常→1.0 | 长队限量→拥堵1.6 | 关闭→暂停
# 查询预算：每日 2 次 GDELT（ct05 合并单查 + ct06 全口岸单查）+ 至多 2 次 RSS 备胎。
# ============================================================
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime

from net import get_json

API = "https://api.gdeltproject.org/api/v2/doc/doc"
URL_SHORT = "https://api.gdeltproject.org/api/v2/doc/doc?mode=artlist"
GNEWS = "https://news.google.com/rss/search"

ARMED = "(clash OR airstrike OR shelling OR ambush OR artillery OR offensive)"

# ---- CT06 口岸表（02_route_network.md 表2；corridor → 口岸检索词）----
PORT_TERMS = {
    "PT-01": ["Myawaddy", "Kawkareik"],
    "PT-02": ["Muse", "Ruili"],
    "PT-03": ["Lweje"],
    "PT-04": ["Chinshwehaw", "Kyukoke"],
    "PT-05": ["Myeik", "Kawthoung"],
}
CORRIDOR_PORTS = {
    "A": ["PT-01"], "B": [], "C": ["PT-02", "PT-04"], "D": [],
    "E": [], "F": ["PT-05"], "G": [], "H": ["PT-03"],
}
CT06_CONTEXT = '(border OR crossing OR gate OR checkpoint OR trade OR "trade zone")'
CT06_CLOSE = ("closed", "closure", "shutdown", "suspended", "seal", "halt")
CT06_QUEUE = ("queue", "congestion", "restricted", "limit", "backlog", "delay")
CT06_REOPEN = ("reopen", "resum", "back open")

# ---- CT05 走廊城市词（城市=corridors.py；显式列出可审计；列表供标题匹配复用）----
CORRIDOR_CITY_LIST = {
    "A": ["Myawaddy", "Kawkareik", "Hpa-an", "Thaton", "Kyaikto"],
    "B": ["Naypyidaw", "Meiktila", "Mandalay"],
    "C": ["Muse", "Lashio", "Kutkai", "Kyaukme"],
    "D": ["Shwebo", "Katha", "Myitkyina"],
    "E": ["Pathein", "Hline"],
    "F": ["Dawei", "Myeik", "Mawlamyine"],
    "G": ["Kyaukpyu", "Ann", "Magway"],
    "H": ["Lweje", "Bhamo"],
}
CORRIDOR_CITY_TERMS = {
    cid: "(" + " OR ".join(f'"{c}"' for c in cities) + ")"
    for cid, cities in CORRIDOR_CITY_LIST.items()
}
CT05_INFRA = '(bridge OR checkpoint OR highway OR road OR "supply route")'
CT05_DESTROY = ("destroyed", "blown up", "collapsed", "demolish", "severed")
CT05_BLOCK = ("blocked", "closed", "cut off", "shut")
CT05_ATTACK = ("attacked", "ambush", "struck", "damaged", "seized", "overrun", "clash")


def _artlist(query: str, maxrecords: int = 100) -> list[dict] | None:
    """GDELT artlist：[{url,title,domain,seendate,...}]；失败返回 None（调用方走 RSS 备胎）。"""
    url = (f"{API}?query={urllib.parse.quote(query)}&mode=artlist"
           f"&timespan=3d&maxrecords={maxrecords}&format=json&sort=datedesc")
    for attempt in range(3):
        try:
            data = get_json(url)
            arts = data.get("articles") if isinstance(data, dict) else None
            return arts if arts is not None else []
        except Exception:
            if attempt == 2:
                return None
            time.sleep(5 * (attempt + 1))
    return None


def within_72h(rfc822_date: str, now: datetime) -> bool:
    """RSS pubDate（RFC822）是否在 now 起 72 小时内；解析失败视为过期（保守）。"""
    try:
        return (now - parsedate_to_datetime(rfc822_date).astimezone(timezone.utc)) <= timedelta(hours=72)
    except Exception:
        return False


def parse_gnews_rss(xml_text: str, now: datetime | None = None) -> list[dict]:
    """Google News RSS → 标准化文章列表 [{url,title,domain,pubdate}]（72h 内）。
    domain 取 <source> 出版方名（RSS 不给原始域名，出版方名即独立信源单位）。"""
    now = now or datetime.now(timezone.utc)
    out = []
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return out
    for item in root.iter("item"):
        title = (item.findtext("title") or "").strip()
        link = (item.findtext("link") or "").strip()
        pub = (item.findtext("pubDate") or "").strip()
        src_el = item.find("source")
        domain = (src_el.text or "").strip() if src_el is not None and src_el.text else "unknown"
        if not title or not within_72h(pub, now):
            continue
        out.append({"url": link, "title": title, "domain": domain, "pubdate": pub})
    return out


def _gnews_articles(query: str) -> list[dict] | None:
    """Google News RSS 检索；网络失败返回 None（与 artlist 的失败语义一致）。"""
    q = query.replace(" sourcelang:eng", "")
    url = f"{GNEWS}?q={urllib.parse.quote(q)}&hl=en&gl=US&ceid=US:en"
    for attempt in range(2):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 seikcha-info-pipeline/1.0"})
            with urllib.request.urlopen(req, timeout=20) as r:
                return parse_gnews_rss(r.read().decode("utf-8", errors="replace"))
        except Exception:
            if attempt == 1:
                return None
            time.sleep(3)
    return None


def _fetch_articles(query: str) -> tuple[list[dict] | None, str]:
    """双源取文章：GDELT 主 → Google News RSS 备。返回 (文章列表|None, 来源模式)。"""
    arts = _artlist(query)
    if arts is not None:
        return arts, "gdelt-news"
    arts = _gnews_articles(query)
    return (arts, "gnews-rss") if arts is not None else (None, "baseline")


def _title_hit(title: str, terms: tuple[str, ...]) -> bool:
    t = title.lower()
    return any(k in t for k in terms)


def _refs(articles: list[dict]) -> str:
    return " ; ".join(f"{a['domain']}: {a['title'][:70]} ({a['url']})" for a in articles[:3]) or "无报道"


# ---- 纯规则函数（tests/test_news_rules.py 覆盖） ----

def score_ct06_port(domains_close: set[str], domains_queue: set[str]) -> str:
    """单口岸：关闭≥2独立信源 | 拥堵≥1 | 否则正常（中性）。"""
    if len(domains_close) >= 2:
        return "关闭"
    if len(domains_close) >= 1 or len(domains_queue) >= 1:
        return "拥堵"
    return "正常"


def score_ct05_corridor(domains_destroy: set[str], domains_attack: set[str]) -> str:
    """单走廊：桥毁/阻断≥2独立信源→关闭 | 遇袭/受损≥1→收紧 | 否则常规（中性）。"""
    if len(domains_destroy) >= 2:
        return "关闭"
    if len(domains_destroy) >= 1 or len(domains_attack) >= 1:
        return "收紧"
    return "常规"


def st_suggestion_level(ct04: int, ct05: str, ct06: str) -> str:
    """ST-01 建议档（纯信号映射，advisory——转移须人工批准，不改 segments.json）。
    依据评分卡口径"月事件计数+准入+证实遇袭"：证实遇袭/封锁→S3；冲突骤增→S2；其余→S1。"""
    if ct05 == "关闭" or ct06 == "关闭":
        return "S3"
    if ct04 == 3 or ct05 == "收紧":
        return "S2"
    return "S1"


def match_ct06(articles: list[dict]) -> dict[str, dict]:
    """口岸归因（纯函数）：文章按标题口岸词归类 → 各口岸计数与档位。"""
    per_port = {pid: {"close": set(), "queue": set(), "reopen": set(), "arts": []} for pid in PORT_TERMS}
    for a in articles:
        title = a.get("title") or ""
        dom = a.get("domain") or ""
        pid = next((p for p, terms in PORT_TERMS.items()
                    if any(t.lower() in title.lower() for t in terms)), None)
        if pid is None:
            continue
        if _title_hit(title, CT06_CLOSE):
            per_port[pid]["close"].add(dom)
            per_port[pid]["arts"].append(a)
        elif _title_hit(title, CT06_QUEUE):
            per_port[pid]["queue"].add(dom)
            per_port[pid]["arts"].append(a)
        elif _title_hit(title, CT06_REOPEN):
            per_port[pid]["reopen"].add(dom)
            per_port[pid]["arts"].append(a)
    return per_port


def match_ct05(articles: list[dict]) -> dict[str, dict]:
    """走廊归因（纯函数）：文章按标题城市词归类 → 各走廊毁阻/遇袭信源集与档位。"""
    per_corr = {cid: {"destroy": set(), "attack": set(), "arts": []} for cid in CORRIDOR_CITY_LIST}
    for a in articles:
        title = a.get("title") or ""
        dom = a.get("domain") or ""
        for cid, cities in CORRIDOR_CITY_LIST.items():
            if not any(c.lower() in title.lower() for c in cities):
                continue
            if _title_hit(title, CT05_DESTROY) or _title_hit(title, CT05_BLOCK):
                per_corr[cid]["destroy"].add(dom)
                per_corr[cid]["arts"].append(a)
            elif _title_hit(title, CT05_ATTACK):
                per_corr[cid]["attack"].add(dom)
                per_corr[cid]["arts"].append(a)
            break  # 一篇文章只归第一个命中走廊（保守，避免跨走廊重复放大）
    return per_corr


# ---- 抓取编排 ----

PORT_ZH = {"PT-01": "妙瓦底", "PT-02": "木姐", "PT-03": "雷基", "PT-04": "清水河-滚弄", "PT-05": "丹老/高当"}


def fetch_nodes_and_ports(gap: float = 10.0) -> tuple[dict[str, str], dict[str, str], list[dict], list[dict], str, str]:
    """返回 (ct05_by_corridor, ct06_by_corridor, ev5, ev6, mode5, mode6)。
    每日 2 次 GDELT（ct06 全口岸单查 + ct05 全走廊合并单查），GDELT 失败走 RSS 备胎。"""
    ct05: dict[str, str] = {}
    ct06: dict[str, str] = {}
    ev5: list[dict] = []
    ev6: list[dict] = []
    mode5 = mode6 = "baseline"

    # ---- CT06：全口岸单查询 ----
    all_port_terms = sorted({t for terms in PORT_TERMS.values() for t in terms})
    q6 = (f"({ ' OR '.join('\"%s\"' % t for t in all_port_terms) }) {CT06_CONTEXT} "
          f"({' OR '.join(sorted(set(CT06_CLOSE + CT06_QUEUE + ('reopen',))))}) sourcelang:eng")
    arts6, mode6 = _fetch_articles(q6)
    src6 = {"gdelt-news": "GDELT", "gnews-rss": "Google News RSS"}[mode6] if mode6 != "baseline" else ""
    if arts6 is None:
        ev6.append({"source": "GDELT+RSS", "url": URL_SHORT,
                    "note": "口岸新闻双源（GDELT/RSS）均抓取失败 → ct06 全口岸落基准档 '正常'"})
    else:
        mode6_ok = mode6
        for pid, info in match_ct06(arts6).items():
            level = score_ct06_port(info["close"], info["queue"])
            ev6.append({"source": src6, "url": URL_SHORT,
                        "note": f"口岸{PORT_ZH[pid]} 72h：关停信源{len(info['close'])} 拥堵信源{len(info['queue'])} "
                                f"重开信源{len(info['reopen'])} → {level}。{_refs(info['arts'])}"})
            for cid, pids in CORRIDOR_PORTS.items():
                if pid in pids:
                    ct06[cid] = level
        mode6 = mode6_ok

    time.sleep(gap)  # 两次 GDELT 查询之间隔开（限流）

    # ---- CT05：全走廊合并单查询（城市词 OR 起来，本地按标题归因走廊）----
    all_cities = sorted({c for cities in CORRIDOR_CITY_LIST.values() for c in cities})
    q5 = (f"({ ' OR '.join('\"%s\"' % c for c in all_cities) }) {CT05_INFRA} "
          f"({' OR '.join(sorted(set(CT05_DESTROY + CT05_BLOCK + CT05_ATTACK)))}) {ARMED} sourcelang:eng")
    arts5, mode5 = _fetch_articles(q5)
    src5 = {"gdelt-news": "GDELT", "gnews-rss": "Google News RSS"}[mode5] if mode5 != "baseline" else ""
    if arts5 is None:
        ev5.append({"source": "GDELT+RSS", "url": URL_SHORT,
                    "note": "走廊基础设施新闻双源（GDELT/RSS）均抓取失败 → ct05 全走廊落基准档 '常规'"})
    else:
        for cid, info in match_ct05(arts5).items():
            level = score_ct05_corridor(info["destroy"], info["attack"])
            ct05[cid] = level
            ev5.append({"source": src5, "url": URL_SHORT,
                        "note": f"走廊{cid} 72h：毁阻信源{len(info['destroy'])} 遇袭信源{len(info['attack'])} "
                                f"→ {level}。{_refs(info['arts'])}"})

    # 未覆盖走廊（无口岸/无信号）→ 中性基准
    for cid in CORRIDOR_CITY_LIST:
        ct05.setdefault(cid, "常规")
        ct06.setdefault(cid, "正常")
    return ct05, ct06, ev5, ev6, mode5, mode6
