"""
Infiiot agent: Orchestrates authenticated Infiiot operations from the AI backend.
Refactored into a modular structure for better readability.
"""

from __future__ import annotations

import json
import os
from typing import Dict, List, Optional, Tuple

from src.infiiot import db_readonly
from src.infiiot.parser import InfiiotParser
from src.infiiot.sessions import WidgetDraft
from src.tools.auth_tools import verify_user_is_active_tool
from src.tools.tool_create_widget import tool_create_widget
from src.tools.tool_create_dashboard import tool_create_dashboard
from src.tools.tool_create_project import tool_create_project
from src.tools.tool_create_variable import tool_create_variable

WIDGET_KEYWORD_MAPPING: Dict[str, Tuple[int, str, str]] = {
    "line chart": (1, "1", "linechart"),
    "linechart": (1, "1", "linechart"),
    "double axis": (1, "2", "doubleAxis"),
    "scatter plot": (1, "3", "scatterplot"),
    "bar chart": (1, "4", "barchart"),
    "pie": (2, "", "pie"),
    "average": (3, "1", "average"),
    "maximum": (3, "2", "maximum"),
    "minimum": (3, "3", "minimum"),
    "sum": (3, "4", "sum"),
    "count": (3, "5", "count"),
    "last value": (3, "6", "last value"),
    "table": (4, "1", "table"),
    "on off indicator": (5, "1", "onoffIndicator"),
    "onoffindicator": (5, "1", "onoffIndicator"),
    "gauge": (5, "2", "gauge"),
    "thermometer": (5, "3", "thermometer"),
    "switch": (6, "1", "switch"),
    "slider": (6, "2", "slider"),
}

YES_WORDS = {"yes", "y", "confirm", "ok", "okay", "create"}
NO_WORDS = {"no", "n", "cancel", "stop"}

