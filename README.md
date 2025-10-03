WeAll Node MVP

🚧 Status: Work in Progress 🚧
This repository contains the MVP implementation of the WeAll Node — a decentralized social protocol and blockchain network designed to support human-first coordination. The current version includes the scaffolding for APIs, blockchain state management, Proof-of-Humanity (PoH) integration, and IPFS content storage.
Continuity fixes and refactoring are ongoing; feedback is welcome.


---

📖 Overview

The WeAll Node provides:

API Layer (FastAPI)

Endpoints for posts, messaging, treasury, reputation, and PoH.

JSON-based communication with rate limiting, CORS, and metrics.


Consensus & Identity

Draft Proof-of-Humanity NFT validation and tiered onboarding rules.

Consensus parameters under weall_node/consensus/.


Blockchain State

Lightweight ledger and chain (app_state/ledger.py, app_state/chain.py).

Bitcoin-inspired halving cycle for rewards (2-year halving).


Storage Integration

IPFS client with pinning support for decentralized content.


Governance Draft

Simple proposal + voting system (1 person = 1 vote).




---

🗂 Repository Structure

weall_node_mvp/
│
├── weall_node/
│   ├── weall_api.py         # FastAPI entrypoint
│   ├── executor.py          # Node orchestration
│   ├── app_state/           # Blockchain state (ledger, chain, governance, node)
│   ├── api/                 # API routers (posts, treasury, reputation, messaging, PoH)
│   ├── ipfs/                # IPFS client integration
│   ├── consensus/           # Consensus params and rules
│   └── ...                  # Other support modules
│
├── requirements.txt         # Python dependencies
├── apply_weall_patch.py     # Patch/merge helpers (in progress)
├── weall_patch_combined.py  # Consolidated patch file (in progress)
└── README.md                # (this file)


---

🚀 Getting Started

Prerequisites

Python 3.11+

IPFS (Kubo) installed and accessible via ipfs daemon

(Optional) Docker (future deployment flow)


Install dependencies

pip install -r requirements.txt

Run IPFS daemon

ipfs daemon &

Start the API server

uvicorn weall_node.weall_api:app --host 0.0.0.0 --port 8000 --reload

Health check

curl http://127.0.0.1:8000/healthz


---

🔧 Current Limitations

Multiple entrypoints exist (main.py, app.py, executor.py, weall_api.py).
These will be unified in future commits.

Some modules contain stubs or patch artifacts (apply_weall_patch.py).

Testing is minimal — only a draft test_weall_api.py is included.

Deployment scripts (Docker/CI) not finalized.



---

🗺 Roadmap

[ ] Consolidate entrypoints into one clear CLI + API runner.

[ ] Strengthen persistence and state verification in ledger.

[ ] Expand PoH consensus validation.

[ ] Add pytest suite for APIs and chain logic.

[ ] Package Dockerfile + deployment pipeline.

[ ] Integrate tokenomics (2-year halving) fully into ledger.



---

🤝 Contributing

At this stage, contributions are welcome in the form of:

Bug reports & feedback on repo structure.

Suggestions for API design.

Pull requests addressing continuity (imports, tests, entrypoints).

---

📄 License

This project is licensed under the Mozilla Public License 2.0.
