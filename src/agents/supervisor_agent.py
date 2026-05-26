"""
Supervisor agent: decides which downstream path handles the user message.
Uses dynamic LLM routing with Gemini-2.0-flash, falling back to instant
predictable keyword rules on API or connection errors.

Routes:
- RAG: document Q&A (retriever -> evaluator).
- GREETING: short hi/hello only — skip retriever, prefill reply, then evaluator.
- INFIIOT: dashboards, variables, widget mapping, widget creation (Infiiot agent).
"""

from __future__ import annotations

import re
import logging
from typing import Literal

from langchain_core.messages import SystemMessage, HumanMessage
from langchain_google_genai import ChatGoogleGenerativeAI
from settings import BASE_DIR, GOOGLE_API_KEY
from src.utils.yaml_loader import load_prompts

logger = logging.getLogger(__name__)

Route = Literal["rag", "infiiot", "greeting"]


def is_simple_greeting(user_message: str) -> bool:
    """
    True for very short, obvious greetings (hi/hello/hey/good morning/how are you).
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


def _fallback_rule_based_route(user_message: str) -> Route:
    """
    Backup rule-based classifier that handles routing with 100% uptime and speed.
    """
    text = (user_message or "").strip().lower()
    if not text:
        return "rag"

    # --- Infiiot intent signals ---
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

    if re.search(r"\b(project|variable|dashboard)\s*\d+", text):
        return "infiiot"

    if is_simple_greeting(user_message):
        return "greeting"

    return "rag"


def route(user_message: str, infiiot_session_active: bool = False) -> Route:
    """
    Dynamically classify user_message into one of: rag, infiiot, greeting using Gemini.
    If infiiot_session_active is True, keeps routing pinned to infiiot to preserve context.
    """
    # 1. Keep active Infiiot sessions pinned to Infiiot
    if infiiot_session_active:
        return "infiiot"

    text = (user_message or "").strip()
    if not text:
        return "rag"

    # 2. If no API key is set, instantly use rule-based fallback
    if not GOOGLE_API_KEY:
        return _fallback_rule_based_route(text)

    # 3. Dynamic classification using Gemini-2.0-flash
    try:
        llm = ChatGoogleGenerativeAI(
            model="gemini-2.5-flash",
            temperature=0.0,
            google_api_key=GOOGLE_API_KEY,
            max_retries=1,
        )

        prompts = load_prompts(str(BASE_DIR / "src" / "utils" / "prompts.yml"))
        system_prompt = prompts.get("supervisor_agent_prompt")

        response = llm.invoke([
            SystemMessage(content=system_prompt),
            HumanMessage(content=text)
        ])

        result = str(response.content).strip().lower()
        if result in ["infiiot", "greeting", "rag"]:
            return result

        # Fallback if the LLM response is corrupted or unexpected
        return _fallback_rule_based_route(text)

    except Exception as e:
        logger.warning(f"Gemini routing failed: {e}. Falling back to rule-based routing.")
        return _fallback_rule_based_route(text)
