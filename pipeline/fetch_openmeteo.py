# ============================================================
# fetch_openmeteo.py — FR15 天气因子供数（Open-Meteo，免 key，结构化 API）
# 逻辑：走廊沿线全部城市节点（去重后全局批量，单次请求）取未来72h逐时降雨(mm)
#       → 按走廊取沿线最大累积降雨（最不利点，保守口径）→ score.score_fr15 打档。
# 证据：每走廊记录 最大值城市/毫米数/请求URL。
# ============================================================
from corridors import CITY_COORDS
from net import get_json
import score

API_URL = (
    "https://api.open-meteo.com/v1/forecast"
    "?latitude={lats}&longitude={lons}"
    "&hourly=precipitation&forecast_days=3&forecast_hours=72&timezone=Asia%2FYangon"
)


def fetch_rain72_by_city(city_ids: list[str]) -> tuple[dict[str, float], str]:
    """返回 ({city_id: 未来72h累积降雨mm}, 请求URL)。单次批量请求。"""
    unique_ids = sorted(set(city_ids))
    unknown = [c for c in unique_ids if c not in CITY_COORDS]
    if unknown:
        raise ValueError(f"cities.ts 中不存在的城市ID: {unknown}")
    lats = ",".join(str(CITY_COORDS[c][1]) for c in unique_ids)
    lons = ",".join(str(CITY_COORDS[c][2]) for c in unique_ids)
    url = API_URL.format(lats=lats, lons=lons)
    data = get_json(url)
    # 多坐标批量 → 返回数组；单坐标返回对象（此处恒为批量数组）
    items = data if isinstance(data, list) else [data]
    if len(items) != len(unique_ids):
        raise RuntimeError(f"Open-Meteo 返回位置数不符: 请求{len(unique_ids)} 返回{len(items)}")
    rain: dict[str, float] = {}
    for cid, item in zip(unique_ids, items):
        series = (item.get("hourly") or {}).get("precipitation")
        if series is None:
            raise RuntimeError(f"Open-Meteo 响应缺少 hourly.precipitation（城市 {cid}）")
        vals = [float(v) for v in series if v is not None]
        rain[cid] = round(sum(vals), 1)
    return rain, url


def corridor_fr15(corr: str, city_ids: list[str]) -> tuple[str | None, list[dict]]:
    """走廊 fr15 档位 + 证据条目。返回 (档位|None, evidence)；失败降级由调用方兜底。"""
    url_base = API_URL.split("?")[0]
    try:
        rain_by_city, url = fetch_rain72_by_city(city_ids)
    except Exception as e:  # 网络失败 → 返回 None（build_snapshot 落基准档并留痕）
        return None, [{"source": "Open-Meteo", "url": url_base,
                       "note": f"抓取失败，本日该走廊按基准档: {e}"}]
    worst_city = max(rain_by_city, key=lambda c: rain_by_city[c])
    worst_mm = rain_by_city[worst_city]
    level = score.score_fr15(worst_mm)
    zh = CITY_COORDS[worst_city][0]
    ev = [{
        "source": "Open-Meteo",
        "url": url,
        "note": f"未来72h沿线最不利点 {zh} 累积降雨 {worst_mm}mm → {level}（沿线{len(set(city_ids))}城取最大）",
    }]
    return level, ev
