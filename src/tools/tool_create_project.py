import json
from langchain.tools import tool
from src.infiiot.db_writer import create_variable_direct

@tool
def tool_create_project(auth_token: str, project_name: str, user_id: int) -> str:
    """
    Create a project (device) in InfiIoT directly in DB.
    Returns JSON string: {"ok": bool, "message": str}
    """
    # Project creation in InfiIoT is handled by create_variable_direct when variable_name is None.
    result = create_variable_direct(user_id=user_id, project_name=project_name, variable_name=None)
    return json.dumps(result)
