# ============================================================
# validate.py — 快照 schema 校验（与 webapp/src/engine/types.ts 的 InfoSnapshot 严格对齐）
# 非法取值 = 报错不发布（宁缺毋错）。
# ============================================================
from corridors import CORRIDOR_IDS

FR03_ALLOWED = {"段基准", "低", "中", "高", "极高"}
FR15_ALLOWED = {"好", "平", "暴雨", "极端"}
CT04_ALLOWED = {0, 1, 2, 3}
CT05_ALLOWED = {"正常", "常规", "收紧", "关闭"}
CT06_ALLOWED = {"通畅", "正常", "拥堵", "关闭"}


def validate_snapshot(snap: dict) -> None:
    """校验快照结构；任何违例抛 ValueError（调用方据此中止发布）。"""
    if not isinstance(snap, dict):
        raise ValueError("快照必须是 dict")
    for key in ("date", "generated_at", "pipeline_version", "corridors"):
        if key not in snap:
            raise ValueError(f"快照缺少字段: {key}")
    if not (len(snap["date"]) == 10 and snap["date"][4] == "-" and snap["date"][7] == "-"):
        raise ValueError(f"date 必须是 YYYY-MM-DD: {snap['date']!r}")
    corridors = snap["corridors"]
    if set(corridors.keys()) != set(CORRIDOR_IDS):
        raise ValueError(f"corridors 键必须恰为 {CORRIDOR_IDS}: {sorted(corridors.keys())}")
    for cid, c in corridors.items():
        for f, allowed in (
            ("fr03", FR03_ALLOWED),
            ("fr15", FR15_ALLOWED),
            ("ct05", CT05_ALLOWED),
            ("ct06", CT06_ALLOWED),
        ):
            if c.get(f) not in allowed:
                raise ValueError(f"走廊{cid} {f} 非法取值: {c.get(f)!r}（允许 {sorted(allowed)}）")
        if c.get("ct04") not in CT04_ALLOWED:
            raise ValueError(f"走廊{cid} ct04 非法取值: {c.get('ct04')!r}（允许 0|1|2|3）")
    ev = snap.get("evidence", {})
    if not isinstance(ev, dict):
        raise ValueError("evidence 必须是 dict")
    # st_suggestion 为可选附加字段（ST-01 人工定级的每日建议，站点端忽略）
    if "st_suggestion" in snap:
        ssg = snap["st_suggestion"]
        if not isinstance(ssg, dict) or set(ssg.keys()) != set(CORRIDOR_IDS):
            raise ValueError(f"st_suggestion 键必须恰为 {CORRIDOR_IDS}")
        for cid, item in ssg.items():
            if not isinstance(item, dict) or item.get("suggestion") not in {"S0", "S1", "S2", "S3"}:
                raise ValueError(f"st_suggestion[{cid}] 非法: {item!r}")


def validate_corridor_entry(entry: dict) -> bool:
    """网站侧同规则的走廊条目校验（供参考；网站端在 infoSnapshot.ts 内独立实现）。"""
    try:
        for f, allowed in (
            ("fr03", FR03_ALLOWED), ("fr15", FR15_ALLOWED),
            ("ct05", CT05_ALLOWED), ("ct06", CT06_ALLOWED),
        ):
            if entry.get(f) not in allowed:
                return False
        return entry.get("ct04") in CT04_ALLOWED
    except Exception:
        return False
