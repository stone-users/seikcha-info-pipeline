# ============================================================
# corridors.py — 走廊定义（权威来源：the-seikcha/database/02_route_network.md 表1/表2）
# 城市坐标复制自 webapp/src/data/cities.ts（同源，禁止在此重造数值）。
# 走廊 A~H 为权威段走廊；假设联络段（W/N/S）不参与信息层评分。
# ============================================================

# 城市坐标 (lat, lon)——与 cities.ts CITIES 表逐一对应
CITY_COORDS = {
    "myawaddy":     ("妙瓦底",   16.72,  98.51),
    "kawkareik":    ("高加力",   16.53,  98.79),
    "hpaan":        ("帕安",     16.89,  97.63),
    "thaton":       ("直通",     16.92,  97.37),
    "kyaikto":      ("斋托",     17.28,  97.03),
    "bago":         ("勃固",     17.34,  96.48),
    "yangon":       ("仰光",     16.87,  96.20),
    "thilawa":      ("仰光港(迪拉瓦)", 16.63, 96.28),
    "hline":        ("莱河",     16.85,  95.35),
    "pathein":      ("勃生",     16.78,  94.73),
    "pyay":         ("卑谬",     19.82,  95.22),
    "myingyan":     ("敏建",     21.46,  95.02),
    "naypyidaw":    ("内比都",   19.76,  96.08),
    "meiktila":     ("密铁拉",   20.88,  95.86),
    "taunggyi":     ("东枝",     20.78,  96.45),
    "mandalay":     ("曼德勒",   21.98,  96.08),
    "shwebo":       ("瑞保",     22.57,  95.99),
    "yeu":          ("耶乌",     22.85,  95.62),
    "kachinborder": ("克钦界",   24.05,  96.05),
    "katha":        ("卡塔",     24.14,  96.35),
    "shwegu":       ("杰沙",     24.08,  96.42),
    "myitkyina":    ("密支那",   25.38,  97.40),
    "bhamo":        ("八莫",     24.26,  96.94),
    "lweje":        ("雷基",     24.32,  97.42),
    "kyaukme":      ("皎迈",     22.60,  97.03),
    "lashio":       ("腊戌",     22.94,  97.75),
    "kutkai":       ("贵慨",     23.05,  98.10),
    "muse":         ("木姐",     23.99,  97.75),
    "chinshwehaw":  ("清水河-滚弄", 23.95, 98.70),
    "mawlamyine":   ("毛淡棉",   16.48,  97.63),
    "dawei":        ("土瓦",     14.09,  98.20),
    "myeik":        ("丹老",     12.44,  98.60),
    "kyaukpyu":     ("皎漂",     19.42,  93.53),
    "ann":          ("安",       18.95,  94.30),
    "magway":       ("马圭",     20.28,  94.93),
}

# 走廊 → 沿线城市节点（= ROUTE_POLYS 中该走廊各段 nodes 的并集）
CORRIDOR_CITIES = {
    "A": ["myawaddy", "kawkareik", "hpaan", "thaton", "kyaikto", "bago", "yangon", "thilawa"],
    "B": ["yangon", "bago", "naypyidaw", "meiktila", "mandalay"],
    "C": ["mandalay", "kyaukme", "lashio", "kutkai", "muse"],
    "D": ["mandalay", "shwebo", "yeu", "kachinborder", "katha", "myitkyina"],
    "E": ["yangon", "hline", "pathein"],
    "F": ["yangon", "mawlamyine", "dawei", "myeik"],
    "G": ["kyaukpyu", "ann", "magway"],
    "H": ["lweje", "bhamo", "myitkyina"],
}

CORRIDOR_NAMES = {
    "A": "东南线 妙瓦底→仰光",
    "B": "中纵线 仰光→曼德勒",
    "C": "东北线 曼德勒→木姐",
    "D": "西北线 曼德勒→密支那",
    "E": "仰光-勃生",
    "F": "土瓦-丹老",
    "G": "皎漂-马圭",
    "H": "雷基-八莫",
}

# 走廊 → ACLED admin1 一级行政区（大小写不敏感匹配；同义拼写并列以容错）
CORRIDOR_ADMIN1 = {
    "A": ["Kayin", "Mon", "Bago", "Yangon"],
    "B": ["Yangon", "Bago", "Naypyitaw", "Naypyidaw", "Mandalay"],
    "C": ["Mandalay", "Shan"],
    "D": ["Mandalay", "Sagaing", "Kachin"],
    "E": ["Yangon", "Ayeyarwady", "Irrawaddy"],
    "F": ["Yangon", "Bago", "Mon", "Tanintharyi", "Taninthayi"],
    "G": ["Rakhine", "Magway"],
    "H": ["Kachin"],
}

CORRIDOR_IDS = ["A", "B", "C", "D", "E", "F", "G", "H"]
