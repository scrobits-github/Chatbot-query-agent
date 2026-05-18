from dataclasses import dataclass
from typing import Optional

@dataclass
class WidgetDraft:
    """In-progress widget creation state for multi-turn conversations."""
    widget_label: str  # e.g. "gauge", "line chart"
    widget_type_id: str
    widget_sub_type: str
    dashboard_id: Optional[int] = None
    project_id: Optional[int] = None
    variable_name: Optional[str] = None
    title: Optional[str] = None
    user_id: Optional[int] = None
