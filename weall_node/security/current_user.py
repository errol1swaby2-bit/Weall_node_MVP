from __future__ import annotations

from typing import Optional

from fastapi import Cookie, Depends, HTTPException, status

from . import auth_db


def current_user_id_from_cookie_optional(
    session_id: Optional[str] = Cookie(default=None, alias="weall_session"),
) -> Optional[str]:
    if not session_id:
        return None
    sess = auth_db.get_session(session_id, touch=True)
    if not sess:
        return None
    return str(sess["user_id"])


def require_current_user_id(
    user_id: Optional[str] = Depends(current_user_id_from_cookie_optional),
) -> str:
    if not user_id:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated.")
    return user_id
