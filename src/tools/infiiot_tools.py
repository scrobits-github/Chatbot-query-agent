"""
Tool-style wrappers for Infiiot operations.

These tools are intentionally stateless: callers pass all required inputs.
They can be used by agents/orchestrators without coupling to class instance state.
"""

from __future__ import annotations

import json
from typing import Dict, Optional, Tuple
from urllib import error, request

from langchain.tools import tool

from src.infiiot import db_readonly


def _post_json(url: str, payload: Dict[str, object], auth_token: str, timeout: int = 20) -> Tuple[int, str]:
    """Execute a JSON POST request with both Authorization and Token headers."""
    req = request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {auth_token}",
            "Token": auth_token,
        },
        method="POST",
    )
    try:
        with request.urlopen(req, timeout=timeout) as resp:
            body = resp.read().decode("utf-8", errors="ignore")
            return resp.status, body
    except error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="ignore")
        return exc.code, body


@tool
def create_dashboard_tool(base_url: str, auth_token: str, dashboard_name: str) -> str:
    """
    Create a dashboard in Infiiot.
    Returns JSON string: {"ok": bool, "dashboard_id": int|null, "message": str, "status_code": int}
    """
    url = f"{(base_url or '').rstrip('/')}/dashboard/create-dashboard"
    payload = {"type": "create", "dashboardName": dashboard_name}
    status_code, body = _post_json(url, payload, auth_token)
    dashboard_id: Optional[int] = None
    message = body or "Unknown response"

    try:
        parsed = json.loads(body) if body else {}
        if isinstance(parsed, str):
            parsed = json.loads(parsed)
        if isinstance(parsed, dict):
            if parsed.get("dashboard_id") is not None:
                try:
                    dashboard_id = int(parsed.get("dashboard_id"))
                except (TypeError, ValueError):
                    dashboard_id = None
            message = str(parsed.get("message") or parsed.get("dashboardCreated") or body or "")
    except Exception:
        pass

    ok = 200 <= status_code < 300 and ("success" in message.lower() or dashboard_id is not None)
    return json.dumps(
        {
            "ok": ok,
            "dashboard_id": dashboard_id,
            "message": message or f"HTTP {status_code}",
            "status_code": status_code,
        }
    )


@tool
def create_project_tool(base_url: str, auth_token: str, project_name: str) -> str:
    """
    Create a project/device in Infiiot using /apis/update-Device.
    Returns JSON string: {"ok": bool, "message": str, "status_code": int}
    """
    url = f"{(base_url or '').rstrip('/')}/apis/update-Device"
    payload = {"device": project_name, "values": []}
    status_code, body = _post_json(url, payload, auth_token)
    ok = 200 <= status_code < 300
    return json.dumps(
        {"ok": ok, "message": body or f"HTTP {status_code}", "status_code": status_code}
    )


@tool
def create_variable_tool(
    base_url: str,
    auth_token: str,
    project_name: str,
    variable_name: str,
    unit: str = "unit",
) -> str:
    """
    Create (or update) a variable under a project using /apis/update-Device.
    Returns JSON string: {"ok": bool, "message": str, "status_code": int}
    """
    url = f"{(base_url or '').rstrip('/')}/apis/update-Device"
    payload = {
        "device": project_name,
        "values": [{"variable": variable_name, "unit": unit, "data": []}],
    }
    status_code, body = _post_json(url, payload, auth_token)
    ok = 200 <= status_code < 300
    return json.dumps(
        {"ok": ok, "message": body or f"HTTP {status_code}", "status_code": status_code}
    )


@tool
def create_widget_tool(base_url: str, auth_token: str, endpoint: str, payload_json: str) -> str:
    """
    Create a widget by posting payload JSON to a dashboard endpoint.
    Returns JSON string: {"ok": bool, "message": str, "status_code": int}
    """
    url = f"{(base_url or '').rstrip('/')}{endpoint}"
    try:
        payload = json.loads(payload_json) if payload_json else {}
        if not isinstance(payload, dict):
            payload = {}
    except Exception:
        payload = {}
    status_code, body = _post_json(url, payload, auth_token)
    ok = 200 <= status_code < 300
    return json.dumps(
        {"ok": ok, "message": body or f"HTTP {status_code}", "status_code": status_code}
    )


@tool
def resolve_project_name_by_id_tool(auth_token: str, project_id: int) -> str:
    """
    Resolve project name by numeric project id using read-only DB + token->user lookup.
    Returns JSON string: {"ok": bool, "project_name": str|null}
    """
    user_id = db_readonly.resolve_user_id_from_token(auth_token)
    if user_id is None:
        return json.dumps({"ok": False, "project_name": None})
    projects = db_readonly.fetch_projects_for_user(user_id, limit=500)
    for row in projects:
        if len(row) >= 2 and row[0] is not None and int(row[0]) == int(project_id):
            return json.dumps({"ok": True, "project_name": str(row[1]).strip()})
    return json.dumps({"ok": False, "project_name": None})

