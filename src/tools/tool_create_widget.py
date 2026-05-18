import json
import logging
from langchain.tools import tool
from src.infiiot.db_writer import create_widget_direct

logger = logging.getLogger(__name__)

@tool
def tool_create_widget(
    auth_token: str,
    user_id: int,
    dashboard_db_id: int,
    variable_db_id: int,
    widget_type: str,
    widget_subtype: str,
    title: str,
    payload_json: str = "{}"
) -> str:
    """
    Create a widget by writing directly to dashboard_widgets table.
    Expects database primary keys for dashboard and variable.
    """
    try:
        payload = json.loads(payload_json) if payload_json else {}
    except Exception:
        payload = {}

    result = create_widget_direct(
        user_id=user_id,
        dashboard_db_id=dashboard_db_id,
        variable_db_id=variable_db_id,
        widget_type=widget_type,
        widget_subtype=widget_subtype,
        title=title,
        ymin=str(payload.get("ymin", "0")),
        ymax=str(payload.get("ymax", "100")),
        xlabel=str(payload.get("xlabel", "Time")),
        ylabel=str(payload.get("ylabel", "Value")),
        unit=str(payload.get("unit", "")),
        color=str(payload.get("color", "#4488ff"))
    )
    return json.dumps(result)
