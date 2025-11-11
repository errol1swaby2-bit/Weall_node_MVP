#!/usr/bin/env bash
set -Eeuo pipefail

# --- 1) POSIX-safe runner (works even if /system/bin/sh runs it) ---
mkdir -p bin
cat > bin/run_api_dev_posix.sh <<'POSIX'
#!/system/bin/sh
set -eu
cd "$(dirname "$0")/.."
[ -d ".venv" ] && . .venv/bin/activate
PYMOD="weall_node.main:app"
if command -v uvicorn >/dev/null 2>&1; then
  exec uvicorn "$PYMOD" --host 127.0.0.1 --port 8000 --reload
else
  exec python3 -m uvicorn "$PYMOD" --host 127.0.0.1 --port 8000 --reload
fi
POSIX
chmod +x bin/run_api_dev_posix.sh

# --- 2) Make existing bash runner tolerant on Termux (no pipefail crash) ---
if [ -f bin/run_api_dev.sh ]; then
  # Ensure bash shebang
  sed -i '1s|^#!.*|#!/usr/bin/env bash|' bin/run_api_dev.sh
  # Soften strict mode if /bin/sh happens to run it
  if ! grep -q 'WEALL_DEV_EMAIL' bin/run_api_dev.sh; then
    sed -i '1iexport WEALL_DEV_EMAIL=1' bin/run_api_dev.sh
  fi
  # Replace strict pipefail with a safe no-op if unsupported
  sed -i 's/set -Eeuo pipefail/set -euo pipefail 2>\/dev\/null || set -eu/' bin/run_api_dev.sh
  chmod +x bin/run_api_dev.sh
fi

# --- 3) Fix email input fields (remove 6-char limit; keep OTP max=6) ---
FRONT="weall_node/frontend"
[ -d "$FRONT" ] || { echo "[WARN] missing $FRONT"; exit 0; }

fix_email_fields() {
  f="$1"
  # Only touch lines that look like email inputs
  if grep -qE '(id|name)="email"' "$f"; then
    # remove maxlength / pattern on email inputs
    sed -i -E '/(id|name)="email"/ s/[[:space:]]maxlength="[^"]*"//g' "$f"
    sed -i -E '/(id|name)="email"/ s/[[:space:]]pattern="[^"]*"//g' "$f"
    # force type=email (from text/number if present)
    sed -i -E '/(id|name)="email"/ s/type="text"/type="email"/g' "$f"
    sed -i -E '/(id|name)="email"/ s/type="number"/type="email"/g' "$f"
    echo "patched(email): $f"
  fi
  # Keep OTP/code fields at 6 chars
  if grep -qE '(id|name)="(code|otp)"' "$f"; then
    # ensure maxlength=6 exists
    awk '
      BEGIN{changed=0}
      {
        line=$0
        if (line ~ /(id|name)="(code|otp)"/) {
          if (line ~ /maxlength="/) {
            gsub(/maxlength="[^"]*"/,"maxlength=\"6\"", line)
          } else {
            sub(/>/," maxlength=\"6\">", line)
          }
          changed=1
        }
        print line
      }
      END{ if (changed) {} }
    ' "$f" > "$f.tmp" && mv "$f.tmp" "$f"
    echo "patched(otp): $f"
  fi
}

export -f fix_email_fields
find "$FRONT" -maxdepth 1 -type f -name "*.html" -print0 | xargs -0 -I{} bash -c 'fix_email_fields "$@"' _ {}

echo "[✓] Runner fixed and email field unlocked."
