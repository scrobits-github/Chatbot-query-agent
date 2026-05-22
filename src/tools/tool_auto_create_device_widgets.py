import json
import logging
from typing import Optional
from langchain.tools import tool

from src.infiiot.db_readonly import (
    resolve_user_id_from_token,
    resolve_dashboard_id_by_name,
    resolve_project_id_by_name,
    fetch_variables_for_user_projects
)
from src.infiiot.db_writer import create_dashboard_direct, create_widget_direct

logger = logging.getLogger(__name__)

@tool
def tool_auto_create_device_widgets(
    auth_token: str,
    dashboard_name: str,
    recommendations_json: str,
    project_name: Optional[str] = None
) -> str:
    """
    Automated Intent-based Widget Creator (Unified Super-Tool).
    1. Resolves user from auth_token.
    2. Resolves dashboard database ID (creates dashboard if not exists).
    3. If project_name is provided: Resolves project database ID and retrieves all variables of that project (device).
    4. If project_name is omitted: Directly creates widgets from recommendations_json using variable_db_id.
    
    recommendations_json format:
    [
      {
        "variable_name": "Temperature",
        "variable_db_id": 123,  # Required if project_name is omitted
        "widget_type": "5",
        "widget_subtype": "3",
        "title": "Room Temp",
        "ymin": "0",
        "ymax": "100",
        "unit": "°C",
        "color": "#ff3300"
      }
    ]
    """
    try:
        user_id = resolve_user_id_from_token(auth_token)
        if not user_id:
            return json.dumps({"ok": False, "message": "Invalid token or unauthorized."})

        # 1. Resolve or Create Dashboard
        dashboard_id = resolve_dashboard_id_by_name(user_id, dashboard_name)
        created_dashboard = False
        if not dashboard_id:
            db_res = create_dashboard_direct(user_id, dashboard_name)
            if not db_res.get("ok"):
                return json.dumps({"ok": False, "message": f"Failed to create dashboard: {db_res.get('message')}"})
            dashboard_id = db_res.get("dashboard_id")
            created_dashboard = True

        # 2. Parse recommendations passed by the LLM
        custom_recs = []
        try:
            recs_list = json.loads(recommendations_json)
            for item in recs_list:
                custom_recs.append(item)
        except Exception as e:
            return json.dumps({"ok": False, "message": f"Failed to parse recommendations_json: {str(e)}"})

        # 3. Determine widgets to create
        widgets_to_create = []

        if project_name:
            # --- Case A: Bulk Project/Device Auto-Setup ---
            project_db_id = resolve_project_id_by_name(user_id, project_name)
            if not project_db_id:
                return json.dumps({"ok": False, "message": f"Project (Device) '{project_name}' not found for this user."})

            # Fetch all variables under this project
            all_variables = fetch_variables_for_user_projects(user_id)
            project_vars = []
            for var in all_variables:
                # var: (v.id, v.variable_name, p.id AS project_id, p.project_name)
                if len(var) >= 4 and var[2] == project_db_id:
                    project_vars.append({
                        "id": var[0],
                        "name": var[1]
                    })

            if not project_vars:
                return json.dumps({
                    "ok": False, 
                    "message": f"No variables found under device/project '{project_name}'."
                })

            # Map the project variables using recommendations
            recs_map = {rec.get("variable_name", "").lower().strip(): rec for rec in custom_recs if rec.get("variable_name")}
            for pvar in project_vars:
                vname = pvar["name"]
                vname_key = vname.lower().strip()
                
                if vname_key in recs_map:
                    rec = recs_map[vname_key]
                    widgets_to_create.append({
                        "variable_db_id": pvar["id"],
                        "variable_name": vname,
                        "widget_type": str(rec.get("widget_type", "1")),
                        "widget_subtype": str(rec.get("widget_subtype", "1")),
                        "title": rec.get("title", vname),
                        "ymin": str(rec.get("ymin", "0")),
                        "ymax": str(rec.get("ymax", "100")),
                        "unit": rec.get("unit", ""),
                        "color": rec.get("color", "#4488ff")
                    })
                else:
                    # Default fallback to standard line chart
                    widgets_to_create.append({
                        "variable_db_id": pvar["id"],
                        "variable_name": vname,
                        "widget_type": "1",
                        "widget_subtype": "1",
                        "title": f"{vname} Chart",
                        "ymin": "0",
                        "ymax": "100",
                        "unit": "",
                        "color": "#2196f3"
                    })
        else:
            # --- Case B: Custom/Single Ad-hoc Setup using direct variable_db_id ---
            for rec in custom_recs:
                v_db_id = rec.get("variable_db_id")
                if not v_db_id:
                    v_db_id = rec.get("variable_id")
                
                if not v_db_id:
                    return json.dumps({
                        "ok": False, 
                        "message": "variable_db_id is required in recommendations_json when project_name is omitted."
                    })
                
                widgets_to_create.append({
                    "variable_db_id": int(v_db_id),
                    "variable_name": rec.get("variable_name", "Variable"),
                    "widget_type": str(rec.get("widget_type", "1")),
                    "widget_subtype": str(rec.get("widget_subtype", "1")),
                    "title": rec.get("title", rec.get("variable_name", "Widget")),
                    "ymin": str(rec.get("ymin", "0")),
                    "ymax": str(rec.get("ymax", "100")),
                    "unit": rec.get("unit", ""),
                    "color": rec.get("color", "#4488ff")
                })

        # 4. Create all resolved widgets in a batch
        created_widgets = []
        failed_widgets = []
        for w in widgets_to_create:
            res = create_widget_direct(
                user_id=user_id,
                dashboard_db_id=dashboard_id,
                variable_db_id=w["variable_db_id"],
                widget_type=w["widget_type"],
                widget_subtype=w["widget_subtype"],
                title=w["title"],
                ymin=w["ymin"],
                ymax=w["ymax"],
                xlabel="Time",
                ylabel="Value",
                unit=w["unit"],
                color=w["color"]
            )
            if res.get("ok"):
                created_widgets.append({
                    "variable_name": w["variable_name"],
                    "widget_title": w["title"],
                    "widget_id": res.get("widget_id"),
                    "type": w["widget_type"],
                    "subtype": w["widget_subtype"]
                })
            else:
                failed_widgets.append({
                    "variable_name": w["variable_name"],
                    "error": res.get("message")
                })

        return json.dumps({
            "ok": True,
            "dashboard_name": dashboard_name,
            "dashboard_db_id": dashboard_id,
            "created_dashboard": created_dashboard,
            "device_name": project_name or "Custom Selection",
            "widgets_created": created_widgets,
            "widgets_failed": failed_widgets
        })

    except Exception as e:
        logger.error(f"Error in tool_auto_create_device_widgets: {e}", exc_info=True)
        return json.dumps({"ok": False, "message": f"Exception: {str(e)}"})