class InfiiotAgent:
    """Handles Infiiot-specific chat: widget flows + optional read-only DB hints."""

    def __init__(self) -> None:
        self._sessions: Dict[str, WidgetDraft] = {}
        self.parser = InfiiotParser()
        self.widget_mapping: Dict[str, Tuple[int, str, str]] = {}

    def _load_mapping(self):
        """Load mapping from ai_widget_chart_mapping table."""
        print("DEBUG: Loading widget mapping from DB...")
        try:
            rows = db_readonly.fetch_widget_chart_mappings()
            print(f"DEBUG: Found {len(rows)} mapping rows in DB.")
            for r_type, r_subtype, r_kind in rows:
                self.widget_mapping[r_kind.lower()] = (int(r_type), str(r_subtype), r_kind)
        except Exception as e:
            print(f"DEBUG: Mapping load failed: {e}")
            pass

    def has_active_session(self, session_id: str) -> bool:
        return session_id in self._sessions

    def handle_message(self, user_message: str, session_id: str, auth_token: Optional[str]) -> Dict[str, object]:
        """
        The main entrance for the chatbot. 
        It decides if the message is for creating a widget, a project, or just a list request.
        """
        # Always refresh mapping if it's empty
        if not self.widget_mapping:
            self._load_mapping()
        text = (user_message or "").strip()
        lowered = text.lower()

        # STEP 1: Verify the user is authenticated via their Token
        user_id = self._get_user_id(auth_token)
        if auth_token and not user_id:
            return {"handled": True, "response": "Authentication failed: User inactive or token invalid."}

        # STEP 2: Detect Intent first to decide if we should start fresh or continue
        is_new_widget = self.parser.is_widget_create_intent(lowered)
        
        draft = self._sessions.get(session_id)
        if draft and user_id:
            draft.user_id = user_id

        # If it's a NEW widget request, we start fresh and discard any old draft
        if is_new_widget:
            return self._start_widget_flow(text, lowered, auth_token, session_id, user_id)

        # If not a new request, but we have an old draft, continue it
        if draft:
            return self._continue_flow(draft, lowered, auth_token, session_id)

        # STEP 3: Handle other requests (Read-only, Variable, Project, Dashboard)
        if self._is_scope_question(lowered):
            if not auth_token:
                return {"handled": True, "response": "Authentication required to look up dashboards/variables."}
            return {"handled": True, "response": self._readonly_scope_answer(auth_token)}

        if self.parser.is_variable_create_intent(lowered):
            return self._handle_variable_create(text, lowered, auth_token, user_id)

        if self.parser.is_project_create_intent(lowered):
            return self._handle_project_create(text, lowered, auth_token, user_id)

        if self.parser.is_dashboard_create_intent(lowered):
            return self._handle_dashboard_create(text, lowered, auth_token, user_id)

        # If it doesn't match anything, we let the normal AI handle it.
        return {"handled": False}

    def _get_user_id(self, auth_token: Optional[str]) -> Optional[int]:
        if not auth_token:
            return None
        res = json.loads(verify_user_is_active_tool.invoke({"auth_token": auth_token}))
        return res.get("user_id") if res.get("ok") and res.get("is_active") else None

    def _start_widget_flow(self, text: str, lowered: str, auth_token: str, session_id: str, user_id: Optional[int]) -> Dict[str, object]:
        if not auth_token:
            return {"handled": True, "response": "Authentication is required for Infiiot widget actions."}
            
        detected = self._detect_widget_type(lowered)
        if not detected:
            return {"handled": True, "response": "Please specify widget type (e.g. gauge, line chart)."}

        w_type_id, w_sub_type, w_label = detected
        dash_id = self.parser.extract_number(lowered, "dashboard")
        if dash_id is None and user_id:
            dash_name = self.parser.extract_dashboard_name(text)
            if dash_name:
                dash_id = db_readonly.resolve_dashboard_id_by_name(user_id, dash_name)

        var_name = self.parser.extract_variable_name(text)
        proj_id = self.parser.extract_number(lowered, "project")
        if proj_id is None and user_id:
            proj_name = self.parser.extract_project_name(text)
            if proj_name:
                proj_id = db_readonly.resolve_project_id_by_name(user_id, proj_name)
            elif var_name:
                proj_id = db_readonly.resolve_project_id_by_variable_name(user_id, var_name)

        draft = WidgetDraft(
            widget_label=w_label, widget_type_id=str(w_type_id), widget_sub_type=w_sub_type,
            dashboard_id=dash_id, project_id=proj_id, variable_name=var_name,
            title=self.parser.extract_title(text), user_id=user_id
        )
        self._sessions[session_id] = draft

        hint = self._optional_user_scope_hint(auth_token)
        reply = self._continue_flow(draft, lowered, auth_token, session_id)
        if hint and "response" in reply:
            reply["response"] = f"{hint}\n\n{reply['response']}"
        return reply

    def _handle_variable_create(self, text: str, lowered: str, auth_token: str, user_id: int) -> Dict[str, object]:
        if not auth_token: return {"handled": True, "response": "Authentication required."}
        v_name = self.parser.extract_variable_name(text)
        if not v_name: return {"handled": True, "response": "Please provide variable name."}
        p_name = self.parser.extract_project_name(text)
        if not p_name: return {"handled": True, "response": "Please specify project name."}
        unit = self.parser.extract_unit(text) or "unit"
        
        raw = tool_create_variable.invoke({"auth_token": auth_token, "user_id": user_id, "project_name": p_name, "variable_name": v_name, "unit": unit})
        res = json.loads(str(raw))
        return {"handled": True, "response": res.get("message", "Variable created.")}

    def _handle_project_create(self, text: str, lowered: str, auth_token: str, user_id: int) -> Dict[str, object]:
        if not auth_token: return {"handled": True, "response": "Authentication required."}
        p_name = self.parser.extract_project_name(text)
        if not p_name: return {"handled": True, "response": "Please provide project name."}
        raw = tool_create_project.invoke({"auth_token": auth_token, "project_name": p_name, "user_id": user_id})
        res = json.loads(str(raw))
        return {"handled": True, "response": res.get("message", "Project created.")}

    def _handle_dashboard_create(self, text: str, lowered: str, auth_token: str, user_id: int) -> Dict[str, object]:
        if not auth_token: return {"handled": True, "response": "Authentication required."}
        d_name = self.parser.extract_dashboard_name(text)
        if not d_name: return {"handled": True, "response": "Please provide dashboard name."}
        raw = tool_create_dashboard.invoke({"auth_token": auth_token, "dashboard_name": d_name, "user_id": user_id})
        res = json.loads(str(raw))
        return {"handled": True, "response": res.get("message", "Dashboard created.")}

    def _continue_flow(self, draft: WidgetDraft, lowered: str, auth_token: str, session_id: str) -> Dict[str, object]:
        if lowered in NO_WORDS:
            self._sessions.pop(session_id, None)
            return {"handled": True, "response": "Cancelled."}

        # Collect missing fields with helpful hints
        if draft.dashboard_id is None:
            draft.dashboard_id = self.parser.extract_number(lowered, "dashboard") or (db_readonly.resolve_dashboard_id_by_name(draft.user_id, self.parser.extract_dashboard_name(lowered)) if draft.user_id else None)
            if draft.dashboard_id is None:
                hint = ""
                if draft.user_id:
                    dashes = db_readonly.fetch_dashboard_summary_for_user(draft.user_id, limit=5)
                    if dashes: hint = "\nExisting Dashboards: " + ", ".join(d[1] for d in dashes)
                return {"handled": True, "response": f"Please provide dashboard name or ID.{hint}"}

        if draft.project_id is None:
            draft.project_id = self.parser.extract_number(lowered, "project") or (db_readonly.resolve_project_id_by_name(draft.user_id, self.parser.extract_project_name(lowered)) if draft.user_id else None)
            if draft.project_id is None and draft.variable_name and draft.user_id:
                draft.project_id = db_readonly.resolve_project_id_by_variable_name(draft.user_id, draft.variable_name)
            if draft.project_id is None:
                hint = ""
                if draft.user_id:
                    projs = db_readonly.fetch_projects_for_user(draft.user_id, limit=5)
                    if projs: hint = "\nExisting Projects: " + ", ".join(p[1] for p in projs)
                return {"handled": True, "response": f"Please provide project name or ID.{hint}"}

        if draft.variable_name is None:
            draft.variable_name = self.parser.extract_variable_name(lowered)
            if not draft.variable_name:
                hint = ""
                if draft.user_id and draft.project_id:
                    vars = db_readonly.fetch_variables_for_user_projects(draft.user_id, limit=20)
                    relevant = [v[1] for v in vars if v[2] == draft.project_id]
                    if relevant: hint = "\nExisting Variables in this project: " + ", ".join(relevant[:10])
                return {"handled": True, "response": f"Please provide variable name.{hint}"}

        # Final Confirmation
        if lowered not in YES_WORDS:
            return {"handled": True, "response": f"Create {draft.widget_label} (dash={draft.dashboard_id}, proj={draft.project_id}, var={draft.variable_name})? Reply yes/no."}

        # Execute Creation
        v_db_id = db_readonly.resolve_variable_id_by_project_id(draft.user_id, draft.project_id, draft.variable_name)
        if v_db_id is None:
            return {
                "handled": True,
                "response": f"Error: Could not find variable '{draft.variable_name}' in project ID {draft.project_id}. Please check the name and try again."
            }

        payload = {
            "widgetType": draft.widget_type_id, "widgetSubtype": draft.widget_sub_type,
            "project": draft.project_id, "variable": draft.variable_name,
            "title": draft.title or f"{draft.widget_label.title()} Widget",
            "dashboard_id": draft.dashboard_id, "user_id": draft.user_id,
            "variable_id": v_db_id
        }
        
        raw = tool_create_widget.invoke({
            "auth_token": auth_token, "user_id": draft.user_id, "dashboard_db_id": draft.dashboard_id,
            "variable_db_id": v_db_id, "widget_type": str(payload["widgetType"]),
            "widget_subtype": str(payload["widgetSubtype"]), "title": payload["title"], "payload_json": json.dumps(payload)
        })
        self._sessions.pop(session_id, None)
        res = json.loads(str(raw))
        return {"handled": True, "response": res.get("message", "Done.")}

    def _detect_widget_type(self, text: str) -> Optional[Tuple[int, str, str]]:
        """Map free-text widget keyword to (widget_type_id, widget_sub_type, widget_label)."""
        # 1. Try dynamic mapping from DB (ai_widget_chart_mapping)
        for k, v in sorted(self.widget_mapping.items(), key=lambda x: -len(x[0])):
            if k in text: 
                return v
        # 2. Fallback to hardcoded mapping
        for k, v in sorted(WIDGET_KEYWORD_MAPPING.items(), key=lambda x: -len(x[0])):
            if k in text: 
                return v
        return None

    def _is_scope_question(self, text: str) -> bool:
        return ("list" in text or "show" in text) and ("dashboard" in text or "variable" in text)

    def _optional_user_scope_hint(self, auth_token: str) -> str:
        uid = db_readonly.resolve_user_id_from_token(auth_token)
        if not uid: return ""
        
        dashboards = db_readonly.fetch_dashboard_summary_for_user(uid, limit=5)
        projects = db_readonly.fetch_projects_for_user(uid, limit=5)
        variables = db_readonly.fetch_variables_for_user_projects(uid, limit=5)
        
        d_str = ", ".join(str(d[1]) for d in dashboards)
        p_str = ", ".join(str(p[1]) for p in projects)
        v_str = ", ".join(str(v[1]) for v in variables)
        
        lines = []
        if d_str: lines.append(f"Existing Dashboards: [{d_str}]")
        if p_str: lines.append(f"Existing Projects: [{p_str}]")
        if v_str: lines.append(f"Existing Variables: [{v_str}]")
        
        return "\n".join(lines) if lines else ""

    def _readonly_scope_answer(self, auth_token: str) -> str:
        uid = db_readonly.resolve_user_id_from_token(auth_token)
        if not uid: return "User not found."
        dashboards = db_readonly.fetch_dashboard_summary_for_user(uid, limit=20)
        variables = db_readonly.fetch_variables_for_user_projects(uid, limit=50)
        return f"User ID: {uid}\nDashboards: {dashboards}\nVariables: {variables}"

infiiot_agent = InfiiotAgent()
