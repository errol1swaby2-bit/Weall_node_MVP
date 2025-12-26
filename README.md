# WeAll Node MVP

**MVP Node Software for the WeAll Protocol** — a FastAPI-based node + a static web client served from the same process.

This repo is currently aimed at **local development and MVP validation** (Android/Termux or Linux).
It is **not production/mainnet-ready yet**.

---

## What’s included

- **Backend (FastAPI)**
  - Ledger + monetary policy scaffolding
  - Proof-of-Humanity (PoH) tier registry + role gating
  - Governance / proposals scaffolding
  - Disputes + juror/reputation wiring
  - Content: likes/comments + media upload endpoint (MVP)
  - P2P overlay scaffolding + optional IPFS pinning hooks

- **Frontend**
  - Static HTML/JS client served from: `/frontend/*`
  - MVP feed + session/onboarding flow (still being normalized)

---

## Status

Implemented so far (partial v2 alignment):
- Ledger + WeCoin monetary policy scaffolding
- PoH tiers & registry + role gating
- Jurors/disputes + reputation wiring
- Groups/emissaries + governance runtime scaffolding
- Termux-friendly scripts and a local single-node dev flow

Still in progress:
- Full PoH upgrade journeys (Tier 1→2→3 verification flows end-to-end)
- Strict PoH-gated governance enforcing 1-human-1-vote across vote surfaces
- Validator selection (PoH + reputation aware), slashing, and hardening
- STV elections for emissaries + group wallets

---

## Prerequisites

- Python **3.11+** (3.12 OK)
- Termux (Android) or Linux shell
- Optional: IPFS Kubo (if you want pinning experiments)

---

## Quick start (local)

```bash
git clone https://github.com/errol1swaby2-bit/Weall_node_MVP.git
cd Weall_node_MVP

python -m venv .venv
source .venv/bin/activate

python -m pip install -U pip
python -m pip install -r requirements.txt -r requirements-dev.txt

# run API (foreground)
python -m uvicorn weall_node.weall_api:app --host 127.0.0.1 --port 8000
Open:
Frontend: http://127.0.0.1:8000/frontend/index.html
Health:    http://127.0.0.1:8000/health
Running tests
Copy code
Bash
python -m pytest -q
python -m compileall -q .
Optional: IPFS (dev)
If you have ipfs installed:
Copy code
Bash
nohup ipfs daemon > ipfs.log 2>&1 &
Configuration / Environment
This project supports environment configuration via .env files.
Important: do NOT commit real secrets, API keys, or TLS private keys.
Recommended workflow:
Keep example templates committed (e.g. .env.example)
Keep real values local only: .env, .env.mail, etc.
Example for SMTP verification (Gmail example):
Copy code
Env
MAIL_FROM="WeAll weall.verify@gmail.com"
SMTP_HOST="smtp.gmail.com"
SMTP_PORT=465
MAIL_TLS=0
MAIL_SSL=1
SMTP_USER="your_gmail_username@gmail.com"
SMTP_PASS="your_app_password"
If .env is missing/invalid, the server should fall back to logging verification codes to console (dev behavior).
Repo hygiene / security expectations (before “production”)
If any of these files exist locally, they should be ignored and never tracked:
.env
.env.mail
cert.pem
key.pem
node_id.json
weall_state.json
*.log
If you suspect any real secret was committed historically:
rotate it immediately
remove the file from git history (e.g. git filter-repo)
add guardrails (.gitignore, secret scanning, CI)
Contributing
PRs are welcome. Good first contributions:
improve onboarding flow / frontend wiring
harden PoH tier enforcement paths
add CI (pytest + compileall)
tighten config validation + docs
License
See LICENSE.
