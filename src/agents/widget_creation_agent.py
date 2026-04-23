import json
import os
import re
from dataclasses import dataclass
from typing import Dict, Optional, Tuple
from urllib import error, request


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

YES_WORDS = {"yes", "y", "ho", "haan", "ha", "confirm", "ok", "okay", "create"}
NO_WORDS = {"no", "n", "nahi", "cancel", "stop"}


class WidgetCreationAgent:
    def __init__(self) -> None:
        self._sessions: Dict[str, WidgetDraft] = {}
        self.base_url = os.getenv("INFIIOT_BASE_URL", "").rstrip("/")
        self.endpoint_map = {
            "gauge": "/dashboard/gauge",
            "switch": "/dashboard/switch",
            "slider": "/dashboard/slider",
            "thermometer": "/dashboard/thermometer",
            "table": "/dashboard/table",
            "onoffIndicator": "/dashboard/on_off_indicator",
        }

    def handle_message(
        self, user_message: str, session_id: str, auth_token: Optional[str]
    ) -> Dict[str, object]:
        text = (user_message or "").strip()
        lowered = text.lower()

        draft = self._sessions.get(session_id)
        if draft:
            return self._continue_flow(draft, lowered, auth_token, session_id)

        if not self._is_widget_create_intent(lowered):
            return {"handled": False}

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
        return self._continue_flow(draft, lowered, auth_token, session_id)

    def _continue_flow(
        self, draft: WidgetDraft, lowered: str, auth_token: Optional[str], session_id: str
    ) -> Dict[str, object]:
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
                    "Currently supported: gauge/switch/slider/thermometer/table/onoffIndicator."
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

    def _build_payload(self, draft: WidgetDraft) -> Dict[str, object]:
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

    @staticmethod
    def _is_widget_create_intent(text: str) -> bool:
        create_words = ("create", "banav", "banvun", "build", "add")
        widget_words = ("widget", "chart", "gauge", "switch", "slider", "pie")
        return any(word in text for word in create_words) and any(word in text for word in widget_words)

    @staticmethod
    def _detect_widget_type(text: str) -> Optional[Tuple[int, str, str]]:
        for keyword, value in sorted(WIDGET_KEYWORD_MAPPING.items(), key=lambda item: -len(item[0])):
            if keyword in text:
                return value
        return None

    @staticmethod
    def _extract_number(text: str, label: str) -> Optional[int]:
        match = re.search(rf"{label}\s*[:=]?\s*(\d+)", text, re.IGNORECASE)
        if match:
            return int(match.group(1))
        return None

    @staticmethod
    def _extract_title(text: str) -> Optional[str]:
        match = re.search(r"title\s*[:=]\s*([A-Za-z0-9 _-]+)", text, re.IGNORECASE)
        if match:
            return match.group(1).strip()
        return None

    @staticmethod
    def _extract_variable_name(text: str) -> Optional[str]:
        match = re.search(r"variable\s*[:=]?\s*([A-Za-z0-9_.-]+)", text, re.IGNORECASE)
        if match:
            return match.group(1).strip()
        return None

    def _call_create_api(self, create_url: str, payload: Dict[str, object], auth_token: str) -> Tuple[bool, str]:
        payload_bytes = json.dumps(payload).encode("utf-8")
        req = request.Request(
            create_url,
            data=payload_bytes,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {auth_token}",
                "Token": auth_token,
            },
            method="POST",
        )
        try:
            with request.urlopen(req, timeout=20) as resp:
                body = resp.read().decode("utf-8", errors="ignore")
                if 200 <= resp.status < 300:
                    return True, body or "Widget created successfully."
                return False, f"HTTP {resp.status}: {body}"
        except error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="ignore")
            return False, self._friendly_http_error(exc.code, body, payload, create_url)
        except Exception as exc:  # noqa: BLE001
            return False, str(exc)

    @staticmethod
    def _friendly_http_error(
        status_code: int, body: str, payload: Dict[str, object], create_url: str
    ) -> str:
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
                "Please verify token and user permissions."
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


widget_creation_agent = WidgetCreationAgent()
