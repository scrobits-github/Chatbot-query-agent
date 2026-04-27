"""
Infiiot agent: authenticated Infiiot operations from the AI backend.

Responsibilities:
- Enforce auth at the start of new Infiiot/widget flows (token required).
- Optional read-only DB context (dashboards, variables, chart mapping) for hints.
- Widget creation via existing Infiiot HTTP endpoints (POST with Token header).

Widget creation state is keyed by session_id (same id across turns in the client).
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

from src.infiiot import db_readonly
from src.tools.infiiot_tools import (
    create_dashboard_tool,
    create_project_tool,
    create_variable_tool,
    create_widget_tool,
    resolve_project_name_by_id_tool,
)

@dataclass
class WidgetDraft:
    widget_label: str
    widget_type_id: int
    widget_sub_type: str
    dashboard_id: Optional[int] = None
    project_id: Optional[int] = None
    variable_name: Optional[str] = None
    title: Optional[str] = None
    awaiting_confirmation: bool = False
    # When dashboard id is invalid, agent can create one and resume flow.
    pending_dashboard_create: bool = False
    dashboard_name_to_create: Optional[str] = None
    # When project id is invalid, agent can create one and resume flow.
    pending_project_create: bool = False
    project_name_to_create: Optional[str] = None


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
        """Initialize in-memory session state and Infiiot endpoint configuration."""
        # Per-session widget creation drafts (multi-turn).
        self._sessions: Dict[str, WidgetDraft] = {}
        # Base URL for Django/Infiiot service (required for widget creation calls).
        self.base_url = os.getenv("INFIIOT_BASE_URL", "").rstrip("/")
        # Endpoint mapping aligned with existing dashboard views in infiIOT-chat-assistant.
        self.endpoint_map = {
            "linechart": "/dashboard/lineChart",
            "doubleAxis": "/dashboard/doubleAxis",
            "scatterplot": "/dashboard/scatter-plot",
            "barchart": "/dashboard/barChart",
            "pie": "/dashboard/label",
            "average": "/dashboard/label",
            "maximum": "/dashboard/label",
            "minimum": "/dashboard/label",
            "sum": "/dashboard/label",
            "count": "/dashboard/label",
            "last value": "/dashboard/label",
            "gauge": "/dashboard/gauge",
            "switch": "/dashboard/switch",
            "slider": "/dashboard/slider",
            "thermometer": "/dashboard/thermometer",
            "table": "/dashboard/table",
            "onoffIndicator": "/dashboard/on_off_indicator",
        }

    def has_active_session(self, session_id: str) -> bool:
        """True if this session has an in-progress widget draft (for supervisor routing)."""
        return session_id in self._sessions

    def handle_message(
        self, user_message: str, session_id: str, auth_token: Optional[str]
    ) -> Dict[str, object]:
        """
        Main Infiiot entrypoint for one chat turn.

        Flow:
        - Handle read-only listing questions.
        - Continue an existing widget draft if present.
        - Start widget create flow, or direct dashboard/project create intents.
        - Return {"handled": False} when the message is not an Infiiot request.
        """
        text = (user_message or "").strip()
        lowered = text.lower()

        draft = self._sessions.get(session_id)

        # --- Read-only "what are my dashboards / variables" style questions ---
        if not draft and self._is_scope_question(lowered):
            if not auth_token:
                return {
                    "handled": True,
                    "response": "Authentication required to look up your dashboards and variables.",
                }
            return {"handled": True, "response": self._readonly_scope_answer(auth_token)}

        if draft:
            return self._continue_flow(draft, lowered, auth_token, session_id)

        # --- Widget flow should take priority over create-dashboard wording ---
        if self._is_widget_create_intent(lowered):
            if not auth_token:
                return {
                    "handled": True,
                    "response": (
                        "Authentication is required for Infiiot widget actions. "
                        "Send Authorization: Bearer <token> with your request."
                    ),
                }

            detected = self._detect_widget_type(lowered)
            if not detected:
                return {
                    "handled": True,
                    "response": (
                        "Please specify widget type: line chart, bar chart, pie, gauge, switch, slider."
                    ),
                }

            widget_type_id, widget_sub_type, widget_label = detected
            draft = WidgetDraft(
                widget_label=widget_label,
                widget_type_id=widget_type_id,
                widget_sub_type=widget_sub_type,
                dashboard_id=self._extract_number(lowered, "dashboard"),
                project_id=self._extract_number(lowered, "project"),
                variable_name=self._extract_variable_name(text),
                title=self._extract_title(text),
            )
            self._sessions[session_id] = draft

            # First turn: optional read-only hint (dashboards / variables) for this user.
            hint = self._optional_user_scope_hint(auth_token)
            flow_reply = self._continue_flow(draft, lowered, auth_token, session_id)
            if hint and isinstance(flow_reply.get("response"), str):
                flow_reply["response"] = f"{hint}\n\n{flow_reply['response']}"
            return flow_reply

        # --- Direct dashboard creation intent ---
        if self._is_dashboard_create_intent(lowered):
            if not auth_token:
                return {
                    "handled": True,
                    "response": "Authentication is required to create a dashboard. Send Authorization: Bearer <token>.",
                }
            dashboard_name = self._extract_dashboard_name(text)
            if not dashboard_name:
                return {
                    "handled": True,
                    "response": "Please provide dashboard name. Example: create dashboard DemoBoard",
                }
            ok, created_dashboard_id, message = self._create_dashboard(auth_token, dashboard_name)
            if ok:
                return {
                    "handled": True,
                    "response": f"Dashboard '{dashboard_name}' created successfully (dashboard_id={created_dashboard_id}).",
                }
            return {"handled": True, "response": f"Dashboard create failed: {message}"}

        # --- Direct project/device creation intent (token-based API) ---
        if self._is_project_create_intent(lowered):
            if not auth_token:
                return {
                    "handled": True,
                    "response": "Authentication is required to create a project. Send Authorization: Bearer <token>.",
                }
            project_name = self._extract_project_name(text)
            if not project_name:
                return {
                    "handled": True,
                    "response": "Please provide project name. Example: create project PumpRoomA",
                }
            ok, created_project_id, message = self._create_project(auth_token, project_name)
            if ok:
                return {
                    "handled": True,
                    "response": f"Project '{project_name}' created successfully (project_id={created_project_id}).",
                }
            return {"handled": True, "response": f"Project create failed: {message}"}

        # --- Direct variable creation intent (token-based API) ---
        if self._is_variable_create_intent(lowered):
            if not auth_token:
                return {
                    "handled": True,
                    "response": "Authentication is required to create a variable. Send Authorization: Bearer <token>.",
                }
            variable_name = self._extract_variable_name(text)
            if not variable_name:
                return {
                    "handled": True,
                    "response": "Please provide variable name. Example: create variable temperature",
                }
            project_name = self._extract_project_name(text)
            project_id = self._extract_number(lowered, "project")
            if not project_name and project_id is not None:
                project_name = self._resolve_project_name_by_id(auth_token, project_id)
            if not project_name:
                return {
                    "handled": True,
                    "response": (
                        "Please provide project name or id. "
                        "Example: create variable temperature project PumpRoomA or project 1"
                    ),
                }
            unit = self._extract_unit(text) or "unit"
            ok, message = self._create_variable(auth_token, project_name, variable_name, unit)
            if ok:
                return {
                    "handled": True,
                    "response": (
                        f"Variable '{variable_name}' created/updated successfully "
                        f"under project '{project_name}' (unit={unit})."
                    ),
                }
            return {"handled": True, "response": f"Variable create failed: {message}"}

        return {"handled": False}

    def _optional_user_scope_hint(self, auth_token: str) -> str:
        """Attach a short read-only summary if DB credentials are configured."""
        uid = db_readonly.resolve_user_id_from_token(auth_token)
        if uid is None:
            return ""
        dashboards = db_readonly.fetch_dashboard_summary_for_user(uid, limit=20)
        variables = db_readonly.fetch_variables_for_user_projects(uid, limit=30)
        parts: List[str] = []
        if dashboards:
            dash_str = ", ".join(f"{d[0]}:{d[1]}" for d in dashboards[:10])
            parts.append(f"Your dashboards (id:name): {dash_str}")
        if variables:
            var_str = ", ".join(f"{v[2]}/{v[1]}" for v in variables[:10])
            parts.append(f"Sample variables (project_id/name): {var_str}")
        return " ".join(parts) if parts else ""

    def _readonly_scope_answer(self, auth_token: str) -> str:
        """Full read-only answer for dashboard/variable listing questions."""
        uid = db_readonly.resolve_user_id_from_token(auth_token)
        if uid is None:
            return "Could not resolve your user from the token (check DB read access or token value)."
        dashboards = db_readonly.fetch_dashboard_summary_for_user(uid, limit=50)
        variables = db_readonly.fetch_variables_for_user_projects(uid, limit=100)
        mappings = db_readonly.fetch_widget_chart_mappings(limit=100)
        lines = [f"User id: {uid}", ""]
        lines.append("Dashboards (dashboard_id, name, default):")
        if dashboards:
            for d in dashboards:
                lines.append(f"  - {d[0]} | {d[1]} | default={d[2]}")
        else:
            lines.append("  (none or DB not configured)")
        lines.append("")
        lines.append("Variables (id, name, project_id, project_name):")
        if variables:
            for v in variables[:50]:
                lines.append(f"  - var_id={v[0]} name={v[1]} project_id={v[2]} project={v[3]}")
        else:
            lines.append("  (none or DB not configured)")
        lines.append("")
        lines.append("Widget chart mapping (widget_type_id, widget_sub_type, chart_kind):")
        if mappings:
            for m in mappings[:30]:
                lines.append(f"  - {m[0]} | {m[1]} | {m[2]}")
        else:
            lines.append("  (none or table missing / DB not configured)")
        return "\n".join(lines)

    @staticmethod
    def _is_scope_question(text: str) -> bool:
        """Return True for read-only list/show questions about dashboards/variables/mapping."""
        if "list" in text or "show" in text or "what are" in text:
            if "dashboard" in text or "variable" in text or "mapping" in text:
                return True
        return False

    def _continue_flow(
        self, draft: WidgetDraft, lowered: str, auth_token: Optional[str], session_id: str
    ) -> Dict[str, object]:
        """
        Continue a multi-turn widget flow until confirm/create or cancel.

        This method collects missing inputs, runs preflight checks, asks confirmation,
        and finally calls the mapped widget create endpoint.
        """
        if draft.pending_dashboard_create:
            return self._handle_pending_dashboard_create(draft, lowered, auth_token)
        if draft.pending_project_create:
            return self._handle_pending_project_create(draft, lowered, auth_token)

        if lowered in NO_WORDS:
            self._sessions.pop(session_id, None)
            return {"handled": True, "response": "Okay, widget creation has been cancelled."}

        if draft.dashboard_id is None:
            dashboard_id = self._extract_number(lowered, "dashboard")
            if dashboard_id is None:
                return {"handled": True, "response": "Please provide dashboard id. Example: dashboard 1"}
            draft.dashboard_id = dashboard_id

        if draft.project_id is None:
            project_id = self._extract_number(lowered, "project")
            if project_id is None:
                return {"handled": True, "response": "Please provide project id. Example: project 5"}
            draft.project_id = project_id

        if draft.variable_name is None:
            variable_name = self._extract_variable_name(lowered)
            if not variable_name:
                return {
                    "handled": True,
                    "response": "Please provide variable name. Example: variable temperature",
                }
            draft.variable_name = variable_name

        if not draft.awaiting_confirmation:
            # Validate collected inputs against read-only DB scope (if configured).
            preflight_error = self._preflight_validate_inputs(draft, auth_token)
            if preflight_error:
                field, message = preflight_error
                # Clear only the invalid field so next user message can refill it.
                if field == "dashboard_id":
                    draft.dashboard_id = None
                    draft.pending_dashboard_create = True
                    if not draft.dashboard_name_to_create:
                        draft.dashboard_name_to_create = self._extract_dashboard_name(lowered)
                    return {
                        "handled": True,
                        "response": (
                            f"{message} If you want, I can create a new dashboard now. "
                            "Reply `yes` (and optionally provide name like `dashboard name DemoBoard`) "
                            "or reply `no` and provide an existing dashboard id."
                        ),
                    }
                elif field == "project_id":
                    draft.project_id = None
                    draft.pending_project_create = True
                    if not draft.project_name_to_create:
                        draft.project_name_to_create = self._extract_project_name(lowered)
                    return {
                        "handled": True,
                        "response": (
                            f"{message} If you want, I can create a new project now. "
                            "Reply `yes` (optionally with `project name PumpRoomA`) "
                            "or reply `no` and provide an existing project id."
                        ),
                    }
                elif field == "variable_name":
                    draft.variable_name = None
                return {"handled": True, "response": message}

            draft.awaiting_confirmation = True
            return {
                "handled": True,
                "response": (
                    f"Do you want me to create a {draft.widget_label} widget? "
                    f"(dashboard_id={draft.dashboard_id}, project={draft.project_id}, variable={draft.variable_name}) "
                    "Reply with yes/no."
                ),
            }

        if lowered not in YES_WORDS:
            return {"handled": True, "response": "To confirm, reply `yes`. To cancel, reply `no`."}

        if not auth_token:
            return {
                "handled": True,
                "response": "Authentication token is missing. Please login and try again.",
            }
        endpoint = self.endpoint_map.get(draft.widget_label)
        if not endpoint:
            return {
                "handled": True,
                "response": (
                    f"No direct create endpoint mapping exists for {draft.widget_label}. "
                    "Currently supported: linechart/doubleAxis/scatterplot/barchart/pie/"
                    "average/maximum/minimum/sum/count/last value/"
                    "gauge/switch/slider/thermometer/table/onoffIndicator."
                ),
            }
        if not self.base_url:
            return {
                "handled": True,
                "response": "Set INFIIOT_BASE_URL in backend env. Example: http://127.0.0.1:8000",
            }

        create_url = f"{self.base_url}{endpoint}"
        payload = self._build_payload(draft)

        ok, message = self._call_create_api(create_url, payload, auth_token)
        self._sessions.pop(session_id, None)
        if ok:
            return {"handled": True, "response": f"Done. {message}"}
        return {"handled": True, "response": f"Widget create failed: {message}"}

    def _handle_pending_dashboard_create(
        self, draft: WidgetDraft, lowered: str, auth_token: Optional[str]
    ) -> Dict[str, object]:
        """Handle auto-step: dashboard missing -> create now?"""
        if lowered in NO_WORDS:
            draft.pending_dashboard_create = False
            draft.dashboard_name_to_create = None
            return {
                "handled": True,
                "response": "Okay. Please provide an existing dashboard id to continue widget creation.",
            }

        if lowered in YES_WORDS or self._is_dashboard_create_intent(lowered):
            if not auth_token:
                return {
                    "handled": True,
                    "response": "Authentication is required to create dashboard. Please login and try again.",
                }
            dashboard_name = self._extract_dashboard_name(lowered) or draft.dashboard_name_to_create
            if not dashboard_name:
                return {
                    "handled": True,
                    "response": "Please provide dashboard name. Example: dashboard name DemoBoard",
                }
            ok, created_dashboard_id, message = self._create_dashboard(auth_token, dashboard_name)
            if not ok or created_dashboard_id is None:
                return {"handled": True, "response": f"Dashboard create failed: {message}"}
            draft.dashboard_id = int(created_dashboard_id)
            draft.pending_dashboard_create = False
            draft.dashboard_name_to_create = dashboard_name
            return {
                "handled": True,
                "response": (
                    f"Dashboard '{dashboard_name}' created (dashboard_id={created_dashboard_id}). "
                    "Now reply `yes` to continue widget creation."
                ),
            }

        # If user sends a numeric dashboard id while pending, accept and continue.
        dashboard_id = self._extract_number(lowered, "dashboard")
        if dashboard_id is not None:
            draft.dashboard_id = dashboard_id
            draft.pending_dashboard_create = False
            draft.dashboard_name_to_create = None
            return {"handled": True, "response": "Got it. Now reply `yes` to continue widget creation."}

        return {
            "handled": True,
            "response": (
                "Reply `yes` to create a new dashboard, or provide an existing dashboard id "
                "(example: dashboard 1)."
            ),
        }

    def _handle_pending_project_create(
        self, draft: WidgetDraft, lowered: str, auth_token: Optional[str]
    ) -> Dict[str, object]:
        """Handle auto-step: project missing -> create now?"""
        if lowered in NO_WORDS:
            draft.pending_project_create = False
            draft.project_name_to_create = None
            return {
                "handled": True,
                "response": "Okay. Please provide an existing project id to continue widget creation.",
            }

        if lowered in YES_WORDS or self._is_project_create_intent(lowered):
            if not auth_token:
                return {
                    "handled": True,
                    "response": "Authentication is required to create project. Please login and try again.",
                }
            project_name = self._extract_project_name(lowered) or draft.project_name_to_create
            if not project_name:
                return {
                    "handled": True,
                    "response": "Please provide project name. Example: project name PumpRoomA",
                }
            ok, created_project_id, message = self._create_project(auth_token, project_name)
            if not ok or created_project_id is None:
                return {"handled": True, "response": f"Project create failed: {message}"}
            draft.project_id = int(created_project_id)
            draft.pending_project_create = False
            draft.project_name_to_create = project_name
            return {
                "handled": True,
                "response": (
                    f"Project '{project_name}' created (project_id={created_project_id}). "
                    "Now reply `yes` to continue widget creation."
                ),
            }

        project_id = self._extract_number(lowered, "project")
        if project_id is not None:
            draft.project_id = project_id
            draft.pending_project_create = False
            draft.project_name_to_create = None
            return {"handled": True, "response": "Got it. Now reply `yes` to continue widget creation."}

        return {
            "handled": True,
            "response": (
                "Reply `yes` to create a new project, or provide an existing project id "
                "(example: project 1)."
            ),
        }

    def _preflight_validate_inputs(
        self, draft: WidgetDraft, auth_token: Optional[str]
    ) -> Optional[Tuple[str, str]]:
        """
        Preflight validation using read-only DB (best-effort).

        If DB read credentials are not configured, this returns None and flow continues.
        If token->user mapping works, validates:
          - dashboard_id belongs to user
          - project_id belongs to user
          - variable_name exists under the selected project
        """
        if not auth_token:
            return None
        if draft.dashboard_id is None or draft.project_id is None or not draft.variable_name:
            return None

        user_id = db_readonly.resolve_user_id_from_token(auth_token)
        if user_id is None:
            # DB read path unavailable or token mapping table not reachable.
            return None

        dashboards = db_readonly.fetch_dashboard_summary_for_user(user_id, limit=200)
        dashboard_ids = {int(d[0]) for d in dashboards if d and d[0] is not None}
        if draft.dashboard_id not in dashboard_ids:
            sample = ", ".join(str(did) for did in sorted(list(dashboard_ids))[:10]) or "none"
            return (
                "dashboard_id",
                f"Dashboard id {draft.dashboard_id} is not available for this authenticated user. "
                f"Available dashboard ids: {sample}. Please provide a valid dashboard id."
            )

        variables = db_readonly.fetch_variables_for_user_projects(user_id, limit=500)
        project_ids = {int(v[2]) for v in variables if len(v) >= 3 and v[2] is not None}
        if draft.project_id not in project_ids:
            sample = ", ".join(str(pid) for pid in sorted(list(project_ids))[:10]) or "none"
            return (
                "project_id",
                f"Project id {draft.project_id} is not available for this authenticated user. "
                f"Available project ids: {sample}. Please provide a valid project id."
            )

        var_match = False
        canonical_variable_name: Optional[str] = None
        for row in variables:
            if len(row) < 4:
                continue
            _, variable_name, project_id, _ = row
            if (
                project_id is not None
                and int(project_id) == draft.project_id
                and str(variable_name).strip().lower() == draft.variable_name.strip().lower()
            ):
                var_match = True
                canonical_variable_name = str(variable_name).strip()
                break
        if not var_match:
            sample_vars = [
                str(v[1]) for v in variables
                if len(v) >= 3 and v[2] is not None and int(v[2]) == draft.project_id
            ]
            sample = ", ".join(sample_vars[:10]) if sample_vars else "none"
            return (
                "variable_name",
                f"Variable '{draft.variable_name}' was not found under project {draft.project_id} "
                f"for this authenticated user. Available variables in that project: {sample}. "
                "Please provide a valid variable name."
            )

        # Use DB-canonical variable casing so Django exact-match lookups succeed.
        if canonical_variable_name:
            draft.variable_name = canonical_variable_name

        return None

    def _build_payload(self, draft: WidgetDraft) -> Dict[str, object]:
        """
        Convert a validated WidgetDraft into the exact Infiiot API payload shape.

        Common fields are always included; widget-specific defaults are injected
        based on the final widget label.
        """
        title = draft.title or f"{draft.widget_label.title()} Widget"
        common_payload: Dict[str, object] = {
            "widgetType": str(draft.widget_type_id),
            "widgetSubtype": str(draft.widget_sub_type or "0"),
            "project": draft.project_id,
            "variable": draft.variable_name,
            "title": title,
            "dashboard_id": draft.dashboard_id,
        }

        if draft.widget_label == "gauge":
            common_payload.update({"min": "0", "max": "100", "color": "#2D3394"})
        elif draft.widget_label == "switch":
            common_payload.update({"color": "#2D3394", "onLabel": "ON", "offLabel": "OFF"})
        elif draft.widget_label == "slider":
            common_payload.update({"color": "#2D3394", "min": "0", "max": "100"})
        elif draft.widget_label == "thermometer":
            common_payload.update({"color": "#2D3394", "unit": "", "min": "0", "max": "100"})
        elif draft.widget_label == "table":
            common_payload.update({"unit": "", "color": "#2D3394"})
            common_payload.pop("widgetSubtype", None)
        elif draft.widget_label == "onoffIndicator":
            common_payload.update(
                {
                    "offlabel": "OFF",
                    "off_color": "#FF0000",
                    "onlabel": "ON",
                    "on_color": "#00AA00",
                }
            )
        return common_payload

    def _create_dashboard(self, auth_token: str, dashboard_name: str) -> Tuple[bool, Optional[int], str]:
        """Create dashboard using Infiiot existing endpoint /dashboard/create-dashboard."""
        if not self.base_url:
            return False, None, "Set INFIIOT_BASE_URL in backend env. Example: http://127.0.0.1:8000"
        raw = create_dashboard_tool.invoke(
            {"base_url": self.base_url, "auth_token": auth_token, "dashboard_name": dashboard_name}
        )
        parsed = self._decode_response_obj(str(raw)) or {}
        if not isinstance(parsed, dict):
            return False, None, str(raw)
        ok = bool(parsed.get("ok"))
        dash_id = parsed.get("dashboard_id")
        message = str(parsed.get("message") or "")
        try:
            dash_id_int = int(dash_id) if dash_id is not None else None
        except (TypeError, ValueError):
            dash_id_int = None
        return ok, dash_id_int, message or ("Dashboard created." if ok else "Dashboard create failed.")

    def _create_project(self, auth_token: str, project_name: str) -> Tuple[bool, Optional[int], str]:
        """
        Create project/device using token-auth API:
        POST /apis/update-Device  body: {"device":"<name>","values":[]}
        """
        if not self.base_url:
            return False, None, "Set INFIIOT_BASE_URL in backend env. Example: http://127.0.0.1:8000"

        raw = create_project_tool.invoke(
            {"base_url": self.base_url, "auth_token": auth_token, "project_name": project_name}
        )
        parsed = self._decode_response_obj(str(raw)) or {}
        if not isinstance(parsed, dict):
            return False, None, str(raw)
        ok = bool(parsed.get("ok"))
        # Resolve numeric project id from read-only DB after creation.
        project_id = None
        user_id = db_readonly.resolve_user_id_from_token(auth_token)
        if user_id is not None:
            project_id = db_readonly.resolve_project_id_by_name(user_id, project_name)
        message = str(parsed.get("message") or "")
        return ok, project_id, message or ("Project create request succeeded." if ok else "Project create failed.")

    def _create_variable(
        self, auth_token: str, project_name: str, variable_name: str, unit: str
    ) -> Tuple[bool, str]:
        """
        Create/update a variable under an existing project using token-auth API.
        Uses /apis/update-Device with one value entry and empty data list.
        """
        if not self.base_url:
            return False, "Set INFIIOT_BASE_URL in backend env. Example: http://127.0.0.1:8000"

        raw = create_variable_tool.invoke(
            {
                "base_url": self.base_url,
                "auth_token": auth_token,
                "project_name": project_name,
                "variable_name": variable_name,
                "unit": unit,
            }
        )
        parsed = self._decode_response_obj(str(raw)) or {}
        if not isinstance(parsed, dict):
            return False, str(raw)
        ok = bool(parsed.get("ok"))
        message = str(parsed.get("message") or "")
        return ok, message or ("Variable create request succeeded." if ok else "Variable create failed.")

    def _resolve_project_name_by_id(self, auth_token: str, project_id: int) -> Optional[str]:
        """Resolve project name from project id using read-only DB and token->user mapping."""
        raw = resolve_project_name_by_id_tool.invoke({"auth_token": auth_token, "project_id": int(project_id)})
        parsed = self._decode_response_obj(str(raw)) or {}
        if isinstance(parsed, dict) and parsed.get("ok") and parsed.get("project_name"):
            return str(parsed.get("project_name")).strip()
        return None

    @staticmethod
    def _is_widget_create_intent(text: str) -> bool:
        """Detect phrases that likely mean 'create/add a widget'."""
        create_words = ("create", "build", "add")
        widget_words = ("widget", "chart", "gauge", "switch", "slider", "pie")
        return any(word in text for word in create_words) and any(word in text for word in widget_words)

    @staticmethod
    def _detect_widget_type(text: str) -> Optional[Tuple[int, str, str]]:
        """Map free-text widget keyword to (widget_type_id, widget_sub_type, widget_label)."""
        for keyword, value in sorted(WIDGET_KEYWORD_MAPPING.items(), key=lambda item: -len(item[0])):
            if keyword in text:
                return value
        return None

    @staticmethod
    def _extract_number(text: str, label: str) -> Optional[int]:
        """Extract numeric values from snippets like 'dashboard 1' or 'project: 5'."""
        match = re.search(rf"{label}\s*[:=]?\s*(\d+)", text, re.IGNORECASE)
        if match:
            return int(match.group(1))
        return None

    @staticmethod
    def _extract_title(text: str) -> Optional[str]:
        """Extract optional widget title from 'title: ...' text."""
        match = re.search(r"title\s*[:=]\s*([A-Za-z0-9 _-]+)", text, re.IGNORECASE)
        if match:
            return match.group(1).strip()
        return None

    @staticmethod
    def _extract_variable_name(text: str) -> Optional[str]:
        """Extract variable name from input like 'variable temperature'."""
        match = re.search(r"variable\s*[:=]?\s*([A-Za-z0-9_.-]+)", text, re.IGNORECASE)
        if match:
            return match.group(1).strip()
        return None

    @staticmethod
    def _extract_dashboard_name(text: str) -> Optional[str]:
        """
        Extract dashboard name from phrases like:
        - create dashboard DemoBoard
        - dashboard name: DemoBoard
        - dashboard DemoBoard
        """
        patterns = [
            r"create\s+dashboard\s+([A-Za-z0-9 _-]+)$",
            r"dashboard\s+name\s*[:=]?\s*([A-Za-z0-9 _-]+)$",
            r"dashboard\s+([A-Za-z][A-Za-z0-9 _-]+)$",
        ]
        clean = (text or "").strip()
        for p in patterns:
            m = re.search(p, clean, re.IGNORECASE)
            if m:
                name = m.group(1).strip()
                # Avoid parsing numeric dashboard id as name.
                if name.isdigit():
                    continue
                return name
        return None

    @staticmethod
    def _extract_project_name(text: str) -> Optional[str]:
        """
        Extract project name from phrases like:
        - create project PumpRoomA
        - project name: PumpRoomA
        - project PumpRoomA
        """
        patterns = [
            r"create\s+project\s+([A-Za-z0-9 _-]+)$",
            r"project\s+name\s*[:=]?\s*([A-Za-z0-9 _-]+)$",
            r"project\s+([A-Za-z][A-Za-z0-9 _-]+)$",
        ]
        clean = (text or "").strip()
        for p in patterns:
            m = re.search(p, clean, re.IGNORECASE)
            if m:
                name = m.group(1).strip()
                if name.isdigit():
                    continue
                return name
        return None

    @staticmethod
    def _is_dashboard_create_intent(text: str) -> bool:
        """Detect direct dashboard creation requests while avoiding widget-create overlap."""
        t = (text or "").lower()
        return (
            ("create" in t or "add" in t or "new" in t)
            and "dashboard" in t
            and "widget" not in t
        )

    @staticmethod
    def _is_project_create_intent(text: str) -> bool:
        """Detect direct project/device creation requests."""
        t = (text or "").lower()
        return ("create" in t or "add" in t or "new" in t) and ("project" in t or "device" in t)

    @staticmethod
    def _is_variable_create_intent(text: str) -> bool:
        """Detect direct variable creation requests."""
        t = (text or "").lower()
        return ("create" in t or "add" in t or "new" in t) and ("variable" in t)

    @staticmethod
    def _decode_response_obj(body: str):
        """Decode JsonResponse payloads that may be dict or JSON-stringified dict."""
        try:
            parsed = json.loads(body)
        except Exception:
            return None
        if isinstance(parsed, str):
            try:
                return json.loads(parsed)
            except Exception:
                return parsed
        return parsed

    @staticmethod
    def _extract_unit(text: str) -> Optional[str]:
        """Extract optional unit from text like 'unit C' or 'unit: psi'."""
        match = re.search(r"unit\s*[:=]?\s*([A-Za-z0-9%/_-]+)", text, re.IGNORECASE)
        if match:
            return match.group(1).strip()
        return None

    def _call_create_api(self, create_url: str, payload: Dict[str, object], auth_token: str) -> Tuple[bool, str]:
        """
        Execute widget create HTTP call with both Authorization and Token headers.

        Returns (success, message) with friendly error mapping for common failures.
        """
        endpoint = create_url
        if self.base_url and create_url.startswith(self.base_url):
            endpoint = create_url[len(self.base_url):] or "/"
        raw = create_widget_tool.invoke(
            {
                "base_url": self.base_url,
                "auth_token": auth_token,
                "endpoint": endpoint,
                "payload_json": json.dumps(payload),
            }
        )
        parsed = self._decode_response_obj(str(raw)) or {}
        if not isinstance(parsed, dict):
            return False, str(raw)
        ok = bool(parsed.get("ok"))
        message = str(parsed.get("message") or "")
        status_code = parsed.get("status_code")
        if ok:
            return True, message or "Widget created successfully."
        try:
            sc = int(status_code)
            return False, self._friendly_http_error(sc, message, payload, create_url)
        except (TypeError, ValueError):
            return False, message or "Widget create request failed."

    @staticmethod
    def _friendly_http_error(
        status_code: int, body: str, payload: Dict[str, object], create_url: str
    ) -> str:
        """Transform raw HTTP errors into concise, user-facing guidance."""
        compact_body = (body or "").replace("\n", " ").strip()
        compact_lower = compact_body.lower()

        if "doesnotexist" in compact_lower:
            dashboard_id = payload.get("dashboard_id")
            project_id = payload.get("project")
            variable_name = payload.get("variable")
            if "/dashboard/gauge" in create_url:
                return (
                    "Infiiot could not find required data for gauge creation "
                    f"(dashboard_id={dashboard_id}, project={project_id}, variable={variable_name}). "
                    "Please verify these values belong to the same authenticated user."
                )
            return (
                "Infiiot could not find required objects for widget creation "
                f"(dashboard_id={dashboard_id}, project={project_id}, variable={variable_name}). "
                "Please verify dashboard, project, and variable values."
            )

        if status_code in (401, 403):
            return (
                "Authentication failed while calling Infiiot API. "
                "Please verify token and user permissions. "
                "If dashboard endpoints rely on Django session auth, ensure a valid session/cookie flow exists."
            )

        if status_code == 404:
            return (
                "Infiiot endpoint not found. Please verify INFIIOT_BASE_URL and endpoint path."
            )

        if status_code >= 500:
            short = compact_body[:200] + ("..." if len(compact_body) > 200 else "")
            return f"Infiiot server error (HTTP {status_code}). Details: {short}"

        short = compact_body[:200] + ("..." if len(compact_body) > 200 else "")
        return f"HTTP {status_code}: {short}"


# Singleton used by FastAPI routes.
infiiot_agent = InfiiotAgent()
