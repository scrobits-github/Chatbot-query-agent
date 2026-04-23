from fastapi import FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from src.Uploader.upload_api import upload_router
from src.Workflow.workflow import workflow
from src.agents.widget_creation_agent import widget_creation_agent
from typing import Optional
import uuid
import re

app = FastAPI()

class ChatRequest(BaseModel):
    user_message: str
    session_id: Optional[str] = None

class ChatResponse(BaseModel):
    response: str

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # or ["http://localhost:5173"] for stricter security
    allow_credentials=True,
    allow_methods=["*"],  # important for POST, GET, OPTIONS, etc.
    allow_headers=["*"],  # allow headers like Content-Type, Authorization
)

app.include_router(upload_router)

@app.get("/")
def root():
    return {"status": "ok", "message": "Chatbot API running"}


@app.post("/chatbot", response_model=ChatResponse)
async def chatbot_endpoint(
    request: ChatRequest,
):
    
    try:
        user_input = request.user_message
        print(f"User message: {user_input}")

        initial_state = {
            "user_query": user_input,
            "query_response": "",
            "evaluation_state": "",
            "retry_count": 0,
            "instruction": ""
        }

        final_state = workflow.invoke(initial_state, config={"verbose": True})
        print("Workflow final state:", final_state)

        query_response = final_state.get("query_response", "No response generated.")

        if "ValidationOutcome" in query_response:
           
            pattern = r'validated_output="((?:[^"\\]|\\.)*)"'
            match = re.search(pattern, query_response)
            if match:
                answer = match.group(1).replace('\\n', '\n').replace('\\"', '"').strip()
            else:
                
                fallback_pattern = r'validated_output=\'([^\']*)\'[, ]'
                fallback_match = re.search(fallback_pattern, query_response)
                if fallback_match:
                    answer = fallback_match.group(1).replace('\\n', '\n').replace('\\"', '"').replace("\\'", "'").strip()
                else:
                    
                    start_idx = query_response.find("validated_output='") + len("validated_output='")
                    end_idx = query_response.find("',\n    reask=", start_idx)
                    if end_idx != -1:
                        raw_content = query_response[start_idx:end_idx]
                        answer = raw_content.replace('\\n', '\n').replace('\\"', '"').replace("\\'", "'").strip()
                    else:
                        answer = "Error parsing validated output."
        else:
            
            answer = query_response.replace("'", "").strip().strip("'").strip()

        
        answer = re.sub(r'\n+$', '', answer).strip()

        
        return ChatResponse(response=answer)

    except Exception as e:
        print("Error in /chatbot:", e)
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/chatbot/create-widget", response_model=ChatResponse)
async def create_widget_endpoint(
    request: ChatRequest,
    authorization: Optional[str] = Header(default=None),
):
    try:
        user_input = request.user_message
        auth_token = None
        if authorization and authorization.lower().startswith("bearer "):
            auth_token = authorization.split(" ", 1)[1].strip()

        session_id = request.session_id or (f"token-{auth_token}" if auth_token else f"session-{uuid.uuid4()}")

        widget_result = widget_creation_agent.handle_message(
            user_message=user_input,
            session_id=session_id,
            auth_token=auth_token,
        )
        if widget_result.get("handled"):
            return ChatResponse(response=str(widget_result.get("response", "")))

        return ChatResponse(
            response=(
                "This endpoint is for widget creation only. "
                "Please provide a create-widget request, for example: "
                "'create gauge widget dashboard 1 project 5 variable temperature'."
            )
        )
    except Exception as e:
        print("Error in /chatbot/create-widget:", e)
        raise HTTPException(status_code=500, detail=str(e))
# python -m uvicorn src.main.chatbotapi:app --reload