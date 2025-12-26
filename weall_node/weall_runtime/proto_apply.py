from __future__ import annotations

from typing import Any, Dict, Tuple
import time

from weall.v1 import tx_pb2


class ProtoApplyError(RuntimeError):
    pass


def _now_ms() -> int:
    return int(time.time() * 1000)


def _bhex(b: bytes) -> str:
    return bytes(b or b"").hex()


def _ns(ledger: Dict[str, Any], key: str) -> Dict[str, Any]:
    obj = ledger.setdefault(key, {})
    if not isinstance(obj, dict):
        ledger[key] = {}
        obj = ledger[key]
    return obj


def _dict_ns(parent: Dict[str, Any], key: str) -> Dict[str, Any]:
    obj = parent.setdefault(key, {})
    if not isinstance(obj, dict):
        parent[key] = {}
        obj = parent[key]
    return obj


def _list_ns(parent: Dict[str, Any], key: str) -> list:
    obj = parent.setdefault(key, [])
    if not isinstance(obj, list):
        parent[key] = []
        obj = parent[key]
    return obj


def _require(cond: bool, msg: str) -> None:
    if not cond:
        raise ProtoApplyError(msg)


# ----------------------------- content -----------------------------

def _apply_content_post(ledger: Dict[str, Any], sender_hex: str, tx_id_hex: str, t: tx_pb2.ContentPostTx) -> None:
    content = _ns(ledger, "content")
    posts = _list_ns(content, "posts")

    posts.append(
        {
            "id": tx_id_hex,
            "author": sender_hex,
            "mime": t.mime,
            "title": t.title,
            "summary": t.summary,
            "content_ref": {
                "kind": getattr(t.content_ref, "kind", ""),
                "value": getattr(t.content_ref, "value", ""),
            },
            "created_at_ms": _now_ms(),
        }
    )


def _apply_like(ledger: Dict[str, Any], sender_hex: str, t: tx_pb2.LikeTx) -> None:
    content = _ns(ledger, "content")
    likes = _dict_ns(content, "likes")
    cid = _bhex(t.content_id)
    _require(bool(cid), "like.content_id missing")

    bucket = likes.setdefault(cid, {})
    if not isinstance(bucket, dict):
        likes[cid] = {}
        bucket = likes[cid]
    bucket[sender_hex] = True


def _apply_comment(ledger: Dict[str, Any], sender_hex: str, tx_id_hex: str, t: tx_pb2.CommentTx) -> None:
    content = _ns(ledger, "content")
    comments = _dict_ns(content, "comments")

    cid = _bhex(t.content_id)
    _require(bool(cid), "comment.content_id missing")
    _require(bool(t.text), "comment.text missing")

    lst = comments.setdefault(cid, [])
    if not isinstance(lst, list):
        comments[cid] = []
        lst = comments[cid]

    lst.append(
        {
            "id": tx_id_hex,
            "author": sender_hex,
            "text": t.text,
            "comment_ref": {
                "kind": getattr(t.comment_ref, "kind", ""),
                "value": getattr(t.comment_ref, "value", ""),
            },
            "created_at_ms": _now_ms(),
        }
    )


def _apply_report_content(ledger: Dict[str, Any], sender_hex: str, tx_id_hex: str, t: tx_pb2.ReportContentTx) -> None:
    reports = _ns(ledger, "reports")
    lst = _list_ns(reports, "content_reports")

    cid = _bhex(t.content_id)
    _require(bool(cid), "report.content_id missing")
    _require(bool(t.reason), "report.reason missing")

    lst.append({"id": tx_id_hex, "content_id": cid, "reporter": sender_hex, "reason": t.reason, "ts_ms": _now_ms()})


# ----------------------------- groups -----------------------------

def _apply_group_create(ledger: Dict[str, Any], sender_hex: str, tx_id_hex: str, t: tx_pb2.GroupCreateTx) -> None:
    groups = _ns(ledger, "groups")
    by_id = _dict_ns(groups, "by_id")
    members = _dict_ns(groups, "members")

    gid = tx_id_hex
    _require(bool(t.display_name), "group.display_name missing")

    by_id[gid] = {
        "id": gid,
        "display_name": t.display_name,
        "description": t.description,
        "created_by": sender_hex,
        "created_at_ms": _now_ms(),
    }

    members.setdefault(gid, {})
    if not isinstance(members.get(gid), dict):
        members[gid] = {}
    members[gid][sender_hex] = True


