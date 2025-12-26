# WeAll Node — Spec Traceability Map (v2.1)

This repository implements a functional MVP of the WeAll Protocol.
This file provides a lightweight mapping from Full Scope Spec v2.1 clauses
to code locations, so spec alignment is auditable and incremental.

## Spec §2 — Roles & Tiers
- Tier definitions + capability gating:
  - weall_node/weall_runtime/roles.py
- Permission enforcement hooks:
  - weall_node/security/permissions.py
  - weall_node/api/content.py (posting rep threshold)
  - weall_node/api/groups.py
  - weall_node/api/governance.py

## Spec §10 — Reputation
- Reputation model + thresholds:
  - weall_node/weall_runtime/reputation.py
- Auto-ban enforcement:
  - weall_node/security/permissions.py

## Spec §7 — Governance (MVP)
- Proposals + vote counting:
  - weall_node/api/governance.py

## Spec §5 — Ledger + Economics (MVP constants)
- Supply/reward/halving/pools:
  - weall_node/weall_runtime/ledger.py

## Spec §6 — Consensus & Finality
- Current state: MVP facade endpoints exist, full driver/finality loop is pending.
  - weall_node/api/consensus.py
  - weall_node/weall_runtime/consensus_driver.py (planned)

## Spec §14 — Code↔Spec Traceability
- This file + spec/traceability.yml are the initial implementation.
