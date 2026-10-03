# ============================================================
# fetch_news.py — CT05 节点安全 / CT06 口岸运行供数（二期·真实新闻源）
# 方案：GDELT DOC artlist（免 key 结构化新闻检索，与 fetch_gdelt 同源限流策略）
#       + 确定性关键词规则初判（AI 只做证据抽取与初判，出分=评分卡规则）。
# 纪律与保守口径：
#   - 媒体沉默≠安全：无证据 = 中性基准档（ct05='常规' / ct06='正常'）；
#     "通畅/正常0.7档"需正面证据，不因没报道而降保费；
#   - 反假新闻："关闭"（触发整段禁售）须 ≥2 个独立域名佐证；单源只到"收紧/拥堵"；
#   - 每条信号留痕：文章标题+域名+URL 进 evidence，人工可复核。
# 评分卡（factor_tables.json → rating_cards，阈值不得改）：
#   CT05: 无异常→正常0.7 | 常规→1.0 | 遇袭未断行→收紧1.5 | 桥毁封锁→关闭(暂停)
#   CT06: 快速→通畅0.8 | 正常→1.0 | 长队限量→拥堵1.6 | 关闭→暂停
# ============================================================
import time
import urllib.parse

from net import get_json

API = "https://api.gdeltproject.org/api/v2/doc/doc"
URL_SHORT = "https://api.gdeltproject.org/api/v2/doc/doc?mode=artlist"

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

# ---- CT05 走廊基础设施遇袭检索词（城市=corridors.py；此处显式列出可审计）----
CORRIDOR_CITY_TERMS = {
    "A": '("Myawaddy" OR "Kawkareik" OR "Hpa-an" OR "Thaton" OR "Kyaikto")',
    "B": '("Naypyidaw" OR "Meiktila" OR "Mandalay")',
    "C": '("Muse" OR "Lashio" OR "Kutkai" OR "Kyaukme")',
    "D": '("Shwebo" OR "Katha" OR "Myitkyina")',
    "E": '("Pathein" OR "Hline")',
    "F": '("Dawei" OR "Myeik" OR "Mawlamyine")',
    "G": '("Kyaukpyu" OR "Ann" OR "Magway")',
    "H": '("Lweje" OR "Bhamo")',
}
CT05_INFRA = '(bridge OR checkpoint OR highway OR road OR "supply route")'
CT05_DESTROY = ("destroyed", "blown up", "collapsed", "demolish", "severed")
CT05_BLOCK = ("blocked", "closed", "cut off", "shut")
CT05_ATTACK = ("attacked", "ambush", "struck", "damaged", "seized", "overrun", "clash")


def _artlist(query: str, maxrecords: int = 75) -> list[dict] | None:
    """GDELT artlist：[{url,title,domain,seendate,...}]；失败返回 None（调用方落基准档）。"""
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


def _title_hit(title: str, terms: tuple[str, ...]) -> bool:
    t = title.lower()
    return any(k in t for k in terms)


# ---- 纯规则函数（tests/test_news_rules.py 覆盖） ----

def score_ct06_port(domains_close: set[str], domains_queue: set[str]) -> str:
    """单口岸：关闭≥2独立域名 | 拥堵≥1 | 否则正常（中性）。"""
    if len(domains_close) >= 2:
        return "关闭"
    if len(domains_close) >= 1 or len(domains_queue) >= 1:
        return "拥堵"
    return "正常"


def score_ct05_corridor(domains_destroy: set[str], domains_attack: set[str]) -> str:
    """单走廊：桥毁/阻断≥2独立域名→关闭 | 遇袭/受损≥1→收紧 | 否则常规（中性）。"""
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


# ---- 抓取编排 ----