def _apply_group_join(ledger: Dict[str, Any], sender_hex: str, t: tx_pb2.GroupJoinTx) -> None:
    groups = _ns(ledger, "groups")
    members = _dict_ns(groups, "members")

    gid = _bhex(t.group_id)
    _require(bool(gid), "group_join.group_id missing")

    bucket = members.setdefault(gid, {})
    if not isinstance(bucket, dict):
        members[gid] = {}
        bucket = members[gid]
    bucket[sender_hex] = True


def _apply_group_leave(ledger: Dict[str, Any], sender_hex: str, t: tx_pb2.GroupLeaveTx) -> None:
    groups = _ns(ledger, "groups")
    members = _dict_ns(groups, "members")

    gid = _bhex(t.group_id)
    _require(bool(gid), "group_leave.group_id missing")

    bucket = members.get(gid, {})
    if isinstance(bucket, dict) and sender_hex in bucket:
        del bucket[sender_hex]


# ----------------------------- treasury -----------------------------

def _apply_treasury_transfer(ledger: Dict[str, Any], sender_hex: str, t: tx_pb2.TreasuryTransferTx) -> None:
    treasury = _ns(ledger, "treasury")
    treasury.setdefault("balance", 0)
    treasury.setdefault("history", [])
    balances = _ns(ledger, "balances")

    amount = int(t.amount or 0)
    _require(amount > 0, "treasury_transfer.amount must be > 0")

    to_hex = _bhex(t.to)
    _require(bool(to_hex), "treasury_transfer.to missing")

    # Reduce treasury balance if present (best-effort)
    treasury["balance"] = max(0, int(treasury.get("balance", 0) or 0) - amount)

    acct = balances.setdefault(to_hex, {})
    if not isinstance(acct, dict):
        balances[to_hex] = {}
        acct = balances[to_hex]

    balances.setdefault(to_hex, {})
    acct.setdefault("balances", {})
    if not isinstance(acct.get("balances"), dict):
        acct["balances"] = {}

    balances = acct["balances"]
    balances["WEC"] = int(balances.get("WEC", 0) or 0) + amount
    acct["last_update_ms"] = _now_ms()

    hist = treasury.setdefault("history", [])
    if not isinstance(hist, list):
        treasury["history"] = []
        hist = treasury["history"]

    hist.append({"to": to_hex, "amount": amount, "memo": t.memo, "source": sender_hex, "ts_ms": _now_ms()})


# ----------------------------- governance (used by your tests) -----------------------------

def _apply_proposal_create(ledger: Dict[str, Any], sender_hex: str, tx_id_hex: str, t: tx_pb2.ProposalCreateTx) -> None:
    gov = _ns(ledger, "governance")
    proposals = _dict_ns(gov, "proposals")

    pid = tx_id_hex
    _require(bool(t.title), "proposal.title missing")

    proposals[pid] = {
        "id": pid,
        "title": t.title,
        "description": t.body,
        "created_by": sender_hex,
        "created_at": int(time.time()),
        "closes_at": int(time.time()) + 60,
        "duration_sec": 60,
        "status": "open",
        "options": ["yes", "no", "abstain"],
        "tallies": {"yes": 0, "no": 0, "abstain": 0},
        "votes": {},
    }


def _apply_proposal_vote(ledger: Dict[str, Any], sender_hex: str, t: tx_pb2.ProposalVoteTx) -> None:
    gov = _ns(ledger, "governance")
    proposals = _dict_ns(gov, "proposals")

    pid = _bhex(t.proposal_id)
    _require(bool(pid), "proposal_vote.proposal_id missing")

    p = proposals.get(pid)
    _require(isinstance(p, dict), "proposal not found")
    _require(p.get("status") == "open", "proposal closed")

    votes = p.setdefault("votes", {})
    if not isinstance(votes, dict):
        p["votes"] = {}
        votes = p["votes"]

    tallies = p.setdefault("tallies", {"yes": 0, "no": 0, "abstain": 0})
    if not isinstance(tallies, dict):
        p["tallies"] = {"yes": 0, "no": 0, "abstain": 0}
        tallies = p["tallies"]

    new_choice = "yes" if bool(t.support) else "no"

    old = votes.get(sender_hex)
    if old in ("yes", "no", "abstain"):
        tallies[old] = max(0, int(tallies.get(old, 0) or 0) - 1)

    votes[sender_hex] = new_choice
    tallies[new_choice] = int(tallies.get(new_choice, 0) or 0) + 1


