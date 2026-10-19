"""轻量知识库检索（RAG-lite）。

不依赖向量数据库与分词器：用「标签精确命中 + 字符二元组重叠」做混合打分，
在几十条量级的专业知识库上检索效果足够，且零额外依赖、部署零成本。
"""
from __future__ import annotations

import json
import os
from functools import lru_cache
from typing import Any, Dict, List

_KB_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "knowledge_base.json")


@lru_cache(maxsize=1)
def load_kb() -> List[Dict[str, Any]]:
    with open(_KB_PATH, "r", encoding="utf-8") as fh:
        return (json.load(fh) or {}).get("entries") or []


def _bigrams(text: str) -> set:
    text = "".join(text.split())
    return {text[i : i + 2] for i in range(max(0, len(text) - 1))}


def retrieve(query: str, top_k: int = 4) -> List[Dict[str, Any]]:
    """按查询返回最相关的知识条目。"""
    entries = load_kb()
    if not entries:
        return []
    query = query or ""
    q_grams = _bigrams(query)
    scored: List[tuple] = []
    for entry in entries:
        score = 0.0
        for tag in entry.get("tags") or []:
            if tag and tag in query:
                score += 3.0
        if q_grams:
            title_overlap = len(q_grams & _bigrams(entry.get("title", ""))) / len(q_grams)
            body_overlap = len(q_grams & _bigrams(entry.get("content", ""))) / len(q_grams)
            score += 2.0 * title_overlap + 1.2 * body_overlap
        if score > 0:
            scored.append((score, entry))
    scored.sort(key=lambda pair: pair[0], reverse=True)
    if not scored:
        return entries[:top_k]
    return [entry for _, entry in scored[:top_k]]


def by_tags(tags: List[str], top_k: int = 4) -> List[Dict[str, Any]]:
    """按标签集合取知识条目（用于给 Agent 装配场景上下文）。"""
    entries = load_kb()
    hits = [e for e in entries if set(e.get("tags") or []) & set(tags)]
    return hits[:top_k]


def as_context(snippets: List[Dict[str, Any]]) -> str:
    """把知识条目拼成可注入提示词的上下文文本。"""
    if not snippets:
        return "（无检索结果）"
    lines = []
    for s in snippets:
        lines.append(f"【{s.get('title')}】{s.get('content')}")
    return "\n".join(lines)
