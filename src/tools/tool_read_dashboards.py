import json
from langchain.tools import tool
from src.infiiot.db_readonly import fetch_dashboard_summary_for_user, resolve_user_id_from_token

@tool
def fetch_dashboard_summary_tool(auth_token: str) -> str:
    """
    Fetch a summary of dashboards (id and name) for the authenticated user.
    """
    user_id = resolve_user_id_from_token(auth_token)
    if not user_id:
        return json.dumps({"ok": False, "message": "Invalid token"})
        
    dashboards = fetch_dashboard_summary_for_user(user_id)
    return json.dumps({"ok": True, "dashboards": dashboards})
