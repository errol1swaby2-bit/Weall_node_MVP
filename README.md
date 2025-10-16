# 🌍 WeAll Node MVP

**Version:** v0.9.3 “All Green Build”  
**Status:** ✅ 100% Tests Passing  
**Author:** Errol Swaby  
**License:** MPL-2.0  

---

## 🧱 Overview
The **WeAll Node** is the core backend for the WeAll Protocol — a decentralized social-governance system built to coordinate human action transparently, democratically, and on-chain.

This MVP implements:
- Proof-of-Humanity (Tier 1–3) onboarding
- Post/comment creation and IPFS integration
- Peer-to-peer messaging
- Governance proposal/voting/enactment
- Ledger + chain simulation with validator rotation
- Static web frontend dashboard

---

## ⚙️ Features

### 🔐 Identity & Proof-of-Humanity
- Tier 1: email bootstrap  
- Tier 2: asynchronous media verification  
- Tier 3: live founder & juror session  
- Generates NFT-style verification badges

### 🪙 Ledger & Chain
- Simulated ledger (`WeCoinLedger`) with deposit, transfer, and balance tracking  
- Block finalization through Tier-3 validator rotation  
- Persistent `chain.json` and `executor_state.json`

### 🧩 Governance
- On-chain proposals, voting, and enactment  
- Stored in governance runtime (`governance.proposals`)  
- Compatible with frontend `/governance` tab

### 🗣️ Social Layer
- Posts, comments, and messaging between verified users  
- Optional IPFS media storage for posts (`ipfs_cid` field)  
- Frontend Feed supports creation and listing of posts

---

## 💻 Quick Start

### 1. Start IPFS
```bash
ipfs daemon &

2. Launch the Node (HTTPS)

./start_weall.sh

Visit https://127.0.0.1:8000

3. Run the Tests

pytest -q

✅ All 17 tests should pass.


---

🧠 Frontend Navigation

Page	Function

/login.html	User login / Tier 1 registration
/index.html	Main dashboard (Feed, Governance, Profile)
/verify.html	Founder/juror verification session
/panel.html	Tier-3 juror live panel



---

🌐 Networking

Local Access

You can connect from other devices on the same LAN using your phone or host’s IP:

https://<local_ip>:8000

P2P Mesh

Nodes automatically announce through /p2p/announce and /p2p/peers endpoints.
WebSocket relay available at /ws/p2p/{token}.


---

🧩 File Structure

weall_node/
 ├── weall_api.py          # FastAPI app
 ├── weall_executor.py     # Core logic (chain, ledger, content, PoH)
 ├── app_state/            # Chain + Ledger + Governance runtime
 ├── p2p/                  # Mesh + peer registry
 ├── frontend/             # HTML/JS frontend
 └── storage/              # SQLite optional persistence


---

🧪 Development Notes

Runs natively in Termux, Linux, or Docker

Default port: 8000

TLS certs auto-generated if missing

IPFS client auto-connects to local daemon

Supports autosave every 120 s



---

📜 License

Released under the Mozilla Public License 2.0 (MPL-2.0).


---

✨ Credits

Core Development: Errol Swaby

Protocol Design: Errol Swaby

AI Co-authoring Support: GPT-5
