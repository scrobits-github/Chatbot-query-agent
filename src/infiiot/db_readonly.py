"""
Read-only PostgreSQL access for the Infiiot agent.

Purpose: let the AI backend read mapping rows, dashboards, and variables using a
read-only DB user (no writes). Configure via env vars below. If unset, helpers
return empty results and the agent still works via HTTP + token only.
"""

from __future__ import annotations

import os
from contextlib import contextmanager
from typing import Any, Iterator, List, Optional, Tuple


def _read_config() -> Optional[Tuple[str, int, str, str, str]]:
    """Build (host, port, dbname, user, password) from env; None if incomplete."""
    host = os.getenv("INFIIOT_DB_READ_HOST", os.getenv("AI_DB_HOST", "")).strip()
    port_s = os.getenv("INFIIOT_DB_READ_PORT", os.getenv("AI_DB_PORT", "5432")).strip()
    name = os.getenv("INFIIOT_DB_READ_NAME", os.getenv("AI_DB_NAME", "")).strip()
    user = os.getenv("INFIIOT_DB_READ_USER", os.getenv("AI_DB_USER", "")).strip()
    password = os.getenv("INFIIOT_DB_READ_PASSWORD", os.getenv("AI_DB_PASSWORD", "")).strip()
    if not all([host, name, user]):
        return None
    try:
        port = int(port_s)
    except ValueError:
        port = 5432
    return (host, port, name, user, password)


@contextmanager
def _connection() -> Iterator[Any]:
    """Yield a psycopg2 connection; caller must not use it for writes."""
    cfg = _read_config()
    if not cfg:
        yield None
        return
    host, port, name, user, password = cfg
    import psycopg2

    conn = psycopg2.connect(
        host=host,
        port=port,
        dbname=name,
        user=user,
        password=password,
        connect_timeout=10,
    )
    conn.autocommit = True
    try:
        yield conn
    finally:
        conn.close()

def fetch_widget_chart_mappings(limit: int = 100) -> List[Tuple[int, str, str]]:
    """Fetch label-to-id mapping from ai_widget_chart_mapping table."""
    query = "SELECT widget_type_id, widget_sub_type, chart_kind FROM ai_widget_chart_mapping ORDER BY id LIMIT %s"
    try:
        with _connection() as conn:
            with conn.cursor() as cur:
                cur.execute(query, (limit,))
                return cur.fetchall()
    except Exception:
        return []


def resolve_user_id_from_token(token: str) -> Optional[int]:
    """
    Map Infiiot TokenStatic UUID to Django user id (read-only).
    Table default: accounts_tokenstatic (token, user_id_id).
    """
    if not token:
        return None
    with _connection() as conn:
        if conn is None:
            return None
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT user_id_id FROM accounts_tokenstatic WHERE token::text = %s LIMIT 1",
                    (token.strip(),),
                )
                row = cur.fetchone()
                return int(row[0]) if row else None
        except Exception:
            return None


def get_token_details(token: str) -> Optional[Tuple[int, Any]]:
    """
    Get both user_id and token_expiry for a given token from accounts_tokenstatic.
    Returns (user_id, token_expiry) or None.
    """
    if not token:
        return None
    with _connection() as conn:
        if conn is None:
            return None
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT user_id_id, token_expiry FROM accounts_tokenstatic WHERE token::text = %s LIMIT 1",
                    (token.strip(),),
                )
                row = cur.fetchone()
                return (int(row[0]), row[1]) if row else None
        except Exception:
            return None


def fetch_dashboard_summary_for_user(user_id: int, limit: int = 50) -> List[Tuple[Any, ...]]:
    """List dashboards for a user (Django default table dashboard_dashboardname)."""
    with _connection() as conn:
        if conn is None:
            return []
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT dashboard_id, dashboard_name, default_dashboard
                    FROM dashboard_dashboardname
                    WHERE user_id_id = %s
                    ORDER BY id
                    LIMIT %s
                    """,
                    (user_id, limit),
                )
                return list(cur.fetchall())
        except Exception:
            return []


def fetch_variables_for_user_projects(user_id: int, limit: int = 100) -> List[Tuple[Any, ...]]:
    """List variables under projects owned by user (devices_variabledir + devices_projectdir)."""
    with _connection() as conn:
        if conn is None:
            return []
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT v.id, v.variable_name, p.id AS project_id, p.project_name
                    FROM devices_variabledir v
                    JOIN devices_projectdir p ON v.project_id_id = p.id
                    WHERE p.user_id_id = %s
                    ORDER BY p.id, v.id
                    LIMIT %s
                    """,
                    (user_id, limit),
                )
                return list(cur.fetchall())
        except Exception:
            return []


