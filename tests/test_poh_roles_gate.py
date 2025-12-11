# tests/test_poh_roles_gate.py

import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from weall_node.weall_runtime.roles import (
    PoHTier,
    Capability,
    HumanRoleFlags,
    compute_effective_role_profile,
    capability_matrix_by_tier,
    capability_matrix_full_example,
)


def _cap_values(profile) -> set[str]:
    """Helper to turn capabilities into plain string values."""
    return {c.value for c in profile.capabilities}


# ---------------------------------------------------------------------------
# Base tier capabilities
# ---------------------------------------------------------------------------

def test_tier1_is_view_only():
    """Tier 1: can view, but cannot post or earn creator rewards."""
    profile = compute_effective_role_profile(PoHTier.TIER1)
    caps = profile.capabilities

    # Can view public + group content
    assert Capability.VIEW_PUBLIC_CONTENT in caps
    assert Capability.VIEW_GROUP_CONTENT in caps

    # No active posting / group / governance actions
    forbidden = [
        Capability.CREATE_POST,
        Capability.COMMENT,
        Capability.LIKE,
        Capability.JOIN_GROUPS,
        Capability.OPEN_DISPUTE,
        Capability.VOTE_GOVERNANCE,
        Capability.EARN_CREATOR_REWARDS,
        Capability.CREATE_GROUP,
        Capability.CREATE_GOVERNANCE_PROPOSAL,
    ]
    for cap in forbidden:
        assert cap not in caps


def test_tier2_can_post_join_and_earn_creator_rewards():
    """
    Tier 2:
      - can post, comment, like
      - can join/leave groups
      - can open disputes and vote in governance
      - earns creator rewards by default
      - cannot yet create groups or governance proposals
    """
    profile = compute_effective_role_profile(PoHTier.TIER2)
    caps = profile.capabilities

    must_have = [
        Capability.VIEW_PUBLIC_CONTENT,
        Capability.VIEW_GROUP_CONTENT,
        Capability.CREATE_POST,
        Capability.COMMENT,
        Capability.LIKE,
        Capability.FLAG_VIOLATION,
        Capability.JOIN_GROUPS,
        Capability.LEAVE_GROUPS,
        Capability.OPEN_DISPUTE,
        Capability.SUBMIT_EVIDENCE,
        Capability.VOTE_GOVERNANCE,
        Capability.EARN_CREATOR_REWARDS,
    ]
    for cap in must_have:
        assert cap in caps

    must_not_have = [
        Capability.CREATE_GROUP,
        Capability.CREATE_GOVERNANCE_PROPOSAL,
        Capability.SERVE_AS_JUROR,
        Capability.RUN_NODE,
        Capability.RUN_VALIDATOR,
        Capability.OPERATE_GATEWAY,
        Capability.OPERATE_COMMUNITY_NODE,
        Capability.ACT_AS_EMISSARY,
    ]
    for cap in must_not_have:
        assert cap not in caps


def test_tier3_superset_of_tier2_and_can_create_groups_and_proposals():
    """
    Tier 3 includes all Tier 2 powers, plus group creation and proposal creation.
    """
    tier2 = compute_effective_role_profile(PoHTier.TIER2)
    tier3 = compute_effective_role_profile(PoHTier.TIER3)

    caps2 = tier2.capabilities
    caps3 = tier3.capabilities

    # Tier 3 must include all Tier 2 caps
    for cap in caps2:
        assert cap in caps3

    # And add "creator / organizer" powers
    assert Capability.CREATE_GROUP in caps3
    assert Capability.CREATE_GOVERNANCE_PROPOSAL in caps3


# ---------------------------------------------------------------------------
# Creator flag behaviour
# ---------------------------------------------------------------------------

def test_creator_flag_respects_opt_out():
    """
    From Tier 2 upwards, wants_creator=False should remove creator rewards.
    """
    flags_off = HumanRoleFlags(wants_creator=False)

    tier2_off = compute_effective_role_profile(PoHTier.TIER2, flags_off)
    tier3_off = compute_effective_role_profile(PoHTier.TIER3, flags_off)

    assert Capability.EARN_CREATOR_REWARDS not in tier2_off.capabilities
    assert Capability.EARN_CREATOR_REWARDS not in tier3_off.capabilities

    # Default (no flags passed) still earns creator rewards at Tier2+
    tier2_default = compute_effective_role_profile(PoHTier.TIER2)
    assert Capability.EARN_CREATOR_REWARDS in tier2_default.capabilities


