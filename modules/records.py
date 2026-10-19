"""钓获记录存储与 AI 复盘。

使用本地 SQLite，零外部依赖；记录字段覆盖时间、钓点、鱼种、尺寸、饵料、
天气条件与备注，并支持基于历史数据的规则化复盘（统计规律 -> 建议）。
"""
from __future__ import annotations

import os
import sqlite3
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

_DB_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "angling.db")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS catches (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    caught_at TEXT NOT NULL,
    spot TEXT,
    species TEXT,
    length_cm REAL,
    weight_kg REAL,
    bait TEXT,
    score INTEGER,
    pressure REAL,
    water_temp REAL,
    note TEXT,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS spots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    lat REAL,
    lon REAL,
    type TEXT,
    note TEXT,
    created_at TEXT NOT NULL
);
"""


def _conn() -> sqlite3.Connection:
    conn = sqlite3.connect(_DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    with _conn() as conn:
        conn.executescript(_SCHEMA)


def add_catch(
    caught_at: str,
    spot: str = "",
    species: str = "",
    length_cm: Optional[float] = None,
    weight_kg: Optional[float] = None,
    bait: str = "",
    score: Optional[int] = None,
    pressure: Optional[float] = None,
    water_temp: Optional[float] = None,
    note: str = "",
) -> int:
    init_db()
    with _conn() as conn:
        cur = conn.execute(
            """INSERT INTO catches
               (caught_at, spot, species, length_cm, weight_kg, bait, score,
                pressure, water_temp, note, created_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
            (
                caught_at, spot, species, length_cm, weight_kg, bait, score,
                pressure, water_temp, note, datetime.now().isoformat(timespec="seconds"),
            ),
        )
        return int(cur.lastrowid)


def list_catches(limit: int = 200) -> List[Dict[str, Any]]:
    init_db()
    with _conn() as conn:
        rows = conn.execute(
            "SELECT * FROM catches ORDER BY caught_at DESC, id DESC LIMIT ?", (limit,)
        ).fetchall()
    return [dict(r) for r in rows]


def delete_catch(catch_id: int) -> None:
    init_db()
    with _conn() as conn:
        conn.execute("DELETE FROM catches WHERE id = ?", (catch_id,))


def add_spot(name: str, lat: float, lon: float, spot_type: str = "", note: str = "") -> int:
    init_db()
    with _conn() as conn:
        cur = conn.execute(
            "INSERT INTO spots (name, lat, lon, type, note, created_at) VALUES (?,?,?,?,?,?)",
            (name, lat, lon, spot_type, note, datetime.now().isoformat(timespec="seconds")),
        )
        return int(cur.lastrowid)


def list_spots() -> List[Dict[str, Any]]:
    init_db()
    with _conn() as conn:
        rows = conn.execute("SELECT * FROM spots ORDER BY id DESC").fetchall()
    return [dict(r) for r in rows]


def delete_spot(spot_id: int) -> None:
    init_db()
    with _conn() as conn:
        conn.execute("DELETE FROM spots WHERE id = ?", (spot_id,))


def stats() -> Dict[str, Any]:
    """汇总统计：总条数、鱼种分布、高产钓点、平均出钓指数、尺寸记录。"""
    records = list_catches(limit=1000)
    if not records:
        return {"count": 0}

    species_count: Dict[str, int] = {}
    spot_count: Dict[str, int] = {}
    scores: List[int] = []
    heaviest = None
    for r in records:
        sp = (r.get("species") or "未记录").strip() or "未记录"
        species_count[sp] = species_count.get(sp, 0) + 1
        st = (r.get("spot") or "").strip()
        if st:
            spot_count[st] = spot_count.get(st, 0) + 1
        if r.get("score") is not None:
            scores.append(int(r["score"]))
        w = r.get("weight_kg")
        if w is not None and (heaviest is None or w > heaviest.get("weight_kg", 0)):
            heaviest = r

    top_species = sorted(species_count.items(), key=lambda kv: kv[1], reverse=True)[:5]
    top_spots = sorted(spot_count.items(), key=lambda kv: kv[1], reverse=True)[:5]
    return {
        "count": len(records),
        "species": top_species,
        "spots": top_spots,
        "avg_score": round(sum(scores) / len(scores), 1) if scores else None,
        "heaviest": heaviest,
    }


def review_text() -> str:
    """基于历史记录生成规则化复盘建议。"""
    data = stats()
    if not data.get("count"):
        return "暂无钓获记录，先录入几条再来看复盘吧。"

    lines: List[str] = []
    lines.append("- **累计记录** %d 条" % data["count"])
    if data.get("avg_score") is not None:
        lines.append("- **平均出钓指数** %s/100" % data["avg_score"])
    if data.get("species"):
        top = data["species"][0]
        lines.append(f"- **主攻鱼种**：{top[0]}（{top[1]} 次）")
    if data.get("spots"):
        best = data["spots"][0]
        lines.append(f"- **高产钓点**：{best[0]}（{best[1]} 次）")
    hv = data.get("heaviest")
    if hv:
        lines.append(
            f"- **个人纪录**：{hv.get('species') or '未记录'} "
            f"{hv.get('weight_kg')} kg / {hv.get('length_cm') or '—'} cm"
        )

    lines.append("")
    lines.append("**复盘建议**：")
    if data.get("spots") and len(data["spots"]) > 2:
        lines.append("- 钓点分散，建议聚焦 1–2 个高产钓点，积累该点位的水深与鱼层经验；")
    else:
        lines.append("- 钓点集中度尚可，可继续深挖当前点位的窗口期规律；")
    if data.get("species") and len(data["species"]) > 3:
        lines.append("- 鱼种较杂，建议按季节确定主攻对象，针对性调整饵料与线组；")
    lines.append("- 记录中带上当日气压与水温，才能把「运气」逐步变成「规律」。")
    return "\n".join(lines)
