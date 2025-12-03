WeAll Node MVP

A FastAPI-based node for the WeAll protocol, bundling:

Backend APIs (ledger, governance, PoH, content, messaging, treasury, validators/operators, etc.)

A static HTML/JS frontend served from /frontend/*

Local single-node demo consensus & storage (with optional IPFS pinning)


This repository is meant for local development and MVP validation on Android (Termux) or Linux.

Table of contents

Prerequisites

Quick start

Environment

Run commands

Frontend

Verification flow (Tier-1/2/3)

Email delivery

IPFS

Security hardening

Known issues

Changelog — ZIP (2025-11-02) vs Public Repo

Mid-update notice



---

Prerequisites

Python 3.11+ (3.12 OK)

Termux (Android) or Linux shell

IPFS Kubo (optional for pinning; we tested 0.38.1 with warnings)

Node/Browser for the static frontend (no build step required)


Recommended Python packages:

pip install fastapi uvicorn pydantic sqlmodel argon2-cffi pyjwt fastapi-mail

> If you don’t plan to send real emails, fastapi-mail is optional (see Email delivery).




---

Quick start

# clone or unzip the project into ~/Weall_node_MVP
cd ~/Weall_node_MVP

# (optional) start IPFS
nohup ipfs daemon > ipfs.log 2>&1 &

# run API (foreground so you see logs)
python3 -m uvicorn weall_node.weall_api:app --host 127.0.0.1 --port 8000

Open in your browser (on the device):

http://127.0.0.1:8000/frontend/index.html


---

Environment

Create a .env at the project root to enable real email delivery (Gmail SMTP example):

# MAIL FROM IDENTITY
MAIL_FROM="WeAll <weall.verify@gmail.com>"

# SMTP (Gmail example)
SMTP_HOST="smtp.gmail.com"
SMTP_PORT=465
MAIL_TLS=0
MAIL_SSL=1
SMTP_USER="your_gmail_username@gmail.com"
SMTP_PASS="your_app_password"  # App Password if 2FA is enabled

> If .env is missing or invalid, the server logs the verification code to console and continues gracefully.




---

Run commands

Common ones we used during development:

# stop any existing server
pkill -f "uvicorn .*weall_node.weall_api:app" || true

# start API in foreground
python3 -m uvicorn weall_node.weall_api:app --host 127.0.0.1 --port 8000

# start API in background
nohup python3 -m uvicorn weall_node.weall_api:app --host 127.0.0.1 --port 8000 > api.log 2>&1 &

# quick health check
curl -fsS http://127.0.0.1:8000/health

IPFS (optional):

# kill & start IPFS
pkill -f "ipfs daemon" 2>/dev/null || true
nohup ipfs daemon > ipfs.log 2>&1 &


---

Frontend

All static assets are served from /frontend/*:

index.html — landing/dashboard

login.html — login portal (redirect target for unauthenticated flows)

onboarding.html — Tier-1 email code flow

capture.html — Tier-2/3 WebRTC capture (now enforced)

profile.html — shows PoH/NFT state, uses nft_minted boolean

juror.html, governance.html, rewards.html, operator.html, etc.


Path & asset fixes (done in ZIP)

All absolute links like /styles.css, /session.js, /favicon.svg now point to /frontend/style.css, /frontend/session.js, /frontend/favicon.svg.

“Back” links that previously pointed at / now go to /frontend/index.html.

Login/signup canonicalized:

/login.html → 307 → /frontend/login.html

/signup.html → 307 → /frontend/onboarding.html




---

Verification flow (Tier-1/2/3)

Tier-1 (email)

POST /auth/start (or legacy: POST /auth/email/request_code) — sends a 6-digit code.

POST /auth/verify (or legacy: POST /auth/email/verify_code) — verifies and issues a dev session cookie (weall_session).


Tier-2 / Tier-3 (video proof of humanness)

Frontend now forces WebRTC video capture before advancing.

capture.html is the canonical page for recording & submission.

UI blocks “Next” if no approved video was recorded/uploaded.


Server-side

/poh/status/{user_id} returns { user_id, poh_level, nft_minted }-style data.

Frontend displays NFT Minted using nft_minted (boolean), replacing any prior length-check of nfts?.length.



---

Email delivery

By default, FastAPI-Mail is enabled. The server attempts to send verification codes from MAIL_FROM using SMTP settings in .env. If sending fails, the code is printed to the console:

[AUTH] dev-only: verification code for <email> = 123456
[MAIL] code sent to <email>
# or:
[MAIL] send failed for <email>: <reason>

Legacy endpoints kept for old frontends

POST /auth/email/request_code → aliased to auth_start

POST /auth/email/verify_code  → aliased to auth_verify



---

IPFS

Kubo 0.38.1 works but may log:

“VersionMismatch” in ipfshttpclient (client expects 0.5.0–<0.9.0)

Netlink permission warnings on Android (Termux) — harmless for local dev


Gateway is typically on http://127.0.0.1:8080/



---

Security hardening

CORS restricted to local origins by default.

Request IDs injected (X-Request-ID) for each request.

Security headers via a combined middleware:

X-Frame-Options: DENY

X-Content-Type-Options: nosniff

Referrer-Policy: no-referrer

Permissions-Policy denies geolocation/mic/camera by default (WebRTC pages will prompt when needed).

CSP: default-src 'self' with data/blob allowances for images/media.




---

Known issues

On Android/Termux, ipfshttpclient may warn about Kubo 0.38.1. Functionality is otherwise fine for the MVP.

Some older pages may still reference deprecated endpoints if you’ve forked or customized beyond this ZIP; search your edited pages for:

/poh/status?account_id=... → must be /poh/status/{user_id}

/auth/email/request_code → /auth/start

/auth/email/verify_code  → /auth/verify




---

Changelog — ZIP (2025-11-02) vs Public Repo

> This section summarizes what’s changed in the uploaded ZIP compared to the public repo as of 2025-11-02. Items marked [NEW], [FIX], [CHANGE], [KEEP].



Frontend

[CHANGE] Canonical asset paths to avoid 404s: all absolute references now use /frontend/....

[FIX] Login/signup redirects:

/login.html → 307 → /frontend/login.html

/signup.html → 307 → /frontend/onboarding.html


[CHANGE] PoH status usage:

Replaced nfts?.length > 0 checks with data.nft_minted boolean.

unified “NFT Minted” display across index.html and profile.html.


[NEW] Tier-2/Tier-3 WebRTC enforcement in UI:

Users cannot proceed without recording/confirming a video in capture.html.


[FIX] Removed stray jQuery-style updater; single consistent DOM updater for #pfNft.


Auth & Sessions

[NEW] Minimal email auth endpoints:

POST /auth/start (send 6-digit code; cookies set on verify)

POST /auth/verify


[KEEP] Legacy aliases:

POST /auth/email/request_code → auth_start

POST /auth/email/verify_code → auth_verify


[NEW] .env-driven email sending (FastAPI-Mail). If .env missing/invalid, codes print to console but auth continues.


API surface

[CHANGE] /poh/status/{user_id} is the supported path (was ?account_id=... in older UIs).

[FIX] Added safety 307 redirects for /index.html, /login.html, /signup.html to mapped /frontend/*.


Middleware & Security

[NEW] Request-ID + security headers + conservative CSP combined into one middleware.

[FIX] CORS tightened to local origins by default.


Developer experience

[NEW] Clear run scripts/commands included in README.

[FIX] Console email fallback + explicit log lines for mail success/failure.



---

Mid-update notice

> Status: In-progress update (auth + Tier-2/Tier-3 enforcement + frontend path fixes).
What it means:

Email login is functional using either real SMTP (via .env) or console codes (fallback).

Frontend now consistently pulls assets from /frontend/* and enforces WebRTC for higher tiers.

Legacy endpoints remain aliased so older pages won’t break while you migrate.

Additional refactors (IPFS client version pinning, further UI polish) are planned next.
