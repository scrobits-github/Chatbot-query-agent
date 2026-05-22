"""
Unified workflow graph:
- supervisor_node decides route (rag vs greeting vs infiiot) and fills greeting reply
- greeting path: skip retriever, dynamic greeting reply (Gemini + prompts.yml), then evaluator
- rag path: retriever -> evaluator loop
- infiiot path: infiiot_agent handles widget/dashboard/variable intents
"""

from functools import lru_cache

from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.graph import StateGraph, START, END
from langchain_google_genai import ChatGoogleGenerativeAI
from settings import BASE_DIR, GOOGLE_API_KEY, ORGANIZATION_NAME
from src.agents.evaluator_agent import evaluator_agent
from src.agents.infiiot_agent import infiiot_agent
from src.agents.retriver_agent import retriver_agent
from src.agents.supervisor_agent import route
from src.schemas.response_schema import ResponseSchema
from src.utils.yaml_loader import load_prompts

_PROMPTS_PATH = BASE_DIR / "src" / "utils" / "prompts.yml"
_GREETING_REPLY = (
    "Hello! I am here to help. Ask me a question from your knowledge base, "
    "or say you want to create a widget, dashboard, or variable in Infiiot."
)


@lru_cache(maxsize=1)
def _greeting_system_prompt() -> str:
    """Load greeting instructions from prompts.yml (cached)."""
    prompts = load_prompts(str(_PROMPTS_PATH))
    text = prompts.get("greeting_agent_prompt")
    if not text or not isinstance(text, str):
        raise KeyError("greeting_agent_prompt missing or invalid in prompts.yml")
    org = (ORGANIZATION_NAME or "").strip() or "your organization"
    return text.strip().format(organization_name=org)


def _generate_greeting_reply(user_message: str) -> str:
    """LLM-generated greeting; falls back to _GREETING_REPLY if API/key or YAML fails."""
    if not GOOGLE_API_KEY:
        return _GREETING_REPLY
    try:
        llm = ChatGoogleGenerativeAI(
            model="gemini-2.5-flash",
            google_api_key=GOOGLE_API_KEY,
            temperature=0.7,
            max_retries=1,
        )
        resp = llm.invoke(
            [
                SystemMessage(content=_greeting_system_prompt()),
                HumanMessage(content=user_message),
            ]
        )
        raw = resp.content if isinstance(resp.content, str) else str(resp.content)
        out = (raw or "").strip()
        return out if out else _GREETING_REPLY
    except Exception:
        return _GREETING_REPLY


def supervisor_node(state: ResponseSchema) -> ResponseSchema:
    """Select route, fill greeting reply if needed, and keep auth/session metadata."""
    message = state["user_query"]
    session_id = state.get("session_id", "")
    chosen = route(message, infiiot_session_active=infiiot_agent.has_active_session(session_id))
    if chosen == "greeting":
        return {
            "user_query": message,
            "query_response": _generate_greeting_reply(message),
            "evaluation_state": "",
            "retry_count": state.get("retry_count", 0),
            "instruction": state.get("instruction", ""),
            "route": "greeting",
            "session_id": session_id,
            "auth_token": state.get("auth_token", ""),
        }
    return {
        "user_query": message,
        "query_response": state.get("query_response", ""),
        "evaluation_state": state.get("evaluation_state", ""),
        "retry_count": state.get("retry_count", 0),
        "instruction": state.get("instruction", ""),
        "route": chosen,
        "session_id": session_id,
        "auth_token": state.get("auth_token", ""),
    }


def supervisor_edge(state: ResponseSchema) -> str:
    """Map supervisor `route` to the next node."""
    r = state.get("route")
    if r == "infiiot":
        return "infiiot_node"
    if r == "greeting":
        return "evaluator_agent"
    return "retriver_agent"


def infiiot_node(state: ResponseSchema) -> ResponseSchema:
    """Execute Infiiot agent inside workflow."""
    result = infiiot_agent.handle_message(
        user_message=state["user_query"],
        session_id=state.get("session_id", ""),
        auth_token=state.get("auth_token", "") or None,
    )
    response = str(result.get("response", "")) if result.get("handled") else (
        "I routed this to Infiiot, but it is not a supported Infiiot request yet."
    )
    return {
        "user_query": state["user_query"],
        "query_response": response,
        "evaluation_state": "True",
        "retry_count": state.get("retry_count", 0),
        "instruction": "",
        "route": "infiiot",
        "session_id": state.get("session_id", ""),
        "auth_token": state.get("auth_token", ""),
        "is_login": 1 if state.get("auth_token") else 0,
    }


def evaluation_edge(state: ResponseSchema):
    return "retriver_agent" if state["evaluation_state"] == "False" else END


graph = StateGraph(ResponseSchema)

graph.add_node("supervisor_node", supervisor_node)
graph.add_node("retriver_agent", retriver_agent)
graph.add_node("evaluator_agent", evaluator_agent)
graph.add_node("infiiot_node", infiiot_node)

graph.add_edge(START, "supervisor_node")
graph.add_conditional_edges(
    "supervisor_node",
    supervisor_edge,
    {
        "evaluator_agent": "evaluator_agent",
        "retriver_agent": "retriver_agent",
        "infiiot_node": "infiiot_node",
    },
)
graph.add_edge("retriver_agent", "evaluator_agent")
graph.add_conditional_edges(
    "evaluator_agent",
    evaluation_edge,
    {
        "retriver_agent": "retriver_agent",
        END: END
    }
)
graph.add_edge("infiiot_node", END)

workflow = graph.compile()

if __name__ == "__main__":
    # --- Print Workflow Graph (Mermaid) ---
    print("\n" + "="*50)
    print("        AGENT WORKFLOW GRAPH (Mermaid)")
    print("="*50)
    print(workflow.get_graph().draw_mermaid())
    print("="*50 + "\n")
    # -------------------------------------

    initial_state = {
        "user_query": "What did the anonymous BCGEU member post on social media about the government's raise offer during the strike?",
        "query_response": "",
        "evaluation_state": "",
        "retry_count": 0,
        "instruction": ""
    }

    final_state = workflow.invoke(initial_state, config={"verbose": True})

    print(final_state)
