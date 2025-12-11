# tests/test_poh_teir3_flow.py

import pathlib
import sys

import pytest

# Ensure repo root (containing inner weall_node package dir) is on sys.path
ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from weall_node.weall_runtime import poh_flow


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _fresh_ledger():
    """Return a fresh, empty ledger dict for isolated tests."""
    return {}


# ---------------------------------------------------------------------------
# Tier 2 -> Tier 3 happy path
# ---------------------------------------------------------------------------

def test_tier3_happy_path_live_call_and_votes_upgrade_to_tier3():
    """
    Scenario:

    - User is already Tier 2.
    - They request Tier 3.
    - Jurors are assigned.
    - Live call is scheduled, started, ended with a recording.
    - Enough jurors vote 'approve'.
    - Result: PoH record tier becomes 3 and request is approved.
    """
    ledger = _fresh_ledger()
    user_id = "@alice"

    # Start with a Tier 2 PoH record
    rec = poh_flow.ensure_poh_record(ledger, user_id)
    rec["tier"] = poh_flow.TIER_2

    # User submits a Tier 3 upgrade request
    req = poh_flow.submit_upgrade_request(ledger, user_id, target_tier=poh_flow.TIER_3)
    assert req["target_tier"] == poh_flow.TIER_3
    assert req["status"] == poh_flow.STATUS_AWAITING_JUROR_ASSIGNMENT

    req_id = req["id"]

    # Assign 3 jurors (even though default required_jurors is 7, min_approvals is 3)
    jurors = ["@juror1", "@juror2", "@juror3"]
    req = poh_flow.assign_jurors(ledger, req_id, jurors)
    assert set(req["jurors"].keys()) == set(jurors)

    # Schedule a live call
    req = poh_flow.schedule_tier3_call(
        ledger,
        req_id,
        scheduled_for=1_800_000_000,
        session_id="session-123",
        scheduled_by="@system",
    )
    assert req["status"] == poh_flow.STATUS_CALL_SCHEDULED
    assert req["call"]["session_id"] == "session-123"

    # Mark call started and ended, with a recording CID
    req = poh_flow.mark_tier3_call_started(ledger, req_id)
    assert req["status"] == poh_flow.STATUS_IN_CALL

    req = poh_flow.mark_tier3_call_ended(
        ledger,
        req_id,
        recording_cids=["bafy-record-1"],
    )
    assert req["status"] == poh_flow.STATUS_AWAITING_VOTES

    # All jurors vote "approve"
    for j in jurors:
        req = poh_flow.apply_juror_vote(
            ledger,
            req_id,
            j,
            vote=poh_flow.VOTE_APPROVE,
            reason="Looks human in live call",
        )

    # After enough approvals, request should be approved and tier should be 3
    assert req["status"] == poh_flow.STATUS_APPROVED
    updated_rec = poh_flow.get_poh_record(ledger, user_id)
    assert updated_rec is not None
    assert updated_rec["tier"] == poh_flow.TIER_3

    # Evidence hashes should include the call recording hash
    hashes = updated_rec.get("evidence_hashes", [])
    assert any(h.startswith("sha256:") for h in hashes)


# ---------------------------------------------------------------------------
# Tier 3 rejection path
# ---------------------------------------------------------------------------

def test_tier3_rejection_when_too_many_no_votes():
    """
    Scenario:

    - Tier 2 user requests Tier 3.
    - Enough jurors vote 'reject' that it's impossible to reach min_approvals.
    - Request moves to REJECTED and user stays Tier 2.
    """
    ledger = _fresh_ledger()
    user_id = "@bob"

    rec = poh_flow.ensure_poh_record(ledger, user_id)
    rec["tier"] = poh_flow.TIER_2

    req = poh_flow.submit_upgrade_request(ledger, user_id, target_tier=poh_flow.TIER_3)
    req_id = req["id"]

    # By default, required_jurors=7, min_approvals=3
    # If 'no' > (required - min_approvals) = 4, it should reject.
    jurors = [f"@juror{i}" for i in range(1, 8)]
    req = poh_flow.assign_jurors(ledger, req_id, jurors)

    # Schedule + end call, so votes are allowed.
    req = poh_flow.schedule_tier3_call(
        ledger,
        req_id,
        scheduled_for=1_800_000_000,
        session_id="session-xyz",
    )
    req = poh_flow.mark_tier3_call_started(ledger, req_id)
    req = poh_flow.mark_tier3_call_ended(ledger, req_id)

    # Cast 5 "reject" votes, which should trip the rejection condition.
    for j in jurors[:5]:
        req = poh_flow.apply_juror_vote(
            ledger,
            req_id,
            j,
            vote=poh_flow.VOTE_REJECT,
            reason="Does not match Tier 2 evidence",
        )

    assert req["status"] == poh_flow.STATUS_REJECTED
    updated_rec = poh_flow.get_poh_record(ledger, user_id)
    assert updated_rec["tier"] == poh_flow.TIER_2


