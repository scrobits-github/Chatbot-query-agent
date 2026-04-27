"""
Unified workflow graph:
- supervisor_node decides route (rag vs greeting vs infiiot)
- greeting path: skip retriever, fixed friendly reply, then evaluator
- rag path: retriever -> evaluator loop
- infiiot path: infiiot_agent handles widget/dashboard/variable intents
"""

from langgraph.graph import StateGraph, START, END
from langchain_google_genai import ChatGoogleGenerativeAI
from settings import GOOGLE_API_KEY
from src.agents.evaluator_agent import evaluator_agent
from src.agents.infiiot_agent import infiiot_agent
from src.agents.retriver_agent import retriver_agent
from src.agents.supervisor_agent import route
from src.schemas.response_schema import ResponseSchema

model = ChatGoogleGenerativeAI(model="gemini-2.0-flash", google_api_key=GOOGLE_API_KEY)


def supervisor_node(state: ResponseSchema) -> ResponseSchema:
    """Select route and keep auth/session metadata in state."""
    message = state["user_query"]
    session_id = state.get("session_id", "")
    chosen = route(message, infiiot_session_active=infiiot_agent.has_active_session(session_id))
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
        return "greeting_node"
    return "retriver_agent"


def greeting_node(state: ResponseSchema) -> ResponseSchema:
    """
    Short greeting shortcut: no query_agent / get_context.
    Fills a minimal reply so the evaluator can still run safety/quality checks.
    """
    return {
        "user_query": state["user_query"],
        "query_response": (
            "Hello! I am here to help. Ask me a question from your knowledge base, "
            "or say you want to create a widget, dashboard, or variable in Infiiot."
        ),
        "evaluation_state": "",
        "retry_count": state.get("retry_count", 0),
        "instruction": "",
        "route": "greeting",
        "session_id": state.get("session_id", ""),
        "auth_token": state.get("auth_token", ""),
    }


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
    }


def evaluation_edge(state: ResponseSchema):
    return "retriver_agent" if state["evaluation_state"] == "False" else END


graph = StateGraph(ResponseSchema)

graph.add_node("supervisor_node", supervisor_node)
graph.add_node("greeting_node", greeting_node)
graph.add_node("retriver_agent", retriver_agent)
graph.add_node("evaluator_agent", evaluator_agent)
graph.add_node("infiiot_node", infiiot_node)

graph.add_edge(START, "supervisor_node")
graph.add_conditional_edges(
    "supervisor_node",
    supervisor_edge,
    {
        "greeting_node": "greeting_node",
        "retriver_agent": "retriver_agent",
        "infiiot_node": "infiiot_node",
    },
)
graph.add_edge("greeting_node", "evaluator_agent")
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
