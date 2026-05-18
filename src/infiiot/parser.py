import re
from typing import Optional

class InfiiotParser:
    """Helper class to extract entities (names, IDs) from natural language messages."""

    @staticmethod
    def extract_number(text: str, label: str) -> Optional[int]:
        """Extract numeric values from snippets like 'dashboard 1' or 'project: 5'."""
        match = re.search(rf"{label}\s*[:=]?\s*(\d+)", text, re.IGNORECASE)
        if match:
            return int(match.group(1))
        return None

    @staticmethod
    def extract_title(text: str) -> Optional[str]:
        """Extract optional widget title from 'title: ...' text."""
        match = re.search(r"title\s*[:=]\s*([A-Za-z0-9 _-]+)", text, re.IGNORECASE)
        if match:
            return match.group(1).strip()
        return None

    @staticmethod
    def extract_dashboard_name(text: str) -> Optional[str]:
        """Extract dashboard name from phrases like 'on the demo dashboard'."""
        patterns = [
            r"dashboard\s+name\s*[:=]?\s*([A-Za-z0-9_-]+)",
            r"(?:on|in|to)\s+(?:the\s+)?([A-Za-z0-9_-]+)\s+dashboard",
            r"dashboard\s+([A-Za-z0-9_-]+)",
            r"([A-Za-z0-9_-]+)\s+dashboard",
        ]
        clean = (text or "").strip()
        for p in patterns:
            m = re.search(p, clean, re.IGNORECASE)
            if m:
                name = m.group(1).strip()
                if not name.isdigit():
                    return name
        return None

    @staticmethod
    def extract_project_name(text: str) -> Optional[str]:
        """Extract project name from phrases like 'for my MyDevice project'."""
        patterns = [
            r"project\s+name\s*[:=]?\s*([A-Za-z0-9_-]+)",
            r"(?:for|in|on)\s+(?:the\s+)?([A-Za-z0-9_-]+)\s+project",
            r"project\s+([A-Za-z0-9_-]+)",
            r"([A-Za-z0-9_-]+)\s+project",
        ]
        clean = (text or "").strip()
        for p in patterns:
            m = re.search(p, clean, re.IGNORECASE)
            if m:
                name = m.group(1).strip()
                if not name.isdigit():
                    return name
        return None

    @staticmethod
    def extract_variable_name(text: str) -> Optional[str]:
        """Extract variable name from input while avoiding articles and prepositions."""
        # Pattern 1: "Temperature variable"
        match = re.search(r"([A-Za-z0-9_.-]+)\s+variable", text, re.IGNORECASE)
        if match:
            vname = match.group(1).strip()
            if vname.lower() not in ["a", "an", "the", "new", "my"]:
                return vname
            
        # Pattern 2: "variable: Temperature"
        match = re.search(r"variable\s*[:=]?\s*([A-Za-z0-9_.-]+)", text, re.IGNORECASE)
        if match:
            vname = match.group(1).strip()
            if vname.lower() not in ["on", "in", "to", "for", "at", "with", "named"]:
                return vname
                
        # Pattern 3: "variable named X"
        match = re.search(r"variable\s+named\s+([A-Za-z0-9_.-]+)", text, re.IGNORECASE)
        if match:
            return match.group(1).strip()
        return None

    @staticmethod
    def extract_unit(text: str) -> Optional[str]:
        """Extract unit from 'unit: ...'."""
        match = re.search(r"unit\s*[:=]\s*([A-Za-z0-9%]+)", text, re.IGNORECASE)
        if match:
            return match.group(1).strip()
        return None

    @staticmethod
    def is_widget_create_intent(text: str) -> bool:
        """Detect phrases that likely mean 'create/add a widget'."""
        create_words = ("create", "build", "add", "new")
        widget_words = ("widget", "wideget", "chart", "gauge", "switch", "slider", "pie", "scatterplot", "bar chart", "line chart")
        return any(word in text for word in create_words) and any(word in text for word in widget_words)

    @staticmethod
    def is_dashboard_create_intent(text: str) -> bool:
        t = (text or "").lower()
        return ("create" in t or "add" in t or "new" in t) and "dashboard" in t and "widget" not in t

    @staticmethod
    def is_project_create_intent(text: str) -> bool:
        t = (text or "").lower()
        return ("create" in t or "add" in t or "new" in t) and ("project" in t or "device" in t) and "variable" not in t

    @staticmethod
    def is_variable_create_intent(text: str) -> bool:
        """Detect variable creation while avoiding widget creation overlap."""
        t = (text or "").lower()
        has_create = any(word in t for word in ["create", "add", "new"])
        # If it mentions "dashboard" or "scatterplot", it's likely a WIDGET, not just a variable.
        is_likely_widget = "dashboard" in t or "scatterplot" in t or "chart" in t or "wideget" in t
        return has_create and ("variable" in t) and not is_likely_widget
