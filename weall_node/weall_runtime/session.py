# weall_node/weall_runtime/session.py
from fastapi import Depends, HTTPException, status
from weall_node.weall_runtime.state import get_state


class Session:
    def __init__(self, user_id: str, tier: int):
        self.user_id = user_id
        self.tier = tier


def get_current_session():
    state = get_state()
    if not state.current_user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
        )
    return Session(
        user_id=state.current_user["id"],
        tier=state.current_user["tier"],
    )
