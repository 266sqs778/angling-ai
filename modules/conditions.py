"""环境数据获取与派生计算。

数据来源：Open-Meteo 免费开放接口（无需 API Key）
- 地理编码：地名 -> 经纬度
- 预报接口：气温、气压、风速风向、云量

派生计算：
- 水温估算（Open-Meteo 不提供淡水水温，采用气温滞回近似模型，仅作参考）
- 月相（基于朔望月周期自算，无需第三方依赖）

限流兜底：Open-Meteo 免费额度按出口 IP 限流，云端托管时多个用户共用 IP，容易触发 429。
本模块对失败请求做有限重试，仍失败则回退到本地缓存的最近一次成功数据（标记为 _stale）。
"""
from __future__ import annotations

import datetime as dt
import json
import math
import os
import tempfile
import time
from typing import Any, Dict, List, Optional

import requests

FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
GEOCODE_URL = "https://geocoding-api.open-meteo.com/v1/search"
# 备用源：MET Norway（挪威气象研究所，免费、无需 Key）。Open-Meteo 对云端共享出口 IP 常返回 429。
METNO_URL = "https://api.met.no/weatherapi/locationforecast/2.0/compact"
METNO_UA = "angling-ai-portfolio/1.0 (+https://github.com/266sqs778/angling-ai)"
TIMEOUT = 15

# 限流与缓存参数
RETRY_ATTEMPTS = 3        # 单次请求最多尝试次数
RETRY_BACKOFF = 0.8       # 指数退避基数（秒）
RETRY_WAIT_CAP = 5.0      # 单次等待上限，避免长时间阻塞界面
CACHE_DIR = os.path.join(tempfile.gettempdir(), "angling_ai_cache")
CACHE_MAX_AGE = 7 * 24 * 3600  # 缓存数据最长可用 7 天

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


def _get(
    url: str,
    params: Dict[str, Any],
    timeout: int,
    attempts: int = RETRY_ATTEMPTS,
    headers: Optional[Dict[str, str]] = None,
):
    """带指数退避的 GET：对限流（429）与服务端错误（5xx）重试。

    其它 4xx 视为请求本身有问题，直接抛出、不做无谓重试。
    全部尝试失败后抛出最后一次的异常，由调用方决定降级方式。
    """
    delay = RETRY_BACKOFF
    last: Optional[Exception] = None
    for _ in range(attempts):
        try:
            resp = requests.get(url, params=params, timeout=timeout, headers=headers)
        except requests.RequestException as exc:  # 网络抖动
            last = exc
            time.sleep(delay)
            delay *= 2
            continue
        if resp.status_code in (429, 500, 502, 503, 504):
            last = requests.HTTPError(f"{resp.status_code} {resp.reason}", response=resp)
            retry_after = (resp.headers.get("Retry-After") or "").strip()
            wait = float(retry_after) if retry_after.replace(".", "").isdigit() else delay
            time.sleep(min(wait, RETRY_WAIT_CAP))
            delay *= 2
            continue
        resp.raise_for_status()
        return resp
    raise last or requests.RequestException("request failed")


def _cache_file(key: str) -> str:
    os.makedirs(CACHE_DIR, exist_ok=True)
    return os.path.join(CACHE_DIR, key)


def _save_cache(key: str, payload: Dict[str, Any]) -> None:
    """记录一次成功响应，供后续限流时降级使用。失败不影响主流程。"""
    try:
        with open(_cache_file(key), "w", encoding="utf-8") as fh:
            json.dump(
                {
                    "fetched_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
                    "payload": payload,
                },
                fh,
                ensure_ascii=False,
            )
    except OSError:
        pass


