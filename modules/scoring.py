"""出钓指数评分模型（可解释加权模型）。

评分维度与权重：
    气压水平   0.20
    气压趋势   0.20
    水温适配   0.25
    风力       0.15
    云量       0.10
    月相       0.10

每个维度输出 0~1 的分值，加权后归一化为 0~100 的出钓指数，
并给出可读的加分/减分理由，保证结论「可解释」而非黑箱。
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

WEIGHTS = {
    "pressure": 0.20,
    "trend": 0.20,
    "water_temp": 0.25,
    "wind": 0.15,
    "cloud": 0.10,
    "moon": 0.10,
}

# 常见鱼种适温与偏好
SPECIES_PROFILE = {
    "通用": {"temp_ideal": (16, 26), "temp_ok": (8, 32), "wind_ideal": (2.0, 5.0)},
    "鲫鱼": {"temp_ideal": (12, 22), "temp_ok": (4, 30), "wind_ideal": (1.5, 4.5)},
    "鲤鱼": {"temp_ideal": (16, 26), "temp_ok": (8, 32), "wind_ideal": (2.0, 5.0)},
    "草鱼": {"temp_ideal": (20, 30), "temp_ok": (14, 34), "wind_ideal": (2.0, 5.0)},
    "鲢鳙": {"temp_ideal": (22, 32), "temp_ok": (18, 36), "wind_ideal": (1.0, 4.0)},
    "翘嘴": {"temp_ideal": (16, 28), "temp_ok": (10, 32), "wind_ideal": (2.0, 6.0)},
    "黑鱼": {"temp_ideal": (20, 30), "temp_ok": (16, 34), "wind_ideal": (0.5, 4.0)},
    "鲈鱼": {"temp_ideal": (18, 28), "temp_ok": (12, 30), "wind_ideal": (2.0, 6.0)},
}

SPECIES_OPTIONS = list(SPECIES_PROFILE.keys())


def _band_score(value: Optional[float], ideal: Tuple[float, float], ok: Tuple[float, float]) -> float:
    """区间打分：落在 ideal 得 1，落在 ok 内线性衰减，超界快速衰减。"""
    if value is None:
        return 0.5
    lo, hi = ideal
    if lo <= value <= hi:
        return 1.0
    if value < lo:
        span = max(1e-6, lo - ok[0])
        if value >= ok[0]:
            return 0.3 + 0.7 * (value - ok[0]) / span
        return max(0.0, 0.3 - (ok[0] - value) / 10.0)
    span = max(1e-6, ok[1] - hi)
    if value <= ok[1]:
        return 0.3 + 0.7 * (ok[1] - value) / span
    return max(0.0, 0.3 - (value - ok[1]) / 10.0)


def _pressure_score(hpa: Optional[float]) -> Tuple[float, str]:
    if hpa is None:
        return 0.5, "气压数据缺失"
    if 1010 <= hpa <= 1025:
        return 1.0, f"气压 {hpa:.0f} hPa，处于高位，溶氧充足"
    if 1005 <= hpa < 1010:
        return 0.7, f"气压 {hpa:.0f} hPa，略偏低但可钓"
    if hpa > 1025:
        return 0.7, f"气压 {hpa:.0f} hPa 偏高，鱼口可能变谨慎"
    if hpa >= 1000:
        return 0.4, f"气压 {hpa:.0f} hPa 偏低，溶氧不足，鱼易上浮"
    return 0.15, f"气压仅 {hpa:.0f} hPa，明显偏低压，鱼口普遍较差"


def _trend_score(current: Optional[float], later: Optional[float]) -> Tuple[float, str]:
    if current is None or later is None:
        return 0.5, "气压趋势数据缺失"
    delta = later - current
    if abs(delta) <= 1.0:
        return 1.0, f"气压平稳（{delta:+.1f} hPa），鱼情稳定"
    if 1.0 < delta <= 3.0:
        return 0.95, f"气压缓慢上升（{delta:+.1f} hPa），鱼情趋好"
    if -3.0 <= delta < -1.0:
        return 0.8, f"气压缓慢下降（{delta:+.1f} hPa），常有抢食窗口"
    if delta > 3.0:
        return 0.55, f"气压快速上升（{delta:+.1f} hPa），鱼需适应"
    return 0.35, f"气压骤降（{delta:+.1f} hPa），鱼口易紊乱"


def _water_temp_score(water: Optional[float], species: str) -> Tuple[float, str]:
    profile = SPECIES_PROFILE.get(species) or SPECIES_PROFILE["通用"]
    if water is None:
        return 0.5, "水温数据缺失（已按气温估算）"
    score = _band_score(water, profile["temp_ideal"], profile["temp_ok"])
    lo, hi = profile["temp_ideal"]
    if lo <= water <= hi:
        return score, f"估算水温 {water:.1f}℃，正处于{species}最适区间 {lo}–{hi}℃"
    if water < lo:
        return score, f"估算水温 {water:.1f}℃，低于{species}最适区间下限 {lo}℃"
    return score, f"估算水温 {water:.1f}℃，高于{species}最适区间上限 {hi}℃"


def _wind_score(wind: Optional[float], species: str) -> Tuple[float, str]:
    profile = SPECIES_PROFILE.get(species) or SPECIES_PROFILE["通用"]
    if wind is None:
        return 0.5, "风力数据缺失"
    lo, hi = profile["wind_ideal"]
    if lo <= wind <= hi:
        return 1.0, f"风速 {wind:.1f} m/s，微风增氧且便于观漂"
    if wind < lo:
        return 0.55, f"风速 {wind:.1f} m/s，近乎无风，闷热时鱼口偏弱"
    if wind <= hi + 3:
        return 0.6, f"风速 {wind:.1f} m/s，风力偏大，观漂与抛投受影响"
    return 0.25, f"风速 {wind:.1f} m/s，大风天气，不建议出钓"


def _cloud_score(cloud: Optional[float]) -> Tuple[float, str]:
    if cloud is None:
        return 0.5, "云量数据缺失"
    if 30 <= cloud <= 80:
        return 1.0, f"云量 {cloud:.0f}%，散射光条件理想"
    if cloud < 30:
        return 0.55, f"云量 {cloud:.0f}%，日照强烈，鱼易离底避光"
    return 0.75, f"云量 {cloud:.0f}%，阴天，多数鱼种摄食积极"


def _moon_score(phase: Dict[str, Any]) -> Tuple[float, str]:
    illum = phase.get("illumination", 0.5)
    if illum >= 0.9 or illum <= 0.1:
        return 1.0, f"月相{phase.get('name')}（大潮期），鱼类摄食活跃度偏高"
    if 0.35 <= illum <= 0.65:
        return 0.65, f"月相{phase.get('name')}（小潮期），影响中性"
    return 0.8, f"月相{phase.get('name')}，影响中性偏好"


def score_conditions(
    current: Dict[str, Any],
    water_temp: Optional[float],
    phase: Dict[str, Any],
    species: str = "通用",
    pressure_later: Optional[float] = None,
) -> Dict[str, Any]:
    """对一组条件打分，返回总分、分项明细与理由列表。"""
    parts: List[Tuple[str, float, str]] = [
        ("气压水平", *_pressure_score(current.get("pressure"))),
        ("气压趋势", *_trend_score(current.get("pressure"), pressure_later)),
        ("水温适配", *_water_temp_score(water_temp, species)),
        ("风力", *_wind_score(current.get("wind"), species)),
        ("云量", *_cloud_score(current.get("cloud"))),
        ("月相", *_moon_score(phase)),
    ]
    keys = ["pressure", "trend", "water_temp", "wind", "cloud", "moon"]
    total = 0.0
    details = []
    for key, (label, sub, reason) in zip(keys, parts):
        weight = WEIGHTS[key]
        total += sub * weight
        details.append(
            {"维度": label, "得分": round(sub * 100), "权重": weight, "说明": reason}
        )

    score = round(total * 100)
    return {
        "score": score,
        "level": level_of(score),
        "details": details,
        "reasons": [d["说明"] for d in details],
    }


def level_of(score: int) -> str:
    if score >= 80:
        return "极佳"
    if score >= 65:
        return "良好"
    if score >= 50:
        return "一般"
    if score >= 35:
        return "较差"
    return "不宜"


def best_windows(
    rows: List[Dict[str, Any]],
    water_temp: Optional[float],
    phase: Dict[str, Any],
    species: str,
    top_n: int = 3,
) -> List[Dict[str, Any]]:
    """在逐时数据上滑窗评分，找出最佳作钓时段。"""
    scored: List[Dict[str, Any]] = []
    for i, row in enumerate(rows):
        later = rows[i + 3]["pressure"] if i + 3 < len(rows) else None
        res = score_conditions(row, water_temp, phase, species, later)
        ts = row.get("time")
        label = ts[11:16] if isinstance(ts, str) and len(ts) >= 16 else str(ts)
        scored.append({"time": label, "score": res["score"], "raw": ts})

    # 以 3 小时窗口求均值，选窗口得分最高的不重叠时段
    windows: List[Dict[str, Any]] = []
    for i in range(0, max(0, len(scored) - 2)):
        chunk = scored[i : i + 3]
        avg = sum(c["score"] for c in chunk) / len(chunk)
        windows.append(
            {
                "start": chunk[0]["time"],
                "end": chunk[-1]["time"],
                "score": round(avg),
            }
        )
    windows.sort(key=lambda w: w["score"], reverse=True)

    picked: List[Dict[str, Any]] = []
    used = set()
    for w in windows:
        idx = int(w["start"][:2])
        if any(abs(idx - u) < 3 for u in used):
            continue
        used.add(idx)
        picked.append(w)
        if len(picked) >= top_n:
            break
    picked.sort(key=lambda w: w["start"])
    return picked
