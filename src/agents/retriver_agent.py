"""Retriever agent node: calls query_agent to fetch RAG context and draft an answer."""

from src.schemas.response_schema import ResponseSchema
from settings import GOOGLE_API_KEY
from src.agents.query_agent import create_query_agent

# Build the query agent once; uses the get_context tool under the hood
query_agent = create_query_agent(api_key=GOOGLE_API_KEY)

def retriver_agent(state: ResponseSchema) -> ResponseSchema:
    user_query = state["user_query"]
    instruction = state["instruction"]
    modified_input = {"input": f"{user_query}\n\n{instruction}" if instruction else user_query}
    result = query_agent.invoke({"input": modified_input})
    response_str = result["output"]

    return {
        "user_query": user_query,
        "query_response": response_str,
        "evaluation_state": "",
        "retry_count": state["retry_count"] + 1,
        "instruction": instruction,
        "route": state.get("route", "rag"),
        "session_id": state.get("session_id", ""),
        "auth_token": state.get("auth_token", ""),
    }
