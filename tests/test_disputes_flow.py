# tests/test_disputes_flow.py

import pathlib
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from weall_node.weall_runtime import disputes, poh_flow


def _fresh_ledger():
    return {}


# ---------------------------------------------------------------------------
# Happy path: content dispute → jurors → upheld decision
# ---------------------------------------------------------------------------

def test_content_dispute_happy_path_upheld():
    ledger = _fresh_ledger()

    reporter = "@reporter"
    jurors = ["@juror1", "@juror2", "@juror3"]

    # Make jurors Tier 3, opt-in, and give them enough reputation score
    for j in jurors:
        rec = poh_flow.ensure_poh_record(ledger, j)
        rec["tier"] = poh_flow.TIER_3
        disputes.set_juror_opt_in(ledger, j, True)
        disputes.set_juror_score(ledger, j, disputes.MIN_JUROR_SCORE + 5)

    # Reporter could be Tier 2 (not strictly needed by runtime here)
    rec_rep = poh_flow.ensure_poh_record(ledger, reporter)
    rec_rep["tier"] = poh_flow.TIER_2

    case = disputes.open_dispute(
        ledger,
        opened_by=reporter,
        case_type=disputes.CASE_TYPE_CONTENT,
        target_kind="content",
        target_id="post-123",
        reason="Incites violence",
        tags=["harmful", "policy-violation"],
        evidence_cids=["bafy-post-123"],
        required_jurors=3,
        min_approvals=2,
    )

    assert case["status"] == disputes.STATUS_AWAITING_JURORS
    case_id = case["id"]

    # Assign jurors
    case = disputes.assign_jurors(ledger, case_id, jurors)
    assert case["status"] == disputes.STATUS_AWAITING_VOTES
    assert set(case["jurors"].keys()) == set(jurors)

    # All jurors vote to uphold the violation
    for j in jurors:
        case = disputes.apply_juror_vote(
            ledger,
            case_id,
            j,
            vote=disputes.VOTE_UPHOLD,
            reason="Clearly violates rules",
        )

    assert case["status"] == disputes.STATUS_DECIDED
    decision = case["decision"]
    assert decision is not None
    assert decision["verdict"] == "upheld"
    assert decision["approvals"] >= 2
    assert decision["rejects"] == 0


# ---------------------------------------------------------------------------
# Guardrail: non-Tier3 user cannot be juror, even if opted in + high score
# ---------------------------------------------------------------------------

def test_non_tier3_cannot_be_juror():
    ledger = _fresh_ledger()

    reporter = "@user"
    bad_juror = "@tier2_user"

    # Reporter Tier 2
    rec_rep = poh_flow.ensure_poh_record(ledger, reporter)
    rec_rep["tier"] = poh_flow.TIER_2

    # Candidate juror only Tier 2 → not allowed to serve,
    # even if they opt in and have high reputation score.
    rec_bad = poh_flow.ensure_poh_record(ledger, bad_juror)
    rec_bad["tier"] = poh_flow.TIER_2
    disputes.set_juror_opt_in(ledger, bad_juror, True)
    disputes.set_juror_score(ledger, bad_juror, disputes.MIN_JUROR_SCORE + 20)

    case = disputes.open_dispute(
        ledger,
        opened_by=reporter,
        case_type=disputes.CASE_TYPE_CONTENT,
        target_kind="content",
        target_id="post-999",
        reason="Spam or scam",
    )
    case_id = case["id"]

    with pytest.raises(ValueError) as excinfo:
        disputes.assign_jurors(ledger, case_id, [bad_juror])

    assert "not eligible to serve as juror" in str(excinfo.value)


# ---------------------------------------------------------------------------
# Guardrail: Tier3 + opt-in but low score cannot be juror
# ---------------------------------------------------------------------------

def test_tier3_opt_in_but_low_score_cannot_be_juror():
    ledger = _fresh_ledger()

    reporter = "@reporter"
    juror = "@juror_lowrep"

    rec_rep = poh_flow.ensure_poh_record(ledger, reporter)
    rec_rep["tier"] = poh_flow.TIER_2

    rec_j = poh_flow.ensure_poh_record(ledger, juror)
    rec_j["tier"] = poh_flow.TIER_3
    disputes.set_juror_opt_in(ledger, juror, True)
    disputes.set_juror_score(ledger, juror, disputes.MIN_JUROR_SCORE - 1)

    case = disputes.open_dispute(
        ledger,
        opened_by=reporter,
        case_type=disputes.CASE_TYPE_CONTENT,
        target_kind="content",
        target_id="post-lowrep",
        reason="Test case",
    )
    case_id = case["id"]

    with pytest.raises(ValueError) as excinfo:
        disputes.assign_jurors(ledger, case_id, [juror])

    assert "not eligible to serve as juror" in str(excinfo.value)


# ---------------------------------------------------------------------------
# Vote aggregation: changing vote updates counts without double-counting
# ---------------------------------------------------------------------------

def test_juror_vote_changes_adjust_counts_correctly():
    ledger = _fresh_ledger()

    reporter = "@reporter"
    juror = "@juror"

    rec_rep = poh_flow.ensure_poh_record(ledger, reporter)
    rec_rep["tier"] = poh_flow.TIER_2

    rec_j = poh_flow.ensure_poh_record(ledger, juror)
    rec_j["tier"] = poh_flow.TIER_3
    disputes.set_juror_opt_in(ledger, juror, True)
    disputes.set_juror_score(ledger, juror, disputes.MIN_JUROR_SCORE + 1)

    case = disputes.open_dispute(
        ledger,
        opened_by=reporter,
        case_type=disputes.CASE_TYPE_CONTENT,
        target_kind="content",
        target_id="post-abc",
        reason="Test case",
        required_jurors=10,
        min_approvals=7,  # high threshold so a single vote never finalizes
    )
    case_id = case["id"]

    case = disputes.assign_jurors(ledger, case_id, [juror])
    assert case["status"] == disputes.STATUS_AWAITING_VOTES

    # First vote: uphold
    case = disputes.apply_juror_vote(
        ledger,
        case_id,
        juror,
        vote=disputes.VOTE_UPHOLD,
        reason="Looks bad",
    )
    vc = case["aggregates"]["vote_counts"]
    assert vc[disputes.VOTE_UPHOLD] == 1
    assert vc[disputes.VOTE_REJECT] == 0
    assert case["status"] == disputes.STATUS_AWAITING_VOTES

    # Change mind: reject
    case = disputes.apply_juror_vote(
        ledger,
        case_id,
        juror,
        vote=disputes.VOTE_REJECT,
        reason="On second thought, fine",
    )
    vc = case["aggregates"]["vote_counts"]
    assert vc[disputes.VOTE_UPHOLD] == 0
    assert vc[disputes.VOTE_REJECT] == 1
    # Still not enough signal to finalize
    assert case["status"] == disputes.STATUS_AWAITING_VOTES
