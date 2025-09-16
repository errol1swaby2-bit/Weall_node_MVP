# app_state.py
"""
Global singletons for shared state across API routers.
"""

from weall_runtime.ledger import Ledger
from weall_runtime.governance import Governance
from weall_runtime.poh import ProofOfHumanity
from weall_runtime.sync import Node

# Shared ledger
ledger = Ledger(persist_file="ledger_state.json")

# Shared governance instance (uses the shared ledger)
governance = Governance(ledger)

# Shared Proof of Humanity instance
poh = ProofOfHumanity(ledger)

# Shared Node instance for P2P sync
node = Node(ledger)
