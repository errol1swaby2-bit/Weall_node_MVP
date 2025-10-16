# WeAll Node — v0.9.3 “All Green Build”
**Release Date:** 2025-10-16  
**Status:** ✅ All tests passing (100%)  
**Branch:** main  
**Tag:** v0.9.3

---

### 🚀 Highlights
- ✅ Full pytest suite passing (17/17 tests)
- ✅ HTTPS mode operational via self-signed TLS (Termux compatible)
- ✅ Frontend dashboard verified live at https://127.0.0.1:8000
- ✅ IPFS daemon connected and functional
- ✅ PoH → Posts → Governance → Ledger integration tested end-to-end

---

### 🧩 Core Updates
#### Backend
- Added optional `ipfs_cid` support to `WeAllExecutor.create_post()`.
- Updated `weall_api.py` HTTPS bootstrap and Prometheus metrics middleware.
- Added graceful fallback for local LAN peers and static frontend serving.
- Improved chain, ledger, and governance synchronization safety.
- Enhanced error handling and cross-origin middleware configuration.

#### Frontend
- Unified multi-tab dashboard (Feed, Governance, Profile) in `frontend/index.html`.
- Functional login and Tier-1 onboarding through `/login.html`.
- Verified post creation, comment, and governance listing flows.
- Auto-redirects to dashboard post-login.
- Ready for future media/IPFS uploads.

#### Infrastructure
- Added `start_weall.sh` for automatic TLS generation and startup.
- Compatible with Termux (Android) and Linux hosts.
- Cleaned dependency tree (`requirements.txt` + explicit uvicorn entry).
- IPFS dev CID stubs supported for offline testing.

---

### 🧪 Test Suite
| Test File | Purpose | Result |
|------------|----------|--------|
| `test_api_flow.py` | End-to-end PoH + content flow | ✅ Passed |
| `test_chain_mempool.py` | Chain event recording + validator logic | ✅ Passed |
| `test_content.py` | Posts/comments creation and linking | ✅ Passed |
| `test_governance.py` | Proposal + voting simulation | ✅ Passed |
| `test_wallet.py` | Ledger + account management | ✅ Passed |
| *(and 12 others)* |  | ✅ Passed |

---

### 🔧 Known Warnings
- `pytest_asyncio` deprecation warning (safe; no functional impact).
- IPFS Kubo version 0.37+ triggers version mismatch warning (client still works).

---

### 🪙 Next Planned Version (v0.9.4)
- IPFS media upload from frontend (`input type=file` → `/ipfs/add`)
- Post disputes (creator vs juror)
- Basic node reputation and balance UI
- Multi-peer local LAN handshake test

---

**Maintainer:** Errol Swaby  
**License:** MPL-2.0  
**Repository:** [https://github.com/errol1swaby2/Weall_node_MVP](https://github.com/errol1swaby2/Weall_node_MVP)
