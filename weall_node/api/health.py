# weall_node/api/health.py
from __future__ import annotations

"""
Health & debug API for WeAll.

This module provides a set of endpoints to quickly inspect the node's
runtime and ledger state.

Routes
------
- GET /health/ping
    Simple heartbeat endpoint.

- GET /health/modules
    Report which major runtimes are available (IPFS, wallet, reputation,
    PoH, etc.).

- GET /health/ledger/{namespace}
    Return the raw ledger slice for a given namespace (e.g. "poh",
    "recovery", "disputes", "governance", "reputation", "treasury",
    "validators", "auth").

- GET /health/summary
    High-level summary of counts per key namespace.
"""

import time
from typing import Any, Dict, Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from ..weall_executor import executor

router = APIRouter(tags=["health"])


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------


class PingResponse(BaseModel):
    ok: bool = True
    ts: float = Field(..., description="Server timestamp.")
    msg: str = "pong"


class ModuleStatus(BaseModel):
    name: str
    available: bool
    details: Optional[Dict[str, Any]] = None


class ModulesResponse(BaseModel):
    ok: bool = True
    modules: Dict[str, ModuleStatus]


class LedgerNamespaceResponse(BaseModel):
    namespace: str
    data: Any


class HealthSummaryResponse(BaseModel):
    ok: bool = True
    namespaces: Dict[str, Dict[str, Any]]


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _normalize_base_url(api_url: str) -> str:
    """
    Normalize base URL (strip trailing slash).

    This helper exists to mirror earlier behavior where the API needed
    to safely handle URLs with or without a trailing slash.
    """
    # Normalize base URL (strip trailing slash)
    return api_url.rstrip("/")


def _get_runtime(name: str) -> Optional[Any]:
    return getattr(executor, name, None)


def _count_dict(obj: Any) -> Optional[int]:
    if isinstance(obj, dict):
        return len(obj)
    return None


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get("/ping", response_model=PingResponse)
def ping() -> PingResponse:
    """
    Simple heartbeat endpoint. Useful for external uptime checks.
    """
    return PingResponse(ts=time.time())


@router.get("/modules", response_model=ModulesResponse)
def modules() -> ModulesResponse:
    """
    Report which major runtimes are available on this node.

    This is a purely informational endpoint and does not mutate any
    state or perform network calls.
    """
    module_names = [
        "ipfs",
        "wallet",
        "reputation",
        "poh",
        "governance",
        "disputes",
        "recovery",
        "validators",
        "treasury",
    ]

    out: Dict[str, ModuleStatus] = {}
    for name in module_names:
        obj = _get_runtime(name)
        out[name] = ModuleStatus(
            name=name,
            available=obj is not None,
            details={"type": type(obj).__name__} if obj is not None else None,
        )

    return ModulesResponse(modules=out)


@router.get("/ledger/{namespace}", response_model=LedgerNamespaceResponse)
def ledger_namespace(namespace: str) -> LedgerNamespaceResponse:
    """
    Return the raw ledger slice for a given namespace.

    Examples
    --------
    - /health/ledger/poh
    - /health/ledger/recovery
    - /health/ledger/disputes
    - /health/ledger/governance
    - /health/ledger/reputation
    - /health/ledger/treasury
    - /health/ledger/validators
    - /health/ledger/auth
    """
    ledger = executor.ledger
    if namespace not in ledger:
        raise HTTPException(status_code=404, detail=f"Namespace {namespace!r} not found in ledger.")
    return LedgerNamespaceResponse(namespace=namespace, data=ledger[namespace])


@router.get("/summary", response_model=HealthSummaryResponse)
def summary(
    include_raw_counts: bool = Query(
        default=True,
        description="If true, returns basic counts (e.g. number of proposals, PoH records, etc.).",
    )
) -> HealthSummaryResponse:
    """
    High-level overview of key ledger namespaces and counts.

    This is designed for quick sanity checks while developing or
    operating a node.
    """
    ledger = executor.ledger

    def ns(name: str) -> Dict[str, Any]:
        ns_data = ledger.get(name) or {}
        info: Dict[str, Any] = {}
        if not include_raw_counts:
            return info

        # Basic heuristics per namespace
        if name == "poh":
            recs = ns_data.get("records") or {}
            info["record_count"] = _count_dict(recs) or 0
        elif name == "governance":
            props = ns_data.get("proposals") or {}
            info["proposal_count"] = _count_dict(props) or 0
        elif name == "recovery":
            cases = ns_data.get("cases") or {}
            events = ns_data.get("events") or []
            info["case_count"] = _count_dict(cases) or 0
            info["event_count"] = len(events) if isinstance(events, list) else 0
        elif name == "disputes":
            cases = ns_data.get("cases") or {}
            info["case_count"] = _count_dict(cases) or 0
        elif name == "reputation":
            scores = ns_data.get("scores") or ns_data.get("users") or {}
            info["tracked_id_count"] = _count_dict(scores) or 0
        elif name == "treasury":
            info["configured"] = bool(ns_data)
        elif name == "validators":
            vals = ns_data.get("validators") or {}
            info["validator_count"] = _count_dict(vals) or 0
        elif name == "auth":
            users = ns_data.get("users") or {}
            sessions = ns_data.get("sessions") or {}
            info["user_count"] = _count_dict(users) or 0
            info["session_count"] = _count_dict(sessions) or 0

        return info

    namespaces = {
        "poh": ns("poh"),
        "governance": ns("governance"),
        "recovery": ns("recovery"),
        "disputes": ns("disputes"),
        "reputation": ns("reputation"),
        "treasury": ns("treasury"),
        "validators": ns("validators"),
        "auth": ns("auth"),
    }

    return HealthSummaryResponse(namespaces=namespaces)
