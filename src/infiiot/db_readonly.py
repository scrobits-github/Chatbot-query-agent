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


def fetch_widget_chart_mappings(limit: int = 200) -> List[Tuple[Any, ...]]:
    """Read rows from public.ai_widget_chart_mapping (if table exists)."""
    table = os.getenv("INFIIOT_DB_MAPPING_TABLE", "public.ai_widget_chart_mapping").strip()
    rows: List[Tuple[Any, ...]] = []
    with _connection() as conn:
        if conn is None:
            return rows
        try:
            with conn.cursor() as cur:
                cur.execute(
                    f"SELECT widget_type_id, widget_sub_type, chart_kind FROM {table} ORDER BY id LIMIT %s",
                    (limit,),
                )
                rows = list(cur.fetchall())
        except Exception:
            return []
    return rows


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
