"""对话式钓鱼参谋 Agent。

两种运行模式：
1) LLM 模式：配置 DeepSeek / OpenAI 兼容接口的 API Key，把「实时环境数据 +
   检索到的知识库片段」作为上下文注入，生成个性化建议。
2) 兜底模式：没有 Key 时，用规则模板结合评分结果与知识库片段直接组稿，
   保证部署后「零配置也能用」——这也是本项目刻意设计的降级策略。
"""
from __future__ import annotations

import os
from typing import Any, Dict, List, Optional

import requests

DEEPSEEK_URL = "https://api.deepseek.com/chat/completions"
DEFAULT_MODEL = "deepseek-chat"


def build_system_prompt() -> str:
    return (
        "你是一名资深垂钓顾问，精通台钓与路亚，熟悉气压、水温、风向、月相与鱼情的关系。\n"
        "回答要求：\n"
        "1. 结合用户提供的实时环境数据与检索到的知识片段，不编造数据；\n"
        "2. 先给结论，再给可执行动作（钓位、钓深、饵料、线组、节奏）；\n"
        "3. 语言简洁专业，控制在 200 字以内，分点输出；\n"
        "4. 涉及安全与合规时主动提醒。"
    )


def build_user_prompt(
    question: str,
    condition_brief: str,
    context: str,
    species: str,
) -> str:
    return (
        f"【目标鱼种】{species}\n"
        f"【实时环境】{condition_brief}\n"
        f"【知识库检索】\n{context}\n\n"
        f"【钓友提问】{question}"
    )


def llm_chat(
    question: str,
    condition_brief: str,
    context: str,
    species: str,
    api_key: str,
    history: Optional[List[Dict[str, str]]] = None,
    model: str = DEFAULT_MODEL,
    timeout: int = 60,
) -> str:
    """调用 DeepSeek（OpenAI 兼容）接口。失败时抛出异常，由上层降级。"""
    messages: List[Dict[str, str]] = [{"role": "system", "content": build_system_prompt()}]
    for item in history or []:
        messages.append({"role": item.get("role", "user"), "content": item.get("content", "")})
    messages.append(
        {"role": "user", "content": build_user_prompt(question, condition_brief, context, species)}
    )
    resp = requests.post(
        DEEPSEEK_URL,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        json={"model": model, "messages": messages, "temperature": 0.6, "max_tokens": 700},
        timeout=timeout,
    )
    resp.raise_for_status()
    data = resp.json()
    return (data.get("choices") or [{}])[0].get("message", {}).get("content", "").strip()


def rule_based_answer(
    question: str,
    score: int,
    level: str,
    reasons: List[str],
    windows: List[Dict[str, Any]],
    species: str,
    snippets: List[Dict[str, Any]],
) -> str:
    """无 LLM 时的兜底回答：由评分结果 + 知识片段拼装。"""
    lines: List[str] = []
    lines.append(f"**出钓指数 {score}/100（{level}）**")
    if windows:
        best = windows[0]
        lines.append(
            f"**推荐时段**：{best['start']}–{best['end']}（窗口评分 {best['score']}），"
            "建议提前 30 分钟到场打窝。"
        )
    lines.append("**关键依据**：")
    for reason in reasons[:3]:
        lines.append(f"- {reason}")
    if snippets:
        lines.append(f"**目标鱼种（{species}）参考**：")
        for s in snippets[:2]:
            lines.append(f"- {s.get('title')}：{s.get('content')[:70]}…")
    lines.append("**行动建议**：先按窗口期到位，根据现场鱼口再调整钓深与饵料味型；注意禁渔期与人身安全。")
    return "\n".join(lines)


def answer(
    question: str,
    condition_brief: str,
    context: str,
    snippets: List[Dict[str, Any]],
    score: int,
    level: str,
    reasons: List[str],
    windows: List[Dict[str, Any]],
    species: str,
    api_key: Optional[str] = None,
    history: Optional[List[Dict[str, str]]] = None,
) -> Dict[str, Any]:
    """统一入口：优先 LLM，失败或未配置则降级到规则回答。"""
    key = (api_key or os.getenv("DEEPSEEK_API_KEY") or "").strip()
    if key:
        try:
            text = llm_chat(question, condition_brief, context, species, key, history)
            if text:
                return {"text": text, "mode": "LLM"}
        except Exception as exc:  # noqa: BLE001 - 任何失败都应降级而非中断
            fallback = rule_based_answer(question, score, level, reasons, windows, species, snippets)
            return {"text": fallback, "mode": "规则兜底", "error": str(exc)[:200]}
    fallback = rule_based_answer(question, score, level, reasons, windows, species, snippets)
    return {"text": fallback, "mode": "规则兜底（未配置 API Key）"}
