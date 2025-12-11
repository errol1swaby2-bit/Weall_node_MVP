# tests/test_reputation_jurors.py

import pathlib
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from weall_node.weall_runtime import disputes, poh_flow, reputation_jurors


def _fresh_ledger():
    return {}


def _make_tier3_juror(ledger, user_id: str, base_score: int):
    rec = poh_flow.ensure_poh_record(ledger, user_id)
    rec["tier"] = poh_flow.TIER_3
    disputes.set_juror_opt_in(ledger, user_id, True)
    disputes.set_juror_score(ledger, user_id, base_score)


# ---------------------------------------------------------------------------
# Juror scores increase when they participate in a decided case
# ---------------------------------------------------------------------------

def test_juror_scores_increment_on_participation():
    ledger = _fresh_ledger()

    reporter = "@reporter"
    jurors = ["@juror1", "@juror2", "@juror3"]

    # Reporter Tier 2
    rec_rep = poh_flow.ensure_poh_record(ledger, reporter)
    rec_rep["tier"] = poh_flow.TIER_2

    base_score = reputation_jurors.MIN_JUROR_SCORE + 1

    for j in jurors:
        _make_tier3_juror(ledger, j, base_score)

    case = disputes.open_dispute(
        ledger,
        opened_by=reporter,
        case_type=disputes.CASE_TYPE_CONTENT,
        target_kind="content",
        target_id="post-123",
        reason="Test reputation increments",
        required_jurors=3,
        min_approvals=2,
    )
    case_id = case["id"]

    case = disputes.assign_jurors(ledger, case_id, jurors)
    assert case["status"] == disputes.STATUS_AWAITING_VOTES

    # All jurors vote -> case should finalize
    for j in jurors:
        case = disputes.apply_juror_vote(
            ledger,
            case_id,
            j,
            vote=disputes.VOTE_UPHOLD,
            reason="Looks bad",
        )

    assert case["status"] == disputes.STATUS_DECIDED

    # Each juror should have gained +1 score
    for j in jurors:
        profile = disputes.get_juror_profile(ledger, j)
        assert profile["score"] == base_score + 1
        assert profile["strikes"] == 0


# ---------------------------------------------------------------------------
# No-show jurors get a strike when a case is decided without their vote
# ---------------------------------------------------------------------------

def test_no_show_juror_gets_strike_when_case_decides():
    ledger = _fresh_ledger()

    reporter = "@reporter"
    juror_present = "@juror_present"
    juror_absent = "@juror_absent"

    # Reporter Tier 2
    rec_rep = poh_flow.ensure_poh_record(ledger, reporter)
    rec_rep["tier"] = poh_flow.TIER_2

    base_score = reputation_jurors.MIN_JUROR_SCORE + 1

    _make_tier3_juror(ledger, juror_present, base_score)
    _make_tier3_juror(ledger, juror_absent, base_score)

    # Note: required_jurors=1 but we assign 2 jurors.
    # This allows case finalization after a single vote while still
    # marking the second juror as a no-show.
    case = disputes.open_dispute(
        ledger,
        opened_by=reporter,
        case_type=disputes.CASE_TYPE_CONTENT,
        target_kind="content",
        target_id="post-456",
        reason="Test no-show strike",
        required_jurors=1,
        min_approvals=1,
    )
    case_id = case["id"]

    case = disputes.assign_jurors(ledger, case_id, [juror_present, juror_absent])
    assert case["status"] == disputes.STATUS_AWAITING_VOTES

    # Only the present juror votes
    case = disputes.apply_juror_vote(
        ledger,
        case_id,
        juror_present,
        vote=disputes.VOTE_UPHOLD,
        reason="Reviewed evidence",
    )

    assert case["status"] == disputes.STATUS_DECIDED

    prof_present = disputes.get_juror_profile(ledger, juror_present)
    prof_absent = disputes.get_juror_profile(ledger, juror_absent)

    # Present juror gets +1 score
    assert prof_present["score"] == base_score + 1
    assert prof_present["strikes"] == 0

    # Absent juror gets a strike, score unchanged
    assert prof_absent["score"] == base_score
    assert prof_absent["strikes"] == 1
