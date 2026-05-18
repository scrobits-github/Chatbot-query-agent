import json
from langchain.tools import tool
from src.infiiot.db_writer import create_variable_direct

@tool
def tool_create_variable(
    auth_token: str,
    user_id: int,
    project_name: str,
    variable_name: str,
    unit: str = "unit",
) -> str:
    """
    Create a variable under a project directly in DB.
    """
    result = create_variable_direct(
        user_id=user_id,
        project_name=project_name,
        variable_name=variable_name,
        unit=unit
    )
    return json.dumps(result)