def fetch_projects_for_user(user_id: int, limit: int = 200) -> List[Tuple[Any, ...]]:
    """List projects for a user from devices_projectdir."""
    with _connection() as conn:
        if conn is None:
            return []
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT id, project_name, project_id
                    FROM devices_projectdir
                    WHERE user_id_id = %s
                    ORDER BY id
                    LIMIT %s
                    """,
                    (user_id, limit),
                )
                return list(cur.fetchall())
        except Exception:
            return []


def resolve_project_id_by_name(user_id: int, project_name: str) -> Optional[int]:
    """Find project numeric id by name for a user."""
    if not project_name:
        return None
    with _connection() as conn:
        if conn is None:
            return None
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT id
                    FROM devices_projectdir
                    WHERE user_id_id = %s AND lower(project_name) = lower(%s)
                    ORDER BY id
                    LIMIT 1
                    """,
                    (user_id, project_name.strip()),
                )
                row = cur.fetchone()
                return int(row[0]) if row else None
        except Exception:
            return None

def resolve_variable_id_by_name(user_id: int, project_name: str, variable_name: str) -> Optional[int]:
    """Find variable numeric id by name and project name for a user."""
    if not project_name or not variable_name:
        return None
    with _connection() as conn:
        if conn is None:
            return None
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT v.id
                    FROM devices_variabledir v
                    JOIN devices_projectdir p ON v.project_id_id = p.id
                    WHERE p.user_id_id = %s AND lower(p.project_name) = lower(%s) AND lower(v.variable_name) = lower(%s)
                    ORDER BY v.id
                    LIMIT 1
                    """,
                    (user_id, project_name.strip(), variable_name.strip()),
                )
                row = cur.fetchone()
                return int(row[0]) if row else None
        except Exception:
            return None

def resolve_dashboard_id_by_name(user_id: int, dashboard_name: str) -> Optional[int]:
    """Find dashboard numeric id by name for a user."""
    if not dashboard_name:
        return None
    with _connection() as conn:
        if conn is None:
            return None
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT id
                    FROM dashboard_dashboardname
                    WHERE user_id_id = %s AND lower(dashboard_name) = lower(%s)
                    ORDER BY id
                    LIMIT 1
                    """,
                    (user_id, dashboard_name.strip()),
                )
                row = cur.fetchone()
                return int(row[0]) if row else None
        except Exception:
            return None

def resolve_variable_id_by_project_id(user_id: int, project_db_id: int, variable_name: str) -> Optional[int]:
    """Find variable numeric id by name and numeric project id for a user."""
    if not project_db_id or not variable_name:
        return None
    with _connection() as conn:
        if conn is None:
            return None
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT id
                    FROM devices_variabledir
                    WHERE project_id_id = %s AND lower(variable_name) = lower(%s)
                    ORDER BY id
                    LIMIT 1
                    """,
                    (project_db_id, variable_name.strip()),
                )
                row = cur.fetchone()
                return int(row[0]) if row else None
        except Exception:
            return None

def resolve_project_id_by_variable_name(user_id: int, variable_name: str) -> Optional[int]:
    """Find the project id for a given variable name if it belongs to the user."""
    if not variable_name:
        return None
    with _connection() as conn:
        if conn is None:
            return None
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT p.id
                    FROM devices_variabledir v
                    JOIN devices_projectdir p ON v.project_id_id = p.id
                    WHERE p.user_id_id = %s AND lower(v.variable_name) = lower(%s)
                    ORDER BY v.id
                    LIMIT 1
                    """,
                    (user_id, variable_name.strip()),
                )
                row = cur.fetchone()
                return int(row[0]) if row else None
        except Exception:
            return None
