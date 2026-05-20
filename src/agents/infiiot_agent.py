"""
Infiiot agent: Orchestrates authenticated Infiiot operations dynamically using a Gemini tool-calling agent.
Replaces the static parser with dynamic LLM-driven reasoning and tool calling.
"""

from __future__ import annotations

import json
import logging
from typing import Dict, List, Optional

from langchain_core.messages import HumanMessage, AIMessage, BaseMessage
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain.agents import create_tool_calling_agent, AgentExecutor
from langchain.prompts import ChatPromptTemplate, MessagesPlaceholder

from settings import GOOGLE_API_KEY
from src.tools.auth_tools import verify_user_is_active_tool
from src.tools.tool_create_widget import tool_create_widget
from src.tools.tool_create_dashboard import tool_create_dashboard
from src.tools.tool_create_project import tool_create_project
from src.tools.tool_create_variable import tool_create_variable
from src.tools.tool_read_dashboards import fetch_dashboard_summary_tool
from src.tools.tool_read_variables import fetch_project_variables_tool
from src.tools.tool_read_chart_mapping import fetch_chart_type_mapping_tool

logger = logging.getLogger(__name__)

class InfiiotAgent:
    """Handles Infiiot-specific chat dynamically using a LangChain tool-calling agent with Gemini."""

    def __init__(self) -> None:
        self._history: Dict[str, List[BaseMessage]] = {}

    def has_active_session(self, session_id: str) -> bool:
        # Pin to InfiIoT only if there is a pending confirmation or clarification question
        if session_id not in self._history or not self._history[session_id]:
            return False
            
        # Find the last AIMessage in the history
        last_ai_msg = None
        for msg in reversed(self._history[session_id]):
            if isinstance(msg, AIMessage):
                last_ai_msg = msg
                break
                
        if not last_ai_msg or not last_ai_msg.content:
            return False
            
        text = last_ai_msg.content.lower()
        
        # We only pin if the last AI message was asking for confirmation, clarification, or input
        # e.g., "confirm", "yes or", "proceed", "would you like to create", "are you sure", "?"
        confirmation_keywords = [
            "confirm", "yes or", "proceed", "would you like", "are you sure", 
            "reply 'yes'", "choose", "select", "which dashboard", "which variable", 
            "what is the name", "please provide"
        ]
        
        return "?" in text or any(kw in text for kw in confirmation_keywords)

    def _get_user_id(self, auth_token: Optional[str]) -> Optional[int]:
        if not auth_token:
            return None
        try:
            res = json.loads(verify_user_is_active_tool.invoke({"auth_token": auth_token}))
            return res.get("user_id") if res.get("ok") and res.get("is_active") else None
        except Exception as e:
            logger.error(f"Failed to verify active user status: {e}")
            return None

    def handle_message(self, user_message: str, session_id: str, auth_token: Optional[str]) -> Dict[str, object]:
        """
        Dynamically handles the chatbot message by executing the LangChain Gemini agent with InfiIoT tools.
        """
        # Always verify token and user status first
        user_id = self._get_user_id(auth_token)
        if not user_id:
            return {"handled": True, "response": "Authentication required. Please provide a valid auth token."}

        # Clear session if the user says cancel / reset
        lowered = (user_message or "").strip().lower()
        if lowered in ["cancel", "reset", "clear"]:
            self._history.pop(session_id, None)
            return {"handled": True, "response": "Flow cancelled and session history cleared."}

        # Retrieve or initialize chat history
        if session_id not in self._history:
            self._history[session_id] = []

        # Create tools list
        tools = [
            fetch_dashboard_summary_tool,
            fetch_project_variables_tool,
            fetch_chart_type_mapping_tool,
            tool_create_dashboard,
            tool_create_project,
            tool_create_variable,
            tool_create_widget,
        ]

        # Initialize LLM
        llm = ChatGoogleGenerativeAI(
            model="gemini-2.5-flash",
            temperature=0.1,
            google_api_key=GOOGLE_API_KEY,
            max_retries=2,
        )

        # Build dynamic prompt with user context
        system_prompt = f"""You are a highly capable AI assistant for InfiIoT, an industrial Internet of Things platform.
Your goal is to help users manage their projects, dashboards, variables, and widgets.

You have access to tools that can list and create these resources directly in the database.
Current context:
- User ID: {user_id}
- Auth Token: {auth_token}

When invoking any tool that requires `user_id` or `auth_token`, you MUST pass the values from the context above.

Instructions:
1. Always resolve names to IDs when required:
   - When creating a widget, you need a dashboard database ID (`dashboard_db_id`) and variable database ID (`variable_db_id`).
   - If the user specifies a dashboard name or variable name, first search for them by calling `fetch_dashboard_summary_tool` and `fetch_project_variables_tool` to find their correct database IDs.
   - If you cannot find the requested dashboard or variable in the list, inform the user and ask if they would like to create them.

2. Widget Type Mapping:
   - When creating a widget, you must pass the correct `widget_type` and `widget_subtype`.
   - Call `fetch_chart_type_mapping_tool` to get the mapping of chart names (e.g. "gauge", "line chart", "slider") to their numeric types and subtypes.
   - Use this mapping to select the correct type and subtype parameters.

3. Always confirm before creation:
   - Before invoking any creation tools (`tool_create_dashboard`, `tool_create_project`, `tool_create_variable`, `tool_create_widget`), summarize what you are going to create and ask the user for confirmation (reply with 'yes' or 'confirm' to proceed) UNLESS the user has already explicitly given confirmation in their prompt.
   - If you ask for confirmation and the user replies with a positive confirmation (e.g. "yes", "go ahead", "confirm"), proceed to call the creation tool in the next step.
   - If the user cancels, do not call the tool and say "Cancelled."

4. Be concise, direct, and professional in all responses.
"""

        prompt = ChatPromptTemplate.from_messages([
            ("system", system_prompt),
            MessagesPlaceholder(variable_name="chat_history"),
            ("human", "{input}"),
            MessagesPlaceholder(variable_name="agent_scratchpad"),
        ])

        # Construct Agent
        agent = create_tool_calling_agent(llm, tools, prompt)
        agent_executor = AgentExecutor(
            agent=agent,
            tools=tools,
            verbose=True,
            max_iterations=5,
            early_stopping_method="generate"
        )

        try:
            # Execute agent
            res = agent_executor.invoke({
                "input": user_message,
                "chat_history": self._history[session_id]
            })
            output = res.get("output", "")
            
            # Save history
            self._history[session_id].append(HumanMessage(content=user_message))
            self._history[session_id].append(AIMessage(content=output))
            
            # Keep history capped to last 14 messages (7 turns) to avoid exceeding token limit
            if len(self._history[session_id]) > 14:
                self._history[session_id] = self._history[session_id][-14:]

            return {"handled": True, "response": output}
            
        except Exception as e:
            logger.error(f"Error in dynamic InfiIoT agent: {e}", exc_info=True)
            return {"handled": True, "response": f"An error occurred while executing InfiIoT request: {str(e)}"}

infiiot_agent = InfiiotAgent()
