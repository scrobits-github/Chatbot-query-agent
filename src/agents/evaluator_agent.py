"""Evaluator agent node: profanity gate + YAML-driven LLM quality check (prompts.yml)."""

from __future__ import annotations

import re
from functools import lru_cache
from better_profanity import profanity
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_google_genai import ChatGoogleGenerativeAI

from settings import BASE_DIR, GOOGLE_API_KEY
from src.schemas.response_schema import ResponseSchema
from src.utils.yaml_loader import load_prompts

profanity.load_censor_words()

_PROMPTS_PATH = BASE_DIR / "src" / "utils" / "prompts.yml"


@lru_cache(maxsize=1)
def _evaluator_system_prompt() -> str:
    """Load evaluator instructions from prompts.yml (single file, cached)."""
    prompts = load_prompts(str(_PROMPTS_PATH))
    text = prompts.get("evaluator_agent_prompt")
    if not text or not isinstance(text, str):
        raise KeyError("evaluator_agent_prompt missing or invalid in prompts.yml")
    return text.strip()


def _parse_evaluator_llm_output(text: str) -> tuple[bool, str]:
    """
    Parse LLM evaluation text. Returns (passes, feedback_for_retry).

    Fails when hallucinations YES or accuracy score < 7.
    Citation completeness is not used as hard fail (sources not in state for this graph).
    """
    t = text or ""
    hall = re.search(r"HALLUCINATIONS_FOUND:\s*(YES|NO)", t, re.IGNORECASE)
    score_m = re.search(r"ACCURACY_SCORE:\s*(\d+)", t, re.IGNORECASE)
    feedback_m = re.search(r"FEEDBACK:\s*(.+?)(?:\n\n|\Z)", t, re.IGNORECASE | re.DOTALL)

    feedback = feedback_m.group(1).strip() if feedback_m else "Please improve the answer per evaluator feedback."

    fails = False
    if hall and hall.group(1).upper() == "YES":
        fails = True
    if score_m:
        try:
            if int(score_m.group(1)) < 7:
                fails = True
        except ValueError:
            pass

    return (not fails, feedback if fails else "")


def evaluator_agent(state: ResponseSchema) -> ResponseSchema:
    user_query = state["user_query"]
    query_response = state["query_response"]
    llm_text = query_response

    # --- Hard stop: too many retriever/evaluator loops ---
    if state["retry_count"] > 3:
        return {
            "user_query": user_query,
            "query_response": "Max retries exceeded. Response could not be generated without profanity.",
            "evaluation_state": "True",
            "instruction": "",
            "route": state.get("route", "rag"),
            "session_id": state.get("session_id", ""),
            "auth_token": state.get("auth_token", ""),
        }

    # --- Fast local gate: profanity ---
    if profanity.contains_profanity(llm_text):
        retry_instruction = (
            "Rephrase the response to be completely profanity-free. Avoid any explicit language, "
            "slurs, or direct quotes of offensive content. Summarize factually and neutrally."
        )
        return {
            "user_query": user_query,
            "query_response": llm_text,
            "evaluation_state": "False",
            "instruction": retry_instruction,
            "route": state.get("route", "rag"),
            "session_id": state.get("session_id", ""),
            "auth_token": state.get("auth_token", ""),
        }

    # --- YAML-driven LLM evaluation (evaluator_agent_prompt in prompts.yml) ---
    if not GOOGLE_API_KEY:
        return {
            "user_query": user_query,
            "query_response": llm_text,
            "evaluation_state": "True",
            "instruction": "",
            "route": state.get("route", "rag"),
            "session_id": state.get("session_id", ""),
            "auth_token": state.get("auth_token", ""),
        }

    try:
        system = _evaluator_system_prompt()
        human = (
            f"USER QUERY:\n{user_query}\n\n"
            f"GENERATED RESPONSE:\n{llm_text}\n\n"
            "CONTEXT NOTE: This pipeline does not pass raw retrieved chunks separately. "
            "Evaluate using the query and the generated response only. "
            "If you cannot verify citations against sources, set CITATIONS_COMPLETE: YES and "
            "do not fail the answer solely for missing citations. "
            "Still check for obvious hallucinations, contradictions, and unsafe content."
        )
        llm = ChatGoogleGenerativeAI(
            model="gemini-2.0-flash",
            google_api_key=GOOGLE_API_KEY,
            temperature=0,
            max_retries=1,
        )
        resp = llm.invoke([SystemMessage(content=system), HumanMessage(content=human)])
        raw = resp.content if isinstance(resp.content, str) else str(resp.content)
        passes, feedback = _parse_evaluator_llm_output(raw)
        if passes:
            return {
                "user_query": user_query,
                "query_response": llm_text,
                "evaluation_state": "True",
                "instruction": "",
                "route": state.get("route", "rag"),
                "session_id": state.get("session_id", ""),
                "auth_token": state.get("auth_token", ""),
            }
        return {
            "user_query": user_query,
            "query_response": llm_text,
            "evaluation_state": "False",
            "instruction": feedback or "Please improve the answer per evaluator feedback.",
            "route": state.get("route", "rag"),
            "session_id": state.get("session_id", ""),
            "auth_token": state.get("auth_token", ""),
        }
    except Exception:
        # If YAML/LLM fails, do not block the user-facing pipeline.
        return {
            "user_query": user_query,
            "query_response": llm_text,
            "evaluation_state": "True",
            "instruction": "",
            "route": state.get("route", "rag"),
            "session_id": state.get("session_id", ""),
            "auth_token": state.get("auth_token", ""),
        }
