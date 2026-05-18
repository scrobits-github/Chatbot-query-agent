"""
Auth tools to verify user login state and token validity.
"""

from __future__ import annotations

import json
from datetime import datetime
from langchain.tools import tool

from src.infiiot.db_readonly import get_token_details, _connection

@tool
def verify_user_is_active_tool(auth_token: str) -> str:
    """
    Verify if a user is logged in and their account is active using their auth token.
    Uses read-only DB access to resolve the token and check the 'is_active' status in auth_user.
    
    Returns JSON string: {"ok": bool, "is_active": bool, "user_id": int|null, "message": str}
    """
    # Step 1: Resolve token to a user ID and check expiry
    details = get_token_details(auth_token)
    
    if not details:
        return json.dumps({
            "ok": False, 
            "is_active": False, 
            "user_id": None,
            "message": "Invalid token or user not found."
        })
    
    user_id, expiry = details

    # Step 2: Check if token is expired
    if expiry and expiry < datetime.now(expiry.tzinfo):
        return json.dumps({
            "ok": False,
            "is_active": False,
            "user_id": user_id,
            "message": f"Token expired on {expiry.strftime('%Y-%m-%d %H:%M:%S')}. Please generate a new token."
        })
    
    is_active = False
    
    # Step 3: Check if the user is active in the Django auth_user table
    with _connection() as conn:
        if conn is not None:
            try:
                with conn.cursor() as cur:
                    cur.execute("SELECT is_active FROM auth_user WHERE id = %s", (user_id,))
                    row = cur.fetchone()
                    if row:
                        is_active = bool(row[0])
            except Exception as e:
                return json.dumps({
                    "ok": False, 
                    "is_active": False, 
                    "user_id": user_id,
                    "message": f"Database error: {str(e)}"
                })
        else:
            return json.dumps({
                "ok": False,
                "is_active": False,
                "user_id": user_id,
                "message": "Could not connect to read-only database."
            })
                
    return json.dumps({
        "ok": True, 
        "is_active": is_active, 
        "user_id": user_id,
        "message": "User is active." if is_active else "User is inactive."
    })
