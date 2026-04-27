"""
Supervisor agent: decides which downstream path handles the user message.

Routes:
- RAG: document Q&A (retriever -> evaluator).
- GREETING: short hi/hello only — skip retriever, prefill reply, then evaluator.
- INFIIOT: dashboards, variables, widget mapping, widget creation (Infiiot agent).

This module uses lightweight keyword rules (no extra LLM call) so routing is fast
and predictable. You can later replace route() with a small LLM classifier.
"""

from __future__ import annotations

import re
from typing import Literal

Route = Literal["rag", "infiiot", "greeting"]


def is_simple_greeting(user_message: str) -> bool:
    """
    True for very short, obvious greetings (hi/hello/hey/good morning/how are you).
    Long or topic-heavy text is never a greeting, so RAG is used instead.
    """
    t = (user_message or "").strip().lower()
    if not t or len(t) > 100:
        return False
    patterns = (
        r"^(hi|hello|hey|hiya|howdy|greetings|yo|sup|what'?s up)\s*[!.?…]*$",
        r"^(hi|hello|hey)\s+there\s*[!.?…]*$",
        r"^good\s+(morning|afternoon|evening|day)(?:\s+\w+)?\s*[!.?…]*$",
        r"^how\s+are\s+you(\s+today|)\s*\??\s*$",
    )
    return any(re.match(p, t) for p in patterns)


def route(user_message: str, infiiot_session_active: bool = False) -> Route:
    """
    Classify user_message into one of: rag, infiiot, greeting.

    Decision order is intentional:
    1) Keep active Infiiot sessions pinned to Infiiot.
    2) Match clear Infiiot keywords/patterns.
    3) Detect short greetings.
    4) Fallback to RAG for all other text.

    If infiiot_session_active is True, keep routing to Infiiot so short follow-ups
    like "dashboard 1" or "yes" are not misclassified as RAG.
    """
    if infiiot_session_active:
        return "infiiot"

    text = (user_message or "").strip().lower()
    if not text:
        return "rag"

    # --- Infiiot intent signals (extend this list as product grows) ---
    infiiot_keywords = (
        "widget",
        "dashboard",
        "variable",
        "gauge",
        "slider",
        "switch",
        "thermometer",
        "infiiot",
        "chart",
        "mapping",
        "create widget",
        "add widget",
    )
    if any(k in text for k in infiiot_keywords):
        return "infiiot"

    # Short commands like "project 5 variable temp" during widget flow land here if no keyword;
    # digits + project/variable hints still belong to Infiiot if session already active — handled in agent.

    if re.search(r"\b(project|variable|dashboard)\s*\d+", text):
        return "infiiot"

    if is_simple_greeting(user_message):
        return "greeting"

    return "rag"
