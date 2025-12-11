"""
weall_node/api/health_ready.py
---------------------------------
Production-leaning ops health endpoints for WeAll node.

We keep this separate from the existing health.py to avoid conflicts.

- /ops/live  -> "is the process up?"
- /ops/ready -> "are key subsystems (IPFS, p2p, ledger) in a usable state?"
"""

import time
from typing import Any, Dict, Optional

from fastapi import APIRouter
from pydantic import BaseModel, Field

from ..weall_executor import executor

# NOTE: prefix is /ops so it won't collide with your existing /health routes
router = APIRouter(prefix="/ops", tags=["ops-health"])


# ---------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------


class SubsystemStatus(BaseModel):
    ok: bool = Field(..., description="True if subsystem looks usable.")
    detail: Optional[str] = Field(
        None,
        description="Short human-readable status.",
    )
    error: Optional[str] = Field(
        None,
        description="Error message if any (for logs / dashboards).",
    )


class HealthReadyResponse(BaseModel):
    ok: bool = True
    node_id: Optional[str] = Field(
        None,
        description="Node identifier, if available.",
    )
    env: Optional[str] = Field(
        None,
        description="WEALL_ENV / runtime environment, if set.",
    )
    timestamp: int = Field(..., description="Unix timestamp when this was generated.")
    ipfs: SubsystemStatus
    p2p: SubsystemStatus
    ledger: SubsystemStatus


# ---------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------


def _now() -> int:
    return int(time.time())


def _check_ipfs() -> SubsystemStatus:
    try:
        ipfs_client = getattr(executor, "ipfs", None)
        if ipfs_client is None:
            return SubsystemStatus(
                ok=False,
                detail="No IPFS client configured on executor.",
                error="missing_ipfs_client",
            )

        try:
            _ = ipfs_client.version()  # type: ignore[attr-defined]
            return SubsystemStatus(
                ok=True,
                detail="IPFS client responded to version()",
                error=None,
            )
        except Exception as e:  # noqa: BLE001
            return SubsystemStatus(
                ok=False,
                detail="IPFS client is configured but did not respond cleanly.",
                error=str(e),
            )
    except Exception as e:  # noqa: BLE001
        return SubsystemStatus(
            ok=False,
            detail="Unexpected error when checking IPFS health.",
            error=str(e),
        )


def _check_p2p() -> SubsystemStatus:
    try:
        node_id = getattr(executor, "node_id", None)
        overlay = getattr(executor, "p2p_overlay", None)

        if not node_id:
            return SubsystemStatus(
                ok=False,
                detail="No node_id on executor; p2p not initialized?",
                error="missing_node_id",
            )

        if overlay is not None:
            try:
                _ = getattr(overlay, "local_peer_id", None)
            except Exception as e:  # noqa: BLE001
                return SubsystemStatus(
                    ok=False,
                    detail="p2p overlay present but raised when inspected.",
                    error=str(e),
                )

        return SubsystemStatus(
            ok=True,
            detail="Node id present; p2p overlay looks sane.",
            error=None,
        )
    except Exception as e:  # noqa: BLE001
        return SubsystemStatus(
            ok=False,
            detail="Unexpected error when checking p2p.",
            error=str(e),
        )


def _check_ledger() -> SubsystemStatus:
    try:
        led = getattr(executor, "ledger", None)
        if led is None:
            return SubsystemStatus(
                ok=False,
                detail="Executor has no ledger attribute.",
                error="missing_ledger",
            )

        if isinstance(led, dict):
            if len(led) == 0:
                return SubsystemStatus(
                    ok=True,
                    detail="Ledger present but currently empty (MVP).",
                    error=None,
                )
            return SubsystemStatus(
                ok=True,
                detail="Ledger present with data.",
                error=None,
            )

        return SubsystemStatus(
            ok=True,
            detail=f"Ledger is {type(led).__name__}; non-dict, but present.",
            error=None,
        )
    except Exception as e:  # noqa: BLE001
        return SubsystemStatus(
            ok=False,
            detail="Unexpected error when checking ledger.",
            error=str(e),
        )


# ---------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------


@router.get("/live", response_model=Dict[str, Any])
def ops_live() -> Dict[str, Any]:
    """
    Liveness probe: if this returns 200, the process is up and FastAPI
    is serving requests.
    """
    return {
        "ok": True,
        "status": "live",
        "timestamp": _now(),
    }


@router.get("/ready", response_model=HealthReadyResponse)
def ops_ready() -> HealthReadyResponse:
    """
    Readiness probe: check node id, IPFS, ledger, and p2p overlay.
    """
    ipfs_status = _check_ipfs()
    p2p_status = _check_p2p()
    ledger_status = _check_ledger()

    node_id = getattr(executor, "node_id", None)
    env = getattr(executor, "env", None)
    if isinstance(env, dict):
        env_str = env.get("name") or env.get("WEALL_ENV") or None
    else:
        env_str = None

    overall_ok = ipfs_status.ok and ledger_status.ok

    return HealthReadyResponse(
        ok=overall_ok,
        node_id=node_id,
        env=env_str,
        timestamp=_now(),
        ipfs=ipfs_status,
        p2p=p2p_status,
        ledger=ledger_status,
    )