# ---------------------------------------------------------------------------
# Guardrail: Tier 3 votes only after call ends
# ---------------------------------------------------------------------------

def test_tier3_votes_rejected_if_call_not_ended():
    """
    Tier 3 votes must only be accepted after the live call has ended.
    """
    ledger = _fresh_ledger()
    user_id = "@carol"

    rec = poh_flow.ensure_poh_record(ledger, user_id)
    rec["tier"] = poh_flow.TIER_2

    req = poh_flow.submit_upgrade_request(ledger, user_id, target_tier=poh_flow.TIER_3)
    req_id = req["id"]

    # Assign jurors and schedule the call, but do NOT end it
    jurors = ["@juror1"]
    req = poh_flow.assign_jurors(ledger, req_id, jurors)
    req = poh_flow.schedule_tier3_call(
        ledger,
        req_id,
        scheduled_for=1_800_000_000,
        session_id="session-guardrail",
    )
    req = poh_flow.mark_tier3_call_started(ledger, req_id)
    assert req["status"] == poh_flow.STATUS_IN_CALL

    # Attempt to vote before call is ended should raise ValueError
    with pytest.raises(ValueError) as excinfo:
        poh_flow.apply_juror_vote(
            ledger,
            req_id,
            "@juror1",
            vote=poh_flow.VOTE_APPROVE,
            reason="Tried to vote mid-call",
        )

    # Mid-call the request is not yet in STATUS_AWAITING_VOTES,
    # so we expect the generic guardrail message.
    assert "not currently accepting votes" in str(excinfo.value)


# ---------------------------------------------------------------------------
# Sanity: Tier 1 -> Tier 2 async video flow works
# ---------------------------------------------------------------------------

def test_tier2_async_video_flow_happy_path():
    """
    Sanity check:

    - User is Tier 1.
    - They request Tier 2.
    - Submit async video evidence.
    - Jurors vote approve.
    - Tier becomes 2 and request is approved.
    """
    ledger = _fresh_ledger()
    user_id = "@dana"

    # Start as Tier 1 email-verified
    rec = poh_flow.ensure_poh_record(ledger, user_id)
    rec["tier"] = poh_flow.TIER_1

    # Request Tier 2 upgrade
    req = poh_flow.submit_upgrade_request(ledger, user_id, target_tier=poh_flow.TIER_2)
    req_id = req["id"]
    assert req["status"] == poh_flow.STATUS_AWAITING_EVIDENCE

    # Submit async video evidence
    req = poh_flow.submit_tier2_async_video(
        ledger,
        req_id,
        user_id,
        video_cids=["bafy-async-1"],
        random_phrase="blue lantern avocado",
        device_fingerprint="device-xyz",
    )
    assert req["status"] == poh_flow.STATUS_AWAITING_VOTES

    # Assign jurors and vote approve
    jurors = ["@juror1", "@juror2"]
    req = poh_flow.assign_jurors(ledger, req_id, jurors)

    for j in jurors:
        req = poh_flow.apply_juror_vote(
            ledger,
            req_id,
            j,
            vote=poh_flow.VOTE_APPROVE,
            reason="Async video looks good",
        )

    # Result: Tier 2 and approved
    assert req["status"] == poh_flow.STATUS_APPROVED
    updated_rec = poh_flow.get_poh_record(ledger, user_id)
    assert updated_rec["tier"] == poh_flow.TIER_2

    # Evidence hashes should include async video hash
    hashes = updated_rec.get("evidence_hashes", [])
    assert any(h.startswith("sha256:") for h in hashes)