# ---------------------------------------------------------------------------
# Juror / operator / validator / emissary gating by PoH tier
# ---------------------------------------------------------------------------

def test_juror_requires_tier3_and_flag():
    flags = HumanRoleFlags(wants_juror=True)

    tier2 = compute_effective_role_profile(PoHTier.TIER2, flags)
    tier3 = compute_effective_role_profile(PoHTier.TIER3, flags)

    assert Capability.SERVE_AS_JUROR not in tier2.capabilities
    assert Capability.SERVE_AS_JUROR in tier3.capabilities


def test_operator_requires_tier3_and_flag():
    flags = HumanRoleFlags(wants_operator=True)

    tier2 = compute_effective_role_profile(PoHTier.TIER2, flags)
    tier3 = compute_effective_role_profile(PoHTier.TIER3, flags)

    operator_caps = [
        Capability.RUN_NODE,
        Capability.OPERATE_GATEWAY,
        Capability.OPERATE_COMMUNITY_NODE,
    ]

    for cap in operator_caps:
        assert cap not in tier2.capabilities
        assert cap in tier3.capabilities


def test_validator_requires_tier3_and_flag():
    flags = HumanRoleFlags(wants_validator=True)

    tier2 = compute_effective_role_profile(PoHTier.TIER2, flags)
    tier3 = compute_effective_role_profile(PoHTier.TIER3, flags)

    assert Capability.RUN_VALIDATOR not in tier2.capabilities
    assert Capability.RUN_VALIDATOR in tier3.capabilities


def test_emissary_requires_tier3_and_flag():
    flags = HumanRoleFlags(wants_emissary=True)

    tier2 = compute_effective_role_profile(PoHTier.TIER2, flags)
    tier3 = compute_effective_role_profile(PoHTier.TIER3, flags)

    assert Capability.ACT_AS_EMISSARY not in tier2.capabilities
    assert Capability.ACT_AS_EMISSARY in tier3.capabilities


# ---------------------------------------------------------------------------
# Capability matrices (for UI / docs)
# ---------------------------------------------------------------------------

def test_capability_matrix_by_tier_basic_invariants():
    """
    The public capability matrix should match our expectations about
    posting & organizing across tiers.
    """
    matrix = capability_matrix_by_tier()

    # Keys are stringified tiers, including observer "0".
    for key in ("0", "1", "2", "3"):
        assert key in matrix

    t1 = set(matrix["1"])
    t2 = set(matrix["2"])
    t3 = set(matrix["3"])

    # Tier1 cannot post; Tier2 can
    assert "create_post" not in t1
    assert "create_post" in t2

    # Tier2 cannot create groups; Tier3 can
    assert "create_group" not in t2
    assert "create_group" in t3

    # Tier3 has at least as many base caps as Tier2
    assert t2.issubset(t3)


def test_capability_matrix_full_example_matches_flag_logic():
    """
    capability_matrix_full_example should illustrate the same flag behaviour
    we test above (e.g., juror only appearing at Tier3).
    """
    full = capability_matrix_full_example()

    # Structure: { "tier": { scenario_name: [caps...] } }
    for tier_key in ("0", "1", "2", "3"):
        assert tier_key in full
        assert "default" in full[tier_key]

    # Juror scenario: only Tier3 should have 'serve_as_juror'
    t2_juror = set(full["2"]["juror"])
    t3_juror = set(full["3"]["juror"])
    assert "serve_as_juror" not in t2_juror
    assert "serve_as_juror" in t3_juror

    # Validator scenario: only Tier3 should have 'run_validator'
    t2_val = set(full["2"]["validator"])
    t3_val = set(full["3"]["validator"])
    assert "run_validator" not in t2_val
    assert "run_validator" in t3_val
