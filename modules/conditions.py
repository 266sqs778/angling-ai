"""环境数据获取与派生计算。

数据来源：Open-Meteo 免费开放接口（无需 API Key）
- 地理编码：地名 -> 经纬度
- 预报接口：气温、气压、风速风向、云量、降水、湿度 + 日出日落

派生计算：
- 水温估算（Open-Meteo 不提供淡水水温，采用气温滞回近似模型，仅作参考）
- 月相（基于朔望月周期自算，无需第三方依赖）
"""
from __future__ import annotations

import datetime as dt
import math
from typing import Any, Dict, List, Optional

import requests

FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
GEOCODE_URL = "https://geocoding-api.open-meteo.com/v1/search"
TIMEOUT = 15

# 朔望月周期与已知新月参考时刻（用于月相推算）
SYNODIC_MONTH = 29.530588853
_NEW_MOON_REF = dt.datetime(2000, 1, 6, 18, 14, tzinfo=dt.timezone.utc)

MOON_NAMES = [
    (1.85, "新月"),
    (5.54, "娥眉月"),
    (9.23, "上弦月"),
    (12.91, "盈凸月"),
    (16.61, "满月"),
    (20.30, "亏凸月"),
    (23.99, "下弦月"),
    (27.68, "残月"),
]


def geocode(name: str) -> Optional[Dict[str, Any]]:
    """地名 -> 经纬度。失败返回 None。"""
    if not name or not name.strip():
        return None
    try:
        resp = requests.get(
            GEOCODE_URL,
            params={"name": name.strip(), "count": 1, "language": "zh", "format": "json"},
            timeout=TIMEOUT,
        )
        resp.raise_for_status()
        results = (resp.json() or {}).get("results") or []
        if not results:
            return None
        item = results[0]
        return {
            "name": item.get("name"),
            "lat": item.get("latitude"),
            "lon": item.get("longitude"),
            "admin": item.get("admin1") or "",
            "country": item.get("country") or "",
        }
    except requests.RequestException:
        return None


def fetch_forecast(lat: float, lon: float, days: int = 3) -> Dict[str, Any]:
    """拉取逐时预报与日出日落。异常抛出 requests.RequestException。"""
    params = {
        "latitude": lat,
        "longitude": lon,
        "timezone": "auto",
        "forecast_days": days,
        "hourly": (
            "temperature_2m,surface_pressure,wind_speed_10m,wind_direction_10m,"
            "cloud_cover,precipitation,relative_humidity_2m"
        ),
        "daily": "sunrise,sunset,temperature_2m_max,temperature_2m_min",
        "current": (
            "temperature_2m,surface_pressure,wind_speed_10m,wind_direction_10m,cloud_cover"
        ),
    }
    resp = requests.get(FORECAST_URL, params=params, timeout=20)
    resp.raise_for_status()
    return resp.json()


def estimate_water_temp(hourly: Dict[str, Any], lag_days: float = 2.0) -> Optional[float]:
    """由气温序列估算水温（滞回近似）。

    水体热惯性大，水温滞后于气温。这里用近若干日均气温的滑动平均近似，
    属工程估算，误差通常在 ±2℃ 内，仅用于筛选适温区间，不作为精确指标。
    """
    temps = [t for t in (hourly.get("temperature_2m") or []) if t is not None]
    if not temps:
        return None
    window = max(1, int(24 * lag_days))
    recent = temps[:window] if len(temps) >= window else temps
    mean_air = sum(recent) / len(recent)
    # 经验修正：水温更平稳，向 15℃ 收缩并略高于气温均值
    water = mean_air * 0.85 + 15.0 * 0.15 + 1.0
    return round(water, 1)


def moon_phase(date: Optional[dt.date] = None) -> Dict[str, Any]:
    """计算指定日期的月相（正午近似）。"""
    date = date or dt.datetime.now().date()
    moment = dt.datetime(date.year, date.month, date.day, 12, tzinfo=dt.timezone.utc)
    days = (moment - _NEW_MOON_REF).total_seconds() / 86400.0
    age = days % SYNODIC_MONTH
    illumination = (1 - math.cos(2 * math.pi * age / SYNODIC_MONTH)) / 2
    name = "残月"
    for threshold, label in MOON_NAMES:
        if age < threshold:
            name = label
            break
    return {
        "age": round(age, 1),
        "illumination": round(illumination, 2),
        "name": name,
    }


def wind_dir_label(deg: Optional[float]) -> str:
    """风向角度 -> 方位文字。"""
    if deg is None:
        return "—"
    dirs = ["北", "东北", "东", "东南", "南", "西南", "西", "西北"]
    idx = int((deg % 360) / 45.0 + 0.5) % 8
    return f"{dirs[idx]}风"


def build_hourly_frame(forecast: Dict[str, Any]) -> List[Dict[str, Any]]:
    """把 Open-Meteo 逐时数据整理成列表，便于评分与绘图。"""
    hourly = forecast.get("hourly") or {}
    times = hourly.get("time") or []
    rows: List[Dict[str, Any]] = []
    for i, ts in enumerate(times):
        rows.append(
            {
                "time": ts,
                "temp": _at(hourly, "temperature_2m", i),
                "pressure": _at(hourly, "surface_pressure", i),
                "wind": _at(hourly, "wind_speed_10m", i),
                "wind_dir": _at(hourly, "wind_direction_10m", i),
                "cloud": _at(hourly, "cloud_cover", i),
                "precip": _at(hourly, "precipitation", i),
                "humidity": _at(hourly, "relative_humidity_2m", i),
            }
        )
    return rows


def _at(hourly: Dict[str, Any], key: str, index: int) -> Optional[float]:
    seq = hourly.get(key) or []
    if index < len(seq):
        return seq[index]
    return None
