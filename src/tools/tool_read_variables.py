import json
from langchain.tools import tool
from src.infiiot.db_readonly import fetch_variables_for_user_projects, resolve_user_id_from_token

@tool
def fetch_project_variables_tool(auth_token: str) -> str:
    """
    Fetch a list of all variables across all projects for the authenticated user.
    Useful to show the user what variables they have available.
    """
    user_id = resolve_user_id_from_token(auth_token)
    if not user_id:
        return json.dumps({"ok": False, "message": "Invalid token"})
        
    variables = fetch_variables_for_user_projects(user_id)
    return json.dumps({"ok": True, "variables": variables})

