# ============================================================
# score.py — 评分卡规则引擎（唯一出分点）
# 阈值唯一权威 = the-seikcha/database/model-core/factor_tables.json → rating_cards：
#   FR03: 月化非武装事件数 <5→低 | 5-15→中 | 15-30→高 | >30→极高
#   FR15: 未来72h预报降雨(mm) <10→好 | 10-50→平 | 50-150→暴雨 | >150→极端
#   CT04: r=近7日武装事件÷近90日均值 <0.7→0 | 0.7-1.5→1 | 1.5-3→2 | >3→3
# 纪律（05_data_sources.md）：AI/爬虫只做证据抽取与初判；出分只走本文件的确定性规则。
# 边界归属约定（对卡面文字的显式化，tests/test_score.py 全覆盖）：
#   FR03: [0,5)低 | [5,15)中 | [15,30]高 | (30,∞)极高
#   FR15: [0,10)好 | [10,50)平 | [50,150]暴雨 | (150,∞)极端
#   CT04: [0,0.7)→0 | [0.7,1.5)→1 | [1.5,3]→2 | (3,∞)→3
# ============================================================

FR03_LEVELS = ["低", "中", "高", "极高"]
FR15_LEVELS = ["好", "平", "暴雨", "极端"]
CT04_LEVELS = [0, 1, 2, 3]


def score_fr03(monthly_nonarmed: float) -> str:
    """月化非武装事件数 → 治安热度档。负数/非数直接抛错（宁缺毋错）。"""
    if not isinstance(monthly_nonarmed, (int, float)) or isinstance(monthly_nonarmed, bool):
        raise ValueError(f"FR03 输入非法: {monthly_nonarmed!r}")
    if monthly_nonarmed < 0:
        raise ValueError(f"FR03 事件数不能为负: {monthly_nonarmed}")
    if monthly_nonarmed < 5:
        return "低"
    if monthly_nonarmed < 15:
        return "中"
    if monthly_nonarmed <= 30:
        return "高"
    return "极高"


def score_fr15(rain72_mm: float) -> str:
    """未来72h预报降雨(mm) → 天气档。"""
    if not isinstance(rain72_mm, (int, float)) or isinstance(rain72_mm, bool):
        raise ValueError(f"FR15 输入非法: {rain72_mm!r}")
    if rain72_mm < 0:
        raise ValueError(f"FR15 降雨不能为负: {rain72_mm}")
    if rain72_mm < 10:
        return "好"
    if rain72_mm < 50:
        return "平"
    if rain72_mm <= 150:
        return "暴雨"
    return "极端"


def score_ct04(ratio_r: float) -> int:
    """近7日武装事件÷近90日日均 → 冲突波动档(0-3)。"""
    if not isinstance(ratio_r, (int, float)) or isinstance(ratio_r, bool):
        raise ValueError(f"CT04 输入非法: {ratio_r!r}")
    if ratio_r < 0:
        raise ValueError(f"CT04 比值不能为负: {ratio_r}")
    if ratio_r < 0.7:
        return 0
    if ratio_r < 1.5:
        return 1
    if ratio_r <= 3:
        return 2
    return 3


# ---- 缺数据时的基准档（必须与 webapp INFO_DEFAULTS 逐字一致，HANDOFF §4.1）----
# 注意 CT05 基准是 '常规'(系数1.0) 而非 '正常'(0.7)：无证据=中性，不得因"没数据"降保费。
BASELINE = {
    "fr03": "段基准",   # 引擎语义：回退到各段档案治安档
    "fr15": "平",
    "ct04": 1,
    "ct05": "常规",
    "ct06": "正常",
}
