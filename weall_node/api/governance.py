from __future__ import annotations

import time
from typing import Any, Dict, List

from fastapi import HTTPException
from pydantic import BaseModel, Field

from weall_node.weall_executor import executor
from weall_node.api.strict import require_mutation_allowed
from weall_node.api.tx_helpers import make_envelope, next_nonce_for_user, apply_tx_local_atomic
from weall.v1 import tx_pb2
from weall.v1 import common_pb2


__all__ = [
    "Proposal",
    "ProposalCreate",
    "ProposalVoteRequest",
    "create_proposal",
    "vote_proposal",
    "close_proposal",
    "get_proposal",
    "list_proposals",
]


class Proposal(BaseModel):
    id: str
    title: str
    description: str = ""
    created_by: str = ""
    type: str = "signal"
    options: List[str] = Field(default_factory=lambda: ["yes", "no", "abstain"])
    duration_sec: int = 60
    status: str = "open"
    created_at: int = 0
    closes_at: int = 0
    tallies: Dict[str, int] = Field(default_factory=lambda: {"yes": 0, "no": 0, "abstain": 0})
    votes: Dict[str, str] = Field(default_factory=dict)


class ProposalCreate(BaseModel):
    title: str
    description: str = ""
    created_by: str = ""
    type: str = "signal"
    options: List[str] = Field(default_factory=lambda: ["yes", "no", "abstain"])
    duration_sec: int = 60


class ProposalVoteRequest(BaseModel):
    choice: str


def _gov_root() -> Dict[str, Any]:
    gov = executor.ledger.setdefault("governance", {})
    if not isinstance(gov, dict):
        executor.ledger["governance"] = {}
        gov = executor.ledger["governance"]
    gov.setdefault("proposals", {})
    return gov


def _proposal_from_ledger(pid: str) -> Proposal:
    gov = _gov_root()
    proposals = gov.get("proposals", {})
    if not isinstance(proposals, dict):
        proposals = {}
    raw = proposals.get(pid, {})
    if not isinstance(raw, dict):
        raw = {}
    return Proposal(
        id=str(raw.get("id", pid)),
        title=str(raw.get("title", "")),
        description=str(raw.get("description", "")),
        created_by=str(raw.get("created_by", "")),
        type="signal",
        options=list(raw.get("options", ["yes", "no", "abstain"])),
        duration_sec=int(raw.get("duration_sec", 60) or 60),
        status=str(raw.get("status", "open")),
        created_at=int(raw.get("created_at", int(time.time()))),
        closes_at=int(raw.get("closes_at", int(time.time()) + 60)),
        tallies=dict(raw.get("tallies", {"yes": 0, "no": 0, "abstain": 0})),
        votes=dict(raw.get("votes", {})),
    )


def create_proposal(payload: ProposalCreate | Dict[str, Any], proposer_id: str) -> Dict[str, Any]:
    require_mutation_allowed(proposer_id)

    if isinstance(payload, dict):
        payload = ProposalCreate(**payload)

    nonce = next_nonce_for_user(executor, proposer_id)

    def _fill(env: tx_pb2.TxEnvelope) -> None:
        env.proposal_create.scope_id = b""
        env.proposal_create.title = payload.title
        env.proposal_create.body = payload.description
        env.proposal_create.body_ref.CopyFrom(common_pb2.Ref(kind="none", value=""))

    env = make_envelope(
        user_id=proposer_id,
        tx_type=tx_pb2.TX_PROPOSAL_CREATE,
        nonce=nonce,
        fill_payload=_fill,
    )

    ok, receipt = apply_tx_local_atomic(executor, env)
    if not ok:
        raise HTTPException(status_code=400, detail=receipt.get("error", "tx_failed"))

    pid = bytes(env.tx_id).hex()

    gov = _gov_root()
    raw = gov.get("proposals", {}).get(pid)
    if isinstance(raw, dict):
        raw["created_by"] = str(payload.created_by or proposer_id)
        raw["duration_sec"] = int(payload.duration_sec)
        raw["created_at"] = int(time.time())
        raw["closes_at"] = int(time.time()) + int(payload.duration_sec)

        opts = list(payload.options or ["yes", "no", "abstain"])
        if not opts:
            opts = ["yes", "no", "abstain"]
        raw["options"] = opts
        raw["tallies"] = {str(o): 0 for o in opts}
        raw["votes"] = {}
        raw["description"] = payload.description
        raw.setdefault("status", "open")

    return {"ok": True, "proposal": _proposal_from_ledger(pid)}


