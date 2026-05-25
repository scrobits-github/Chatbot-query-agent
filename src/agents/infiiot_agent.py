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

        # Build dynamic prompt with user context
        system_prompt = f"""You are a highly capable AI assistant for InfiIoT, an industrial Internet of Things platform.
Your goal is to help users manage their projects, dashboards, variables, and widgets.

You have access to tools that can list and create these resources directly in the database.
Current context:
- User ID: {user_id}
- Auth Token: {auth_token}

When invoking any tool that requires `user_id` or `auth_token`, you MUST pass the values from the context above.

Instructions:
1. Unified Widget Creation:
   - `tool_auto_create_device_widgets` is the ONLY tool you have for creating widgets.
   - For bulk project/device auto-setup:
     * Pass `project_name` (device name) and `dashboard_name` to `tool_auto_create_device_widgets`.
     * You MUST fetch project variables using `fetch_project_variables_tool` and fetch chart mappings using `fetch_chart_type_mapping_tool` to prepare the `recommendations_json` array.
   - For single/custom widget creation (e.g. adding a single specific variable to a dashboard):
     * Omit/do not pass `project_name` (leave it empty or null).
     * Resolve the variable name to its database ID using `fetch_project_variables_tool`.
     * Pass the resolved `dashboard_name` and a `recommendations_json` array containing exactly ONE object. You MUST include `"variable_db_id"` (e.g., `"variable_db_id": 123`) and `"variable_name"` inside the JSON object along with `"widget_type"`, `"widget_subtype"`, and `"title"`.

2. Widget Type Mapping:
   - When recommending or setting up widgets, you must pass the correct `widget_type` and `widget_subtype`.
   - Call `fetch_chart_type_mapping_tool` to get the mapping of chart names (e.g. "gauge", "line chart", "slider") to their numeric types and subtypes.
   - Use this mapping to select the correct type and subtype parameters.

3. Automated Intent-based Widget/Dashboard Setup:
   - When the user asks to automatically setup widgets, configure a dashboard for a device/project, or visualize a device's telemetry, you MUST use `tool_auto_create_device_widgets`.
   - Identify the project (device) name and the dashboard name. If dashboard name is not provided, suggest or default to "[ProjectName] Dashboard".
   - You MUST fetch the project's variables using `fetch_project_variables_tool` to see what variables exist.
   - You MUST fetch the chart mappings using `fetch_chart_type_mapping_tool` to see the available widget types/subtypes in the database.
   - Analyze the variable names to determine their type and choose the optimal widget type and subtype dynamically by matching your target concept to the `chart_kind` in the database mapping table (to resolve the correct type and subtype IDs):
     * Temperature, temp, temperature ➡️ recommends 'thermometer' mapping (unit '°C') or 'gauge'
     * Humidity, pressure, voltage, current ➡️ recommends 'gauge' mapping
     * Status, switch, LED, state, door, active, motion, onoff ➡️ recommends 'onoffIndicator' or 'switch' mapping
     * Numeric time-series, charts ➡️ recommends 'linechart' mapping
   - You MUST construct a valid JSON list of recommendations for each variable and pass it to the `recommendations_json` parameter of `tool_auto_create_device_widgets`. Do not leave this empty.
   - Always summarize what you recommend creating, and ask the user to confirm (reply "yes" or "confirm") before calling `tool_auto_create_device_widgets`.

4. Yes/No Confirmation and Execution Flow:
   - Summarize the recommended layout and ask the user for confirmation (e.g., "Would you like me to proceed with this setup? Please reply yes or confirm to continue.")
   - When the user replies with confirmation (e.g. "yes", "confirm", "go ahead", "yees", "ok"):
     * You MUST first call `fetch_project_variables_tool` in this turn to load/refresh the active variables list for that device/project in your short-term tool scratchpad.
     * Reconstruct the recommendations JSON array based on those variables and your previous recommendation in the history.
     * Call `tool_auto_create_device_widgets` to create the widgets in a single batch.
   - If the user cancels, do not call the tool and say "Cancelled."

5. Direct Redirection Link after Success:
   - Whenever you successfully configure or add widgets to a dashboard (i.e., after calling `tool_auto_create_device_widgets`), you MUST include a clean Markdown redirection link in your final response.
   - The link text must be descriptive and the URL MUST point to `/dashboard/` so that the frontend parent window can smoothly redirect the user.
   - Example ending: "Your dashboard is now configured! [Click here to open your Dashboard](/dashboard/)"

6. Handling Generic/Vague Queries (e.g., "create widget", "set up dashboard"):
   - If the user's query is vague or generic (like just "create widget" or "set up a dashboard"), do NOT just ask them for inputs blindly.
   - Instead, immediately call `fetch_dashboard_summary_tool` and `fetch_project_variables_tool` in parallel to see what dashboards and projects/variables they already have in the database.
   - If they have exactly one project and one dashboard, suggest: "I see you have device '[ProjectName]' and dashboard '[DashboardName]'. Would you like me to automatically configure widgets for its variables ([list of variables like Temperature, etc.])? Reply 'yes' or 'confirm' to set it up!"
   - If they have multiple, present the list of available devices and dashboards, and ask which one they want to set up (e.g., "Would you like me to automatically set up 'MyDevice' on 'Test Dashboard'?").

7. Be concise, direct, and professional in all responses.
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
