import json
from langchain.tools import tool
from src.infiiot.db_writer import create_dashboard_direct

@tool
def tool_create_dashboard(auth_token: str, dashboard_name: str, user_id: int) -> str:
    """
    Create a new dashboard in InfiIoT directly in DB.
    Returns JSON string: {"ok": bool, "dashboard_id": int|null, "message": str}
    """
    result = create_dashboard_direct(user_id=user_id, dashboard_name=dashboard_name)
    return json.dumps(result)