def _apply_proposal_finalize(ledger: Dict[str, Any], t: tx_pb2.ProposalFinalizeTx) -> None:
    gov = _ns(ledger, "governance")
    proposals = _dict_ns(gov, "proposals")

    pid = _bhex(t.proposal_id)
    _require(bool(pid), "proposal_finalize.proposal_id missing")

    p = proposals.get(pid)
    _require(isinstance(p, dict), "proposal not found")

    p["status"] = "closed"


# ----------------------------- PoH / roles / params -----------------------------

def _apply_poh_submit(ledger: Dict[str, Any], sender_hex: str, tx_id_hex: str, t: tx_pb2.PohSubmitTx) -> None:
    poh = _ns(ledger, "poh")
    recs = _dict_ns(poh, "records")

    r = recs.setdefault(sender_hex, {})
    if not isinstance(r, dict):
        recs[sender_hex] = {}
        r = recs[sender_hex]

    subs = r.setdefault("submissions", [])
    if not isinstance(subs, list):
        r["submissions"] = []
        subs = r["submissions"]

    subs.append(
        {
            "id": tx_id_hex,
            "proof_ref": {"kind": getattr(t.proof_ref, "kind", ""), "value": getattr(t.proof_ref, "value", "")},
            "note": t.note,
            "ts_ms": _now_ms(),
        }
    )


def _apply_poh_update_tier(ledger: Dict[str, Any], t: tx_pb2.PohUpdateTierTx) -> None:
    poh = _ns(ledger, "poh")
    recs = _dict_ns(poh, "records")

    subject_hex = _bhex(t.subject)
    _require(bool(subject_hex), "poh_update_tier.subject missing")

    r = recs.setdefault(subject_hex, {})
    if not isinstance(r, dict):
        recs[subject_hex] = {}
        r = recs[subject_hex]

    r["tier"] = int(t.new_tier)
    r["tier_reason"] = t.reason
    r["tier_updated_ms"] = _now_ms()


def _apply_role_grant(ledger: Dict[str, Any], t: tx_pb2.RoleGrantTx) -> None:
    roles = _ns(ledger, "roles")
    by_subject = _dict_ns(roles, "by_subject")

    subject_hex = _bhex(t.subject)
    _require(bool(subject_hex), "role_grant.subject missing")
    _require(bool(t.role), "role_grant.role missing")

    bucket = by_subject.setdefault(subject_hex, {})
    if not isinstance(bucket, dict):
        by_subject[subject_hex] = {}
        bucket = by_subject[subject_hex]
    bucket[t.role] = {"granted_ms": _now_ms(), "reason": t.reason}


def _apply_role_revoke(ledger: Dict[str, Any], t: tx_pb2.RoleRevokeTx) -> None:
    roles = _ns(ledger, "roles")
    by_subject = _dict_ns(roles, "by_subject")

    subject_hex = _bhex(t.subject)
    _require(bool(subject_hex), "role_revoke.subject missing")
    _require(bool(t.role), "role_revoke.role missing")

    bucket = by_subject.get(subject_hex, {})
    if isinstance(bucket, dict) and t.role in bucket:
        del bucket[t.role]


def _apply_param_update(ledger: Dict[str, Any], t: tx_pb2.ParamUpdateTx) -> None:
    params = _ns(ledger, "params")
    _require(bool(t.key), "param_update.key missing")
    params[str(t.key)] = str(t.value)


# ----------------------------- dispatcher -----------------------------

