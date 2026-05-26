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

from settings import BASE_DIR, GOOGLE_API_KEY
from src.utils.yaml_loader import load_prompts
from src.tools.auth_tools import verify_user_is_active_tool
from src.tools.tool_create_dashboard import tool_create_dashboard
from src.tools.tool_create_project import tool_create_project
from src.tools.tool_create_variable import tool_create_variable
from src.tools.tool_read_dashboards import fetch_dashboard_summary_tool
from src.tools.tool_read_variables import fetch_project_variables_tool
from src.tools.tool_read_chart_mapping import fetch_chart_type_mapping_tool
from src.tools.tool_auto_create_device_widgets import tool_auto_create_device_widgets

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
            tool_auto_create_device_widgets,
        ]

        # Initialize LLM
        llm = ChatGoogleGenerativeAI(
            model="gemini-2.5-flash",
            temperature=0.1,
            google_api_key=GOOGLE_API_KEY,
            max_retries=2,
        )

        # Build dynamic prompt with user context loaded from prompts.yml
        prompts = load_prompts(str(BASE_DIR / "src" / "utils" / "prompts.yml"))
        raw_prompt = prompts.get("infiiot_agent_prompt")
        system_prompt = raw_prompt.format(user_id=user_id, auth_token=auth_token)

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
