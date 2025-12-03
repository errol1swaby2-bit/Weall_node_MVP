#!/usr/bin/env bash
set -euo pipefail
FRONT="weall_node/frontend"
[ -d "$FRONT" ] || { echo "Missing $FRONT"; exit 1; }

# Ensure a static entry exists
[ -f "$FRONT/app.js" ] || cat > "$FRONT/app.js" <<'JS'
document.addEventListener('DOMContentLoaded', async () => {
  console.log('Static app.js loaded');
  try {
    const r = await fetch('/api/health'); console.log('API health:', await r.json());
  } catch(e) { console.warn('API health failed:', e); }
});
JS

# Replace common Vite module entries with static app.js in ALL HTML (top level)
find "$FRONT" -maxdepth 1 -type f -name "*.html" -print0 | while IFS= read -r -d '' f; do
  if grep -qE 'type="module".*src="/?src/main\.(tsx|ts|js)"' "$f"; then
    sed -i -E 's#<script[^>]*type="module"[^>]*src="/?src/main\.(tsx|ts|js)".*></script>#<script src="app.js"></script>#Ig' "$f"
    echo "patched(vite→static): $f"
  fi
done

# Also catch any raw references to /src/main.tsx left anywhere under frontend
grep -RIl --exclude='*.bak' --exclude='*.bak.*' '/src/main\.tsx' "$FRONT" | while read -r f; do
  sed -i 's#/src/main\.tsx#app.js#g' "$f"
  echo "replaced raw /src/main.tsx in: $f"
done

echo "[✓] Vite entries replaced with static app.js"
