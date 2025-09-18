# WeAll Node MVP

WeAll Node is a decentralized governance and content-sharing engine built on top of FastAPI, IPFS, and custom consensus logic.  
This repository contains the **MVP implementation** of the WeAll Node, including API endpoints, CLI tools, and frontend templates.

---

## 🚀 Features
- **Decentralized Governance** – proposals, voting, and disputes.
- **Content Layer** – posting, commenting, tagging, and IPFS-based storage.
- **Proof-of-Humanity** – lightweight POH requirements for registration.
- **Wallet Support** – simple on-chain balance tracking and transfers.
- **CLI Tool** – interact directly with the node for testing and automation.
- **Web Frontend** – TikTok-style feed, governance dashboard, and user profile.

---

## 📦 Installation

### Prerequisites
- Python 3.10+
- Git
- [IPFS daemon](https://docs.ipfs.io/install/) running locally or remotely

### Setup
```bash
git clone https://github.com/errol1swaby2-bit/Weall_node_MVP.git
cd Weall_node_MVP
pip install -r requirements.txt


---

🖥️ Usage

Run the API

uvicorn weall-node.main:app --reload --host 0.0.0.0 --port 8000

API will be available at: http://localhost:8000

Run the CLI

python weall-node/weall_cli.py

CLI Commands

register – create a new account

propose – submit governance proposals

vote – vote on proposals

post – create a new post

comment – add a comment to a post

… and more



---

🧪 Testing

pytest


---
🌍 Roadmap

[ ] Strengthen governance mechanisms (proposal lifecycle, disputes, juror system)

[ ] Implement robust security layers (signatures, account protections, dispute resolution)

[ ] Expand social media features (feed, profiles, reputation, content curation)

[ ] Build smooth onboarding flow (registration, Proof-of-Humanity, staking)

[ ] Launch initial network-ready node release



---

📄 License

This project is licensed under the Mozilla Public License 2.0.