def fetch_nodes_and_ports(gap: float = 10.0) -> tuple[dict[str, str], dict[str, str], list[dict], list[dict]]:
    """返回 (ct05_by_corridor, ct06_by_corridor, evidence_ct05, evidence_ct06)。
    2+N 次 GDELT 调用（1 全口岸 + 8 走廊），串行+间隔防限流。"""
    ct05: dict[str, str] = {}
    ct06: dict[str, str] = {}
    ev5: list[dict] = []
    ev6: list[dict] = []

    # ---- CT06：单次全口岸查询，按标题内口岸词归类 ----
    all_port_terms = sorted({t for terms in PORT_TERMS.values() for t in terms})
    q6 = (f"({ ' OR '.join('\"%s\"' % t for t in all_port_terms) }) {CT06_CONTEXT} "
          f"({' OR '.join(sorted(set(CT06_CLOSE + CT06_QUEUE + ('reopen',))))}) sourcelang:eng")
    arts6 = _artlist(q6)
    if arts6 is None:
        ev6.append({"source": "GDELT", "url": URL_SHORT,
                    "note": "口岸新闻抓取失败（限流/网络）→ ct06 全口岸落基准档 '正常'"})
    else:
        per_port = {pid: {"close": set(), "queue": set(), "reopen": set(), "arts": []} for pid in PORT_TERMS}
        for a in arts6:
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
        for pid, info in per_port.items():
            level = score_ct06_port(info["close"], info["queue"])
            zh = {"PT-01": "妙瓦底", "PT-02": "木姐", "PT-03": "雷基", "PT-04": "清水河-滚弄", "PT-05": "丹老/高当"}[pid]
            refs = " ; ".join(f"{a['domain']}: {a['title'][:70]} ({a['url']})" for a in info["arts"][:3]) or "无报道"
            ev6.append({"source": "GDELT", "url": URL_SHORT,
                        "note": f"口岸{zh} 72h：关停域名{len(info['close'])} 拥堵域名{len(info['queue'])} "
                                f"重开域名{len(info['reopen'])} → {level}。{refs}"})
            for cid, pids in CORRIDOR_PORTS.items():
                if pid in pids:
                    ct06[cid] = level

    time.sleep(gap)  # CT06 与 CT05 查询之间隔开（GDELT 限流）

    # ---- CT05：逐走廊基础设施遇袭查询（串行+间隔） ----
    for i, (cid, cities) in enumerate(CORRIDOR_CITY_TERMS.items()):
        if i > 0:
            time.sleep(gap)
        q5 = f"{cities} {CT05_INFRA} ({' OR '.join(sorted(set(CT05_DESTROY + CT05_BLOCK + CT05_ATTACK)))}) {ARMED} sourcelang:eng"
        arts5 = _artlist(q5)
        if arts5 is None:
            ev5.append({"source": "GDELT", "url": URL_SHORT,
                        "note": f"走廊{cid} 基础设施新闻抓取失败 → ct05 落基准档 '常规'"})
            ct05[cid] = "常规"
            continue
        destroy, attack, arts_hit = set(), set(), []
        for a in arts5:
            title = a.get("title") or ""
            dom = a.get("domain") or ""
            if _title_hit(title, CT05_DESTROY):
                destroy.add(dom); arts_hit.append(a)
            elif _title_hit(title, CT05_BLOCK):
                destroy.add(dom); arts_hit.append(a)
            elif _title_hit(title, CT05_ATTACK):
                attack.add(dom); arts_hit.append(a)
        level = score_ct05_corridor(destroy, attack)
        ct05[cid] = level
        refs = " ; ".join(f"{a['domain']}: {a['title'][:70]} ({a['url']})" for a in arts_hit[:3]) or "无报道"
        ev5.append({"source": "GDELT", "url": URL_SHORT,
                    "note": f"走廊{cid} 72h：毁阻域名{len(destroy)} 遇袭域名{len(attack)} → {level}。{refs}"})

    # 未覆盖走廊（无口岸/无信号）→ 中性基准
    for cid in CORRIDOR_CITY_TERMS:
        ct05.setdefault(cid, "常规")
        ct06.setdefault(cid, "正常")
    return ct05, ct06, ev5, ev6
