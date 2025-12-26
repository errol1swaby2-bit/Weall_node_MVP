# tests/test_poh_roles_gate.py
from __future__ import annotations

from weall_node.weall_runtime.roles import (
    PoHTier,
    Capability,
    capability_matrix_by_tier,
    capability_matrix_full_example,
    compute_effective_role_profile,
    HumanRoleFlags,
)


def _caps_for(tier: PoHTier):
    prof = compute_effective_role_profile(tier)
    return set(prof.capabilities)


def test_capability_matrix_exports():
    m = capability_matrix_by_tier()
    assert "0" in m and "1" in m and "2" in m and "3" in m

    ex = capability_matrix_full_example()
    assert "3" in ex
    assert "default" in ex["3"]
    assert "juror" in ex["3"]
    assert "validator" in ex["3"]
    assert "operator" in ex["3"]
    assert "emissary" in ex["3"]


def test_tier0_view_only():
    c = _caps_for(PoHTier.TIER0)
    assert Capability.VIEW_PUBLIC_CONTENT in c
    assert Capability.LIKE not in c
    assert Capability.COMMENT not in c
    assert Capability.CREATE_POST not in c
    assert Capability.VOTE_GOVERNANCE not in c
    assert Capability.JOIN_GROUPS not in c


def test_tier1_like_comment_only_spec():
    """
    Spec v2.1:
      Tier 1 = like + comment (no posting, no voting, no groups)
    """
    c = _caps_for(PoHTier.TIER1)
    assert Capability.VIEW_PUBLIC_CONTENT in c
    assert Capability.LIKE in c
    assert Capability.COMMENT in c

    assert Capability.CREATE_POST not in c
    assert Capability.VOTE_GOVERNANCE not in c
    assert Capability.JOIN_GROUPS not in c


def test_tier2_post_vote_join_spec():
    """
    Spec v2.1:
      Tier 2 = post + vote + join groups (and still like/comment)
    """
    c = _caps_for(PoHTier.TIER2)
    assert Capability.CREATE_POST in c
    assert Capability.VOTE_GOVERNANCE in c
    assert Capability.JOIN_GROUPS in c
    assert Capability.LIKE in c
    assert Capability.COMMENT in c


def test_tier3_opt_in_roles():
    """
    Tier 3 enables steward actions and opt-in duties.
    """
    # Default Tier3 has steward actions
    c = _caps_for(PoHTier.TIER3)
    assert Capability.CREATE_GROUP in c
    assert Capability.CREATE_GOVERNANCE_PROPOSAL in c

    # Juror opt-in
    juror = compute_effective_role_profile(PoHTier.TIER3, HumanRoleFlags(wants_juror=True))
    assert Capability.SERVE_AS_JUROR in set(juror.capabilities)

    # Validator opt-in
    val = compute_effective_role_profile(PoHTier.TIER3, HumanRoleFlags(wants_validator=True))
    assert Capability.RUN_VALIDATOR in set(val.capabilities)

    # Operator opt-in
    op = compute_effective_role_profile(PoHTier.TIER3, HumanRoleFlags(wants_operator=True))
    assert Capability.OPERATE_GATEWAY in set(op.capabilities)

    # Emissary opt-in
    em = compute_effective_role_profile(PoHTier.TIER3, HumanRoleFlags(wants_emissary=True))
    assert Capability.ACT_AS_EMISSARY in set(em.capabilities)
