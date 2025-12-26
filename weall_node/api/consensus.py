from __future__ import annotations

"""
Consensus control + status API.

Adds "ship mode" operational endpoints:

GET  /consensus/status
POST /consensus/tick
POST /consensus/loop/start
POST /consensus/loop/stop
GET  /consensus/loop/status

Notes:
- These endpoints are operational/mutating (tick/start/stop).
- When WEALL_STRICT_API=1, they are gated by require_mutation_allowed()
  which enforces strict prod and disables unsigned tx acceptance.
"""

from typing import Any, Dict

from fastapi import APIRouter

from weall_node.weall_executor import executor
from weall_node.api.strict import require_mutation_allowed

router = APIRouter(prefix="/consensus", tags=["consensus"])


@router.get("/status")
def consensus_status() -> Dict[str, Any]:
    """
    Canonical status payload from executor.
    """
    try:
        return executor.status()
    except Exception:
        # fallback in case executor.status shape changes
        return {
            "ok": True,
            "height": getattr(executor, "chain_height", lambda: 0)(),
            "driver": {
                "ok": True,
                "node_id": getattr(executor, "node_id", "unknown"),
            },
        }


@router.post("/tick")
def consensus_tick() -> Dict[str, Any]:
    """
    Force one consensus loop iteration (operational / mutating).
    """
    require_mutation_allowed("system")
    executor.tick()
    return {"ok": True, "status": executor.status()}


@router.post("/loop/start")
def consensus_loop_start() -> Dict[str, Any]:
    """
    Start background consensus loop (operational / mutating).
    """
    require_mutation_allowed("system")
    executor.start_loop()
    return {"ok": True, "status": executor.status()}


@router.post("/loop/stop")
def consensus_loop_stop() -> Dict[str, Any]:
    """
    Stop background consensus loop (operational / mutating).
    """
    require_mutation_allowed("system")
    executor.stop_loop()
    return {"ok": True, "status": executor.status()}


@router.get("/loop/status")
def consensus_loop_status() -> Dict[str, Any]:
    """
    Report whether the consensus loop is currently running.
    """
    st = executor.status()
    running = bool(st.get("driver", {}).get("running", False))
    return {"ok": True, "running": running, "status": st}