def vote_proposal(proposal_id: str, payload: ProposalVoteRequest | Dict[str, Any], voter_id: str) -> Dict[str, Any]:
    require_mutation_allowed(voter_id)

    if isinstance(payload, dict):
        payload = ProposalVoteRequest(**payload)

    choice = payload.choice.lower().strip()
    if choice not in ("yes", "no", "abstain"):
        raise HTTPException(status_code=400, detail="invalid_choice")

    support = True if choice == "yes" else False
    nonce = next_nonce_for_user(executor, voter_id)

    def _fill(env: tx_pb2.TxEnvelope) -> None:
        env.proposal_vote.proposal_id = bytes.fromhex(proposal_id)
        env.proposal_vote.support = bool(support)

    env = make_envelope(user_id=voter_id, tx_type=tx_pb2.TX_PROPOSAL_VOTE, nonce=nonce, fill_payload=_fill)
    ok, receipt = apply_tx_local_atomic(executor, env)
    if not ok:
        raise HTTPException(status_code=400, detail=receipt.get("error", "tx_failed"))

    gov = _gov_root()
    raw = gov.get("proposals", {}).get(proposal_id)
    if isinstance(raw, dict):
        if str(raw.get("status", "open")) != "open":
            raise HTTPException(status_code=400, detail="proposal_closed")

        opts = raw.get("options", ["yes", "no", "abstain"])
        if not isinstance(opts, list):
            opts = ["yes", "no", "abstain"]
        if choice not in [str(o) for o in opts]:
            raise HTTPException(status_code=400, detail="invalid_choice")

        votes = raw.setdefault("votes", {})
        if not isinstance(votes, dict):
            raw["votes"] = {}
            votes = raw["votes"]

        sender_hex = bytes(env.sender).hex()
        if sender_hex in votes:
            del votes[sender_hex]

        votes[str(voter_id)] = choice

        tallies: Dict[str, int] = {str(o): 0 for o in opts}
        for v in votes.values():
            if v in tallies:
                tallies[v] += 1
        raw["tallies"] = tallies

    return {"ok": True, "proposal": _proposal_from_ledger(proposal_id)}


def close_proposal(proposal_id: str, _closer_id: str) -> Dict[str, Any]:
    require_mutation_allowed(_closer_id)

    nonce = next_nonce_for_user(executor, _closer_id)

    def _fill(env: tx_pb2.TxEnvelope) -> None:
        env.proposal_finalize.proposal_id = bytes.fromhex(proposal_id)

    env = make_envelope(user_id=_closer_id, tx_type=tx_pb2.TX_PROPOSAL_FINALIZE, nonce=nonce, fill_payload=_fill)
    ok, receipt = apply_tx_local_atomic(executor, env)
    if not ok:
        raise HTTPException(status_code=400, detail=receipt.get("error", "tx_failed"))

    return {"ok": True, "proposal": _proposal_from_ledger(proposal_id)}


def get_proposal(proposal_id: str) -> Dict[str, Any]:
    return {"ok": True, "proposal": _proposal_from_ledger(proposal_id)}


def list_proposals() -> Dict[str, Any]:
    gov = _gov_root()
    out: List[Proposal] = []
    proposals = gov.get("proposals", {})
    if isinstance(proposals, dict):
        for pid in proposals.keys():
            try:
                out.append(_proposal_from_ledger(str(pid)))
            except Exception:
                continue
    return {"ok": True, "proposals": out}