def _apply_envelope(ledger: Dict[str, Any], env: tx_pb2.TxEnvelope) -> None:
    sender_hex = _bhex(env.sender)
    tx_id_hex = _bhex(env.tx_id)
    tx_type = int(env.tx_type)

    if tx_type == tx_pb2.TX_CONTENT_POST:
        _apply_content_post(ledger, sender_hex, tx_id_hex, env.content_post)
        return
    if tx_type == tx_pb2.TX_LIKE:
        _apply_like(ledger, sender_hex, env.like)
        return
    if tx_type == tx_pb2.TX_COMMENT:
        _apply_comment(ledger, sender_hex, tx_id_hex, env.comment)
        return
    if tx_type == tx_pb2.TX_REPORT_CONTENT:
        _apply_report_content(ledger, sender_hex, tx_id_hex, env.report_content)
        return

    if tx_type == tx_pb2.TX_GROUP_CREATE:
        _apply_group_create(ledger, sender_hex, tx_id_hex, env.group_create)
        return
    if tx_type == tx_pb2.TX_GROUP_JOIN:
        _apply_group_join(ledger, sender_hex, env.group_join)
        return
    if tx_type == tx_pb2.TX_GROUP_LEAVE:
        _apply_group_leave(ledger, sender_hex, env.group_leave)
        return

    if tx_type == tx_pb2.TX_TREASURY_TRANSFER:
        _apply_treasury_transfer(ledger, sender_hex, env.treasury_transfer)
        return

    if tx_type == tx_pb2.TX_PROPOSAL_CREATE:
        _apply_proposal_create(ledger, sender_hex, tx_id_hex, env.proposal_create)
        return
    if tx_type == tx_pb2.TX_PROPOSAL_VOTE:
        _apply_proposal_vote(ledger, sender_hex, env.proposal_vote)
        return
    if tx_type == tx_pb2.TX_PROPOSAL_FINALIZE:
        _apply_proposal_finalize(ledger, env.proposal_finalize)
        return

    if tx_type == tx_pb2.TX_POH_SUBMIT:
        _apply_poh_submit(ledger, sender_hex, tx_id_hex, env.poh_submit)
        return
    if tx_type == tx_pb2.TX_POH_UPDATE_TIER:
        _apply_poh_update_tier(ledger, env.poh_update_tier)
        return
    if tx_type == tx_pb2.TX_ROLE_GRANT:
        _apply_role_grant(ledger, env.role_grant)
        return
    if tx_type == tx_pb2.TX_ROLE_REVOKE:
        _apply_role_revoke(ledger, env.role_revoke)
        return
    if tx_type == tx_pb2.TX_PARAM_UPDATE:
        _apply_param_update(ledger, env.param_update)
        return

    raise ProtoApplyError(f"Unsupported tx_type={tx_type}")


def apply_proto_tx_atomic(
    ledger: Dict[str, Any],
    env: tx_pb2.TxEnvelope,
    nonce_store: Any,
) -> Tuple[bool, Dict[str, Any]]:
    """
    Apply a proto tx with nonce enforcement and a structured receipt.

    Expected NonceStore API:
        nonce_store.require(sender_hex, nonce) -> bool
        nonce_store.commit(sender_hex, next_expected_nonce) -> None
    """
    sender_hex = _bhex(getattr(env, "sender", b"") or b"")
    tx_type = int(getattr(env, "tx_type", 0) or 0)
    nonce = int(getattr(env, "nonce", 0) or 0)
    tx_id_hex = _bhex(getattr(env, "tx_id", b"") or b"")

    try:
        if sender_hex:
            if not nonce_store.require(sender_hex, nonce):
                return False, {"ok": False, "error": "bad_nonce", "sender": sender_hex, "nonce": nonce, "tx_type": tx_type}
    except Exception as e:
        return False, {"ok": False, "error": f"nonce_store_error:{type(e).__name__}", "sender": sender_hex, "nonce": nonce, "tx_type": tx_type}

    try:
        _apply_envelope(ledger, env)
    except ProtoApplyError as e:
        return False, {"ok": False, "error": str(e), "sender": sender_hex, "nonce": nonce, "tx_type": tx_type, "tx_id": tx_id_hex}

    try:
        if sender_hex:
            nonce_store.commit(sender_hex, nonce + 1)
    except Exception:
        return True, {"ok": True, "tx_id": tx_id_hex, "sender": sender_hex, "nonce": nonce, "tx_type": tx_type, "warning": "nonce_commit_failed"}

    return True, {"ok": True, "tx_id": tx_id_hex, "sender": sender_hex, "nonce": nonce, "tx_type": tx_type}
