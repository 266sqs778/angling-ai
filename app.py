"""千鱼千寻 · AI 钓鱼参谋（Angling-AI）

一站式智能垂钓决策助手：环境数据 + 可解释评分模型 + 知识库检索 + LLM 参谋。
运行：streamlit run app.py
"""
from __future__ import annotations

import datetime as dt
import json
import math
import os
from typing import Any, Dict, List, Optional

import folium
import pandas as pd
import streamlit as st
from streamlit_folium import st_folium

from modules import agent, conditions, knowledge, records, scoring

DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
DEFAULT_LOC = {"name": "深圳", "lat": 22.5431, "lon": 114.0579, "admin": "广东"}

st.set_page_config(page_title="千鱼千寻 · AI 钓鱼参谋", page_icon="🎣", layout="wide")


# ---------------------------------------------------------------- 数据加载与缓存
@st.cache_data(ttl=1800, show_spinner=False)
def cached_geocode(name: str) -> Optional[Dict[str, Any]]:
    return conditions.geocode(name)


@st.cache_data(ttl=900, show_spinner=False)
def cached_forecast(lat: float, lon: float, days: int = 3) -> Dict[str, Any]:
    return conditions.fetch_forecast(lat, lon, days)


@st.cache_data(show_spinner=False)
def builtin_spots() -> List[Dict[str, Any]]:
    path = os.path.join(DATA_DIR, "spots.json")
    with open(path, "r", encoding="utf-8") as fh:
        return (json.load(fh) or {}).get("spots") or []


@st.cache_data(show_spinner=False)
def spots_disclaimer() -> str:
    path = os.path.join(DATA_DIR, "spots.json")
    with open(path, "r", encoding="utf-8") as fh:
        return (json.load(fh) or {}).get("disclaimer") or ""