def _load_cache(key: str) -> Optional[Dict[str, Any]]:
    """读取未过期的缓存，并补上 _stale 标记；无可用缓存时返回 None。"""
    try:
        with open(_cache_file(key), "r", encoding="utf-8") as fh:
            blob = json.load(fh)
        fetched_at = dt.datetime.fromisoformat(blob["fetched_at"])
        age = (dt.datetime.now(dt.timezone.utc) - fetched_at).total_seconds()
        if age > CACHE_MAX_AGE:
            return None
        payload = dict(blob["payload"])
        payload["_stale"] = {"fetched_at": blob["fetched_at"], "age_minutes": int(age // 60)}
        return payload
    except (OSError, KeyError, ValueError, TypeError):
        return None


def _local_offset_hours(lon: float) -> int:
    """由经度粗估时区偏移（备用源只给 UTC 时间，需转成本地时间用于展示）。"""
    return max(-12, min(14, int(round(lon / 15.0))))


def _fetch_metno(lat: float, lon: float, days: int = 3) -> Dict[str, Any]:
    """备用数据源：MET Norway 小时级预报。返回结构与 Open-Meteo 对齐。

    注意：其气压取的是海平面气压（air_pressure_at_sea_level），与 Open-Meteo 的
    站点气压口径不同，海拔较高的钓点会略微偏高。
    """
    resp = _get(METNO_URL, {"lat": lat, "lon": lon}, timeout=20, headers={"User-Agent": METNO_UA})
    series = ((resp.json() or {}).get("properties") or {}).get("timeseries") or []
    series = series[: max(24, days * 24)]
    if not series:
        raise requests.RequestException("met.no 未返回有效数据")

    tz = dt.timezone(dt.timedelta(hours=_local_offset_hours(lon)))
    hourly: Dict[str, List[Any]] = {
        "time": [],
        "temperature_2m": [],
        "surface_pressure": [],
        "wind_speed_10m": [],
        "wind_direction_10m": [],
        "cloud_cover": [],
    }
    for entry in series:
        details = (((entry.get("data") or {}).get("instant") or {}).get("details")) or {}
        moment = dt.datetime.fromisoformat(entry["time"].replace("Z", "+00:00")).astimezone(tz)
        hourly["time"].append(moment.strftime("%Y-%m-%dT%H:%M"))
        hourly["temperature_2m"].append(details.get("air_temperature"))
        hourly["surface_pressure"].append(details.get("air_pressure_at_sea_level"))
        hourly["wind_speed_10m"].append(details.get("wind_speed"))
        hourly["wind_direction_10m"].append(details.get("wind_from_direction"))
        hourly["cloud_cover"].append(details.get("cloud_area_fraction"))

    return {
        "hourly": hourly,
        "current": {
            "temperature_2m": hourly["temperature_2m"][0],
            "surface_pressure": hourly["surface_pressure"][0],
            "wind_speed_10m": hourly["wind_speed_10m"][0],
            "wind_direction_10m": hourly["wind_direction_10m"][0],
            "cloud_cover": hourly["cloud_cover"][0],
        },
    }


def geocode(name: str) -> Optional[Dict[str, Any]]:
    """地名 -> 经纬度。失败返回 None。"""
    if not name or not name.strip():
        return None
    try:
        resp = _get(
            GEOCODE_URL,
            {"name": name.strip(), "count": 1, "language": "zh", "format": "json"},
            TIMEOUT,
            attempts=2,
        )
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
    """拉取逐时预报与当前实况。

    依次尝试 Open-Meteo → 备用源 met.no → 本地缓存，任一环节成功即返回。
    只请求评分与界面真正用到的变量，并统一风速为 m/s，降低单次调用权重。
    返回体中 `_source` 标记数据来源；`_stale`（仅缓存降级时出现）标记数据获取时间。
    """
    params = {
        "latitude": lat,
        "longitude": lon,
        "timezone": "auto",
        "forecast_days": days,
        "wind_speed_unit": "ms",
        "hourly": (
            "temperature_2m,surface_pressure,wind_speed_10m,wind_direction_10m,cloud_cover"
        ),
        "current": (
            "temperature_2m,surface_pressure,wind_speed_10m,wind_direction_10m,cloud_cover"
        ),
    }
    key = f"forecast_{round(lat, 3)}_{round(lon, 3)}_{days}.json"
    try:
        payload = _get(FORECAST_URL, params, timeout=20).json()
        source = "open-meteo"
    except requests.RequestException as primary_err:
        try:
            payload = _fetch_metno(lat, lon, days)
            source = "met.no"
        except requests.RequestException as backup_err:
            cached = _load_cache(key)
            if cached is None:
                raise requests.RequestException(
                    f"所有数据源均不可用（Open-Meteo: {primary_err}；met.no: {backup_err}）"
                ) from backup_err
            cached["_stale"]["reason"] = f"Open-Meteo: {primary_err}；met.no: {backup_err}"
            return cached
    payload["_source"] = source
    _save_cache(key, payload)
    return payload


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
            }
        )
    return rows


def _at(hourly: Dict[str, Any], key: str, index: int) -> Optional[float]:
    seq = hourly.get(key) or []
    if index < len(seq):
        return seq[index]
    return None
