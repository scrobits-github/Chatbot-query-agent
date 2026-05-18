import json
import os
import pandas as pd
from langchain.tools import tool
from settings import BASE_DIR

from src.infiiot.db_readonly import fetch_widget_chart_mappings

@tool
def fetch_chart_type_mapping_tool(auth_token: str) -> str:
    """
    Fetch the mapping of widget labels (e.g. 'line chart') to numeric widgetType and widgetSubType.
    Reads directly from the ai_widget_chart_mapping table in PostgreSQL.
    """
    mappings = fetch_widget_chart_mappings()
    if not mappings:
        return json.dumps({"ok": False, "message": "Chart mapping not found in Database"})
        
    # Convert list of tuples to a list of dicts for JSON response
    result = []
    for m in mappings:
        result.append({
            "widget_type_id": m[0],
            "widget_sub_type": m[1],
            "chart_kind": m[2]
        })
        
    return json.dumps({"ok": True, "mapping": result})