def haversine(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return round(2 * r * math.asin(math.sqrt(a)), 1)


def wgs84_to_gcj02(lat: float, lon: float) -> tuple:
    """WGS-84 转 GCJ-02（高德等国内底图使用的火星坐标系）。

    数据源给出的经纬度是 WGS-84，而高德瓦片基于 GCJ-02，直接叠加会偏移数百米。
    """
    if not (72.004 <= lon <= 137.8347 and 0.8293 <= lat <= 55.8271):
        return lat, lon  # 境外不做偏移

    a = 6378245.0
    ee = 0.00669342162296594323

    def _dlat(x: float, y: float) -> float:
        ret = -100.0 + 2.0 * x + 3.0 * y + 0.2 * y * y + 0.1 * x * y + 0.2 * math.sqrt(abs(x))
        ret += (20.0 * math.sin(6.0 * x * math.pi) + 20.0 * math.sin(2.0 * x * math.pi)) * 2.0 / 3.0
        ret += (20.0 * math.sin(y * math.pi) + 40.0 * math.sin(y / 3.0 * math.pi)) * 2.0 / 3.0
        ret += (160.0 * math.sin(y / 12.0 * math.pi) + 320.0 * math.sin(y * math.pi / 30.0)) * 2.0 / 3.0
        return ret

    def _dlon(x: float, y: float) -> float:
        ret = 300.0 + x + 2.0 * y + 0.1 * x * x + 0.1 * x * y + 0.1 * math.sqrt(abs(x))
        ret += (20.0 * math.sin(6.0 * x * math.pi) + 20.0 * math.sin(2.0 * x * math.pi)) * 2.0 / 3.0
        ret += (20.0 * math.sin(x * math.pi) + 40.0 * math.sin(x / 3.0 * math.pi)) * 2.0 / 3.0
        ret += (150.0 * math.sin(x / 12.0 * math.pi) + 300.0 * math.sin(x / 30.0 * math.pi)) * 2.0 / 3.0
        return ret

    d_lat = _dlat(lon - 105.0, lat - 35.0)
    d_lon = _dlon(lon - 105.0, lat - 35.0)
    rad_lat = lat / 180.0 * math.pi
    magic = 1 - ee * math.sin(rad_lat) ** 2
    sqrt_magic = math.sqrt(magic)
    d_lat = (d_lat * 180.0) / ((a * (1 - ee)) / (magic * sqrt_magic) * math.pi)
    d_lon = (d_lon * 180.0) / (a / sqrt_magic * math.cos(rad_lat) * math.pi)
    return round(lat + d_lat, 6), round(lon + d_lon, 6)


# ---------------------------------------------------------------- 侧边栏
def sidebar() -> Dict[str, Any]:
    st.sidebar.title("🎣 千鱼千寻")
    st.sidebar.caption("AI 钓鱼参谋 · 环境数据 + 可解释评分 + 知识库检索")

    if "loc" not in st.session_state:
        st.session_state["loc"] = dict(DEFAULT_LOC)

    st.sidebar.subheader("① 钓点位置")
    place = st.sidebar.text_input("输入地名（城市 / 区县 / 水库）", value=st.session_state["loc"]["name"])
    if st.sidebar.button("定位", use_container_width=True):
        found = cached_geocode(place)
        if found:
            st.session_state["loc"] = found
            st.rerun()
        else:
            st.sidebar.error("未找到该地点，请换个关键词试试")

    loc = st.session_state["loc"]
    st.sidebar.caption(f"当前：**{loc['name']}**（{loc['lat']:.3f}, {loc['lon']:.3f}）")

    st.sidebar.subheader("② 目标鱼种")
    species = st.sidebar.selectbox("选择主攻鱼种", scoring.SPECIES_OPTIONS, index=1)

    st.sidebar.subheader("③ 顾问模型（可选）")
    api_key = st.sidebar.text_input(
        "DeepSeek API Key（留空则使用规则兜底）",
        type="password",
        help="填入后由大模型生成个性化建议；不填也能正常使用，系统会自动降级为规则回答。",
    )

    st.sidebar.divider()
    with st.sidebar.expander("ℹ️ 数据与说明"):
        st.markdown(
            "- 环境数据：Open-Meteo 免费开放接口（无需 Key）\n"
            "- 水温：由气温滞回模型估算，仅供筛选适温区间\n"
            "- 月相：按朔望月周期自算\n"
            "- 知识库：内置 24 条垂钓专业条目，检索后注入回答\n"
            "- 评分：6 维度加权模型，结论可解释"
        )
    st.sidebar.caption("⚠️ 出钓前请确认当地禁渔期与禁钓区，注意人身安全。")
    return {"loc": loc, "species": species, "api_key": api_key}


# ---------------------------------------------------------------- 公共计算
def compute_context(loc: Dict[str, Any], species: str) -> Optional[Dict[str, Any]]:
    try:
        forecast = cached_forecast(loc["lat"], loc["lon"])
    except Exception as exc:  # noqa: BLE001
        st.error(f"环境数据获取失败：{exc}")
        st.caption("多为 Open-Meteo 免费接口限流所致，稍后重试通常即可恢复。")
        if st.button("重试获取", key="retry_context"):
            cached_forecast.clear()
            st.rerun()
        return None

    stale = forecast.get("_stale")
    if stale:
        st.warning(
            f"⚠️ Open-Meteo 接口暂时限流，当前展示的是最近一次成功获取的缓存数据"
            f"（约 {stale['age_minutes']} 分钟前），非实时数据，评分仅供参考。"
        )

    rows = conditions.build_hourly_frame(forecast)
    if not rows:
        st.error("环境数据为空，请稍后重试。")
        return None

    water = conditions.estimate_water_temp(forecast.get("hourly") or {})
    phase = conditions.moon_phase()
    current_raw = forecast.get("current") or {}
    first = rows[0]
    current = {
        "temp": current_raw.get("temperature_2m") or first.get("temp"),
        "pressure": current_raw.get("surface_pressure") or first.get("pressure"),
        "wind": current_raw.get("wind_speed_10m") or first.get("wind"),
        "wind_dir": conditions.wind_dir_label(
            current_raw.get("wind_direction_10m") or first.get("wind_dir")
        ),
        "cloud": current_raw.get("cloud_cover") or first.get("cloud"),
    }
    today = rows[:24]
    pressure_later = today[3]["pressure"] if len(today) > 3 else None
    result = scoring.score_conditions(current, water, phase, species, pressure_later)
    windows = scoring.best_windows(today, water, phase, species)
    return {
        "rows": rows, "today": today, "water": water, "phase": phase,
        "current": current, "result": result, "windows": windows,
    }


def brief_of(ctx: Dict[str, Any], species: str) -> str:
    c, r = ctx["current"], ctx["result"]
    return (
        f"地点养殖水体当日：气温 {_fmt(c['temp'], '℃')}，气压 {_fmt(c['pressure'], 'hPa')}，"
        f"风速 {_fmt(c['wind'], 'm/s')}（{c['wind_dir']}），云量 {_fmt(c['cloud'], '%')}，"
        f"估算水温 {_fmt(ctx['water'], '℃')}，月相 {ctx['phase']['name']}，"
        f"出钓指数 {r['score']}/100（{r['level']}），目标鱼种 {species}。"
    )


def _fmt(value: Optional[float], unit: str) -> str:
    return f"{value:.1f}{unit}" if isinstance(value, (int, float)) else "—"


# ---------------------------------------------------------------- 页面：今日参谋
def page_advisor(ctx: Dict[str, Any], species: str, api_key: str) -> None:
    r = ctx["result"]
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("出钓指数", f"{r['score']}/100", r["level"])
    c2.metric("估算水温", _fmt(ctx["water"], "℃"))
    c3.metric("气压", _fmt(ctx["current"]["pressure"], " hPa"))
    c4.metric("月相", ctx["phase"]["name"], f"亮度 {int(ctx['phase']['illumination'] * 100)}%")

    if ctx["windows"]:
        best = ctx["windows"][0]
        st.success(f"今日首选窗口：**{best['start']} – {best['end']}**（窗口评分 {best['score']}）")

    st.markdown("#### 提问")
    samples = [
        f"今天适合去钓{species}吗？",
        "应该钓多深、用什么饵？",
        "这个气压趋势要注意什么？",
    ]
    cols = st.columns(len(samples))
    for col, s in zip(cols, samples):
        if col.button(s, use_container_width=True):
            st.session_state.setdefault("pending", "")
            st.session_state["pending"] = s

    with st.form("ask_form", clear_on_submit=True):
        q = st.text_input("向参谋提问", value=st.session_state.get("pending", ""), placeholder="例如：今晚夜钓翘嘴，用什么拟饵？")
        submitted = st.form_submit_button("获取建议", use_container_width=True)

    if submitted and q.strip():
        snippets = knowledge.retrieve(q, top_k=4)
        ctx_text = knowledge.as_context(snippets)
        with st.spinner("参谋正在分析…"):
            out = agent.answer(
                question=q,
                condition_brief=brief_of(ctx, species),
                context=ctx_text,
                snippets=snippets,
                score=r["score"],
                level=r["level"],
                reasons=r["reasons"],
                windows=ctx["windows"],
                species=species,
                api_key=api_key,
            )
        st.session_state.setdefault("chat", [])
        st.session_state["chat"].append({"role": "user", "content": q})
        st.session_state["chat"].append(
            {"role": "assistant", "content": out["text"], "mode": out["mode"], "snippets": snippets}
        )
        st.session_state["pending"] = ""

    history = st.session_state.get("chat") or []
    if history:
        st.markdown("#### 对话记录")
        for msg in history:
            if msg["role"] == "user":
                with st.chat_message("user"):
                    st.write(msg["content"])
            else:
                with st.chat_message("assistant", avatar="🎣"):
                    st.markdown(msg["content"])
                    st.caption(f"生成方式：{msg.get('mode', '—')}")
                    if msg.get("snippets"):
                        with st.expander("本次引用的知识库条目"):
                            for s in msg["snippets"]:
                                st.markdown(f"- **{s['title']}**：{s['content']}")


# ---------------------------------------------------------------- 页面：鱼情指数
def page_forecast(ctx: Dict[str, Any], species: str) -> None:
    r = ctx["result"]
    st.markdown(f"### 今日出钓指数 **{r['score']}/100** · {r['level']}")
    st.progress(min(1.0, r["score"] / 100.0))

    left, right = st.columns([3, 2])
    with left:
        frame = pd.DataFrame(
            [
                {"时间": row["time"][11:16], "指数": scoring.score_conditions(
                    row, ctx["water"], ctx["phase"], species,
                    ctx["today"][i + 3]["pressure"] if i + 3 < len(ctx["today"]) else None,
                )["score"]}
                for i, row in enumerate(ctx["today"])
            ]
        )
        st.line_chart(frame.set_index("时间"), height=260)
        st.caption("逐时出钓指数（0–100）")
    with right:
        st.markdown("**评分明细**")
        st.dataframe(
            pd.DataFrame(r["details"])[["维度", "得分", "权重", "说明"]],
            hide_index=True,
            use_container_width=True,
        )

    if ctx["windows"]:
        st.markdown("#### 推荐时段")
        st.dataframe(pd.DataFrame(ctx["windows"]), hide_index=True, use_container_width=True)


# ---------------------------------------------------------------- 页面：钓点地图
def page_map(ctx: Dict[str, Any], loc: Dict[str, Any], species: str, api_key: str) -> None:
    st.caption(spots_disclaimer())
    all_spots = builtin_spots() + [
        {"name": s["name"], "lat": s["lat"], "lon": s["lon"], "type": s.get("type"), "note": s.get("note"), "custom": True}
        for s in records.list_spots()
        if s.get("lat") is not None
    ]

    # 底图用高德瓦片：国内可直连，且与 GCJ-02 坐标系一致。
    # 注意不要写 {s}，folium 会把 subdomains 只写进 Map 选项、TileLayer 仍是默认
    # 的 a/b/c，会解析到不存在的高德子域；这里固定用 webrd01。
    m = folium.Map(
        location=wgs84_to_gcj02(loc["lat"], loc["lon"]),
        zoom_start=11,
        tiles=(
            "https://webrd01.is.autonavi.com/appmaptile"
            "?lang=zh_cn&size=1&scale=1&style=8&x={x}&y={y}&z={z}"
        ),
        attr="地图数据 © 高德地图",
    )
    folium.Marker(
        list(wgs84_to_gcj02(loc["lat"], loc["lon"])),
        tooltip=f"当前钓点：{loc['name']}",
        icon=folium.Icon(color="red", icon="star"),
    ).add_to(m)
    for s in all_spots:
        folium.Marker(
            list(wgs84_to_gcj02(s["lat"], s["lon"])),
            tooltip=f"{s['name']}｜{'/'.join(s.get('species') or []) or s.get('type') or ''}",
            popup=folium.Popup(
                f"<b>{s['name']}</b><br>类型：{s.get('type') or '—'}<br>"
                f"常见鱼种：{'/'.join(s.get('species') or []) or '—'}<br>"
                f"备注：{s.get('note') or '—'}",
                max_width=260,
            ),
            icon=folium.Icon(color="blue", icon="info-sign"),
        ).add_to(m)

    left, right = st.columns([3, 2])
    with left:
        data = st_folium(m, height=430, use_container_width=True, key="spots_map")
    with right:
        st.markdown("**按距离排序**")
        ranked = sorted(
            [
                {
                    "钓点": s["name"],
                    "类型": s.get("type") or "—",
                    "鱼种": "/".join(s.get("species") or []) or "—",
                    "距离(km)": haversine(loc["lat"], loc["lon"], s["lat"], s["lon"]),
                }
                for s in all_spots
            ],
            key=lambda d: d["距离(km)"],
        )
        st.dataframe(pd.DataFrame(ranked), hide_index=True, use_container_width=True)

    clicked = None
    if isinstance(data, dict):
        clicked = data.get("last_clicked")
    if clicked:
        st.info(f"已在地图上选点：{clicked['lat']:.4f}, {clicked['lng']:.4f}")
        if st.button("以该点作为当前钓点", type="primary"):
            st.session_state["loc"] = {
                "name": f"地图选点 {clicked['lat']:.3f},{clicked['lng']:.3f}",
                "lat": clicked["lat"],
                "lon": clicked["lng"],
                "admin": "",
            }
            st.rerun()

    with st.expander("➕ 添加我的钓点"):
        with st.form("add_spot", clear_on_submit=True):
            c1, c2, c3 = st.columns(3)
            name = c1.text_input("名称")
            lat = c2.number_input("纬度", value=float(loc["lat"]), format="%.5f")
            lon = c3.number_input("经度", value=float(loc["lon"]), format="%.5f")
            s_type = st.selectbox("类型", ["水库", "湖泊", "河流", "池塘", "海钓", "其他"])
            note = st.text_input("备注")
            if st.form_submit_button("保存钓点") and name.strip():
                records.add_spot(name.strip(), lat, lon, s_type, note)
                st.success("已保存，刷新后出现在地图与列表中")
                st.rerun()

    custom = records.list_spots()
    if custom:
        st.markdown("**我的钓点**")
        st.dataframe(pd.DataFrame(custom)[["id", "name", "lat", "lon", "type", "note"]],
                     hide_index=True, use_container_width=True)


# ---------------------------------------------------------------- 页面：钓获记录
def page_records(ctx: Dict[str, Any], loc: Dict[str, Any], species: str) -> None:
    st.caption("记录每一次出钓，让「运气」逐步变成「规律」。")

    with st.form("add_catch"):
        c1, c2, c3 = st.columns(3)
        caught_at = c1.date_input("日期", value=dt.date.today())
        spot = c2.text_input("钓点", value=loc["name"])
        sp = c3.selectbox("鱼种", scoring.SPECIES_OPTIONS, index=scoring.SPECIES_OPTIONS.index(species))
        c4, c5, c6 = st.columns(3)
        length = c4.number_input("体长 (cm)", min_value=0.0, value=0.0, step=0.5)
        weight = c5.number_input("重量 (kg)", min_value=0.0, value=0.0, step=0.05)
        bait = c6.text_input("饵料", placeholder="例如：腥味商品饵 / 雷蛙")
        note = st.text_area("备注", placeholder="天气、鱼口、调整过程…", height=80)
        if st.form_submit_button("保存记录", type="primary"):
            records.add_catch(
                caught_at=str(caught_at),
                spot=spot,
                species=sp,
                length_cm=length or None,
                weight_kg=weight or None,
                bait=bait,
                score=ctx["result"]["score"],
                pressure=ctx["current"]["pressure"],
                water_temp=ctx["water"],
                note=note,
            )
            st.success("已保存本次钓获")
            st.rerun()

    st.divider()
    left, right = st.columns([3, 2])
    with left:
        data = records.list_catches()
        if data:
            st.dataframe(
                pd.DataFrame(data)[
                    ["id", "caught_at", "spot", "species", "length_cm", "weight_kg",
                     "bait", "score", "pressure", "water_temp", "note"]
                ].rename(columns={
                    "id": "ID", "caught_at": "日期", "spot": "钓点", "species": "鱼种",
                    "length_cm": "体长cm", "weight_kg": "重量kg", "bait": "饵料",
                    "score": "当日指数", "pressure": "气压", "water_temp": "水温", "note": "备注",
                }),
                hide_index=True,
                use_container_width=True,
            )
        else:
            st.info("还没有记录，先添加第一条吧。")
    with right:
        st.markdown("**AI 复盘**")
        if st.button("生成复盘报告", use_container_width=True):
            st.session_state["review"] = records.review_text()
        if st.session_state.get("review"):
            st.markdown(st.session_state["review"])

    if records.list_catches():
        with st.expander("删除记录"):
            del_id = st.number_input("输入要删除的记录 ID", min_value=1, step=1)
            if st.button("删除"):
                records.delete_catch(int(del_id))
                st.rerun()


# ---------------------------------------------------------------- 主流程
def main() -> None:
    st.title("🎣 千鱼千寻 · AI 钓鱼参谋")
    st.caption("环境数据 → 可解释评分 → 知识库检索 → 大模型参谋，一条链路给出「今天怎么钓」。")

    cfg = sidebar()
    loc, species, api_key = cfg["loc"], cfg["species"], cfg["api_key"]

    ctx = compute_context(loc, species)
    if ctx is None:
        st.stop()

    tab1, tab2, tab3, tab4 = st.tabs(["🧭 今日参谋", "📈 鱼情指数", "🗺️ 钓点地图", "📒 钓获记录"])
    with tab1:
        page_advisor(ctx, species, api_key)
    with tab2:
        page_forecast(ctx, species)
    with tab3:
        page_map(ctx, loc, species, api_key)
    with tab4:
        page_records(ctx, loc, species)

    st.divider()
    st.caption(
        "千鱼千寻 · AI 钓鱼参谋 ｜ 个人作品：Smart Angling Assistant ｜ "
        "数据来源 Open-Meteo ｜ 仅供垂钓决策参考，请遵守禁渔期与禁钓区规定。"
    )


if __name__ == "__main__":
    main()
