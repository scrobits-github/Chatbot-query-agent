"""
FastAPI entrypoint for the AI backend.

- /chatbot: unified workflow (supervisor -> rag or infiiot branches).
"""

from __future__ import annotations

import re
import uuid
from typing import Optional

from fastapi import FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from src.Uploader.upload_api import upload_router
from src.Workflow.workflow import workflow
from src.agents.infiiot_agent import infiiot_agent

app = FastAPI()


class ChatRequest(BaseModel):
    user_message: str
    session_id: Optional[str] = None


class ChatResponse(BaseModel):
    response: str


app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(upload_router)


def _parse_bearer(authorization: Optional[str]) -> Optional[str]:
    """Extract raw token from Authorization: Bearer <token>."""
    if not authorization or not authorization.lower().startswith("bearer "):
        return None
    return authorization.split(" ", 1)[1].strip()


def _resolve_auth_token(authorization: Optional[str], token_header: Optional[str]) -> Optional[str]:
    """
    Resolve auth token from request headers.

    Priority:
    1) Authorization: Bearer <token>
    2) Token: <token>   (legacy/compat fallback)
    """
    bearer = _parse_bearer(authorization)
    if bearer:
        return bearer
    if token_header and token_header.strip():
        return token_header.strip()
    return None


@app.get("/")
def root():
    return {"status": "ok", "message": "Chatbot API running"}


@app.post("/chatbot", response_model=ChatResponse)
async def chatbot_endpoint(
    request: ChatRequest,
    authorization: Optional[str] = Header(default=None),
    token: Optional[str] = Header(default=None),
):
    """
    Main chat: unified workflow (supervisor node -> rag/infiiot branch).
    """
    try:
        user_input = request.user_message
        # Accept both modern Bearer auth and legacy Token header.
        auth_token = _resolve_auth_token(authorization, token)
        # Keep the same session id across turns; derive one if client didn't send it.
        session_id = request.session_id or (f"token-{auth_token}" if auth_token else f"session-{uuid.uuid4()}")

        # --- Unified workflow: supervisor node decides RAG vs Infiiot branch ---
        initial_state = {
            "user_query": user_input,
            "query_response": "",
            "evaluation_state": "",
            "retry_count": 0,
            "instruction": "",
            "session_id": session_id,
            "auth_token": auth_token or "",
            "is_login": 0,
        }

        final_state = workflow.invoke(initial_state, config={"verbose": True})
        query_response = final_state.get("query_response", "No response generated.")

        if "ValidationOutcome" in query_response:
            pattern = r'validated_output="((?:[^"\\]|\\.)*)"'
            match = re.search(pattern, query_response)
            if match:
                answer = match.group(1).replace("\\n", "\n").replace('\\"', '"').strip()
            else:
                fallback_pattern = r"validated_output='([^']*)'[, ]"
                fallback_match = re.search(fallback_pattern, query_response)
                if fallback_match:
                    answer = (
                        fallback_match.group(1)
                        .replace("\\n", "\n")
                        .replace('\\"', '"')
                        .replace("\\'", "'")
                        .strip()
                    )
                else:
                    start_idx = query_response.find("validated_output='") + len("validated_output='")
                    end_idx = query_response.find("',\n    reask=", start_idx)
                    if end_idx != -1:
                        raw_content = query_response[start_idx:end_idx]
                        answer = (
                            raw_content.replace("\\n", "\n")
                            .replace('\\"', '"')
                            .replace("\\'", "'")
                            .strip()
                        )
                    else:
                        answer = "Error parsing validated output."
        else:
            answer = query_response.replace("'", "").strip().strip("'").strip()

        answer = re.sub(r"\n+$", "", answer).strip()
        return ChatResponse(response=answer)

    except Exception as e:
        print("Error in /chatbot:", e)
        raise HTTPException(status_code=500, detail=str(e))


