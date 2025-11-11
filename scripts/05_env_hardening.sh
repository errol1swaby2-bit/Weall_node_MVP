set -euo pipefail

# Ensure .env has required keys (idempotent no-ops if present)
req_keys=(VITE_CHAIN_RPC VITE_CHAIN_ID VITE_WECOIN_ADDRESS VITE_GOVERNANCE_ADDRESS VITE_POH_ADDRESS)
touch .env
for k in "${req_keys[@]}"; do
  grep -q "^$k=" .env || echo "$k=" >> .env
done

# Backend: add CORS from env if not present
APP="main.py"; [ -f "$APP" ] || APP="weall_node/main.py"
python3 - <<'PY'
import re, os, pathlib
p = pathlib.Path(os.environ.get("APP_PATH","")) if os.environ.get("APP_PATH") else pathlib.Path("main.py")
if not p.exists():
    p = pathlib.Path("weall_node/main.py")
t = p.read_text(encoding="utf-8", errors="ignore")

if "CORSMiddleware" not in t:
    t = t.replace("from fastapi import", "from fastapi import")
    t = "from fastapi.middleware.cors import CORSMiddleware\n" + t
    t = re.sub(r"(app\s*=\s*FastAPI\(.*?\)\n)",
               r"""\1
import os
_origins = os.getenv("CORS_ORIGINS","http://localhost:5173").split(",")
app.add_middleware(
    CORSMiddleware,
    allow_origins=_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
""", t, count=1, flags=re.S)
    p.write_text(t, encoding="utf-8")
    print("✅ CORS middleware added, reading CORS_ORIGINS from env")
else:
    print("ℹ️ CORS already present.")
PY

echo "✅ .env keys scaffolded; CORS configured."
