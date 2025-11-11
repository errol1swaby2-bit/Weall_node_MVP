#!/usr/bin/env bash
set -euo pipefail
INIT="weall_node/weall_runtime/__init__.py"
[ -f "$INIT" ] || { echo "Missing $INIT"; exit 1; }
cp -f "$INIT" "$INIT.bak.$(date +%s)"

python3 - <<'PY'
from pathlib import Path
p = Path("weall_node/weall_runtime/__init__.py")
src = p.read_text(encoding="utf-8")

# 1) Comment out any hard imports of crypto_symmetric.SimpleFernet
lines = src.splitlines()
out = []
for L in lines:
    if "from .crypto_symmetric import SimpleFernet" in L and not L.strip().startswith("#"):
        out.append("# " + L + "  # disabled by fix: we require fallback logic")
    else:
        out.append(L)
src = "\n".join(out)

# 2) Ensure a single, canonical fallback block exists at the top
marker = "# == DEV CRYPTO FALLBACK INSERTED =="
fallback = f"""{marker}
try:
    # Prefer the real implementation (requires pycryptodome: Crypto.Cipher.AES)
    from .crypto_symmetric import SimpleFernet as _RealSimpleFernet  # type: ignore
    SimpleFernet = _RealSimpleFernet
except Exception:  # ImportError or runtime env missing Crypto
    # Dev-only fallback: pure-Python shim to unblock local dev on low-end devices.
    from .crypto_symmetric_dev import SimpleFernet  # type: ignore
{marker}
"""

if marker not in src:
    src = fallback.strip() + "\n\n" + src
else:
    # Ensure our fallback is before any other references
    # Remove duplicates and re-insert cleanly at top
    parts = [s for s in src.split(marker) if s.strip()]
    # Replace entire file with a top fallback + original (without any prior fallback)
    # First, strip existing fallback blocks
    cleaned = []
    skip = 0
    for line in src.splitlines():
        if marker in line:
            skip = 1 - skip  # toggle when we hit marker start/stop
            continue
        if skip == 0:
            cleaned.append(line)
    src = fallback.strip() + "\n\n" + "\n".join(cleaned).strip() + "\n"

p.write_text(src, encoding="utf-8")
print("[✓] Patched:", p)
PY

echo "[✓] weall_runtime/__init__.py now prefers real crypto, else dev shim."
