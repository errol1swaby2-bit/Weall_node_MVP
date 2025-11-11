set -euo pipefail

# Allow optional explicit path; otherwise auto-detect
APP_PATH="${1:-}"
if [ -z "${APP_PATH}" ]; then
  if [ -f "main.py" ]; then
    APP_PATH="main.py"
  elif [ -f "weall_node/main.py" ]; then
    APP_PATH="weall_node/main.py"
  else
    echo "❌ Could not find main.py or weall_node/main.py in $(pwd)"
    exit 1
  fi
fi

APP_PATH="${APP_PATH}" python3 - <<'PY'
import os, re
from pathlib import Path

app_path = Path(os.environ["APP_PATH"])
text = app_path.read_text(encoding="utf-8", errors="ignore")

has_on_event = "@app.on_event(" in text
has_lifespan = "async def lifespan(" in text

if has_on_event and not has_lifespan:
    # Ensure asynccontextmanager import exists once
    if "from contextlib import asynccontextmanager" not in text:
        text = 'from contextlib import asynccontextmanager\n' + text

    # Inject a simple lifespan context right after FastAPI app init
    lifespan_block = """
@asynccontextmanager
async def lifespan(app):
    # TODO: move your startup/shutdown code here
    yield

try:
    app.router.lifespan_context = lifespan  # FastAPI >= 0.100
except Exception:
    pass
"""

    # Place lifespan after "app = FastAPI(...)" the first time it appears
    text = re.sub(
        r"(app\s*=\s*FastAPI\(.*?\)\s*\n)",
        r"\\1" + lifespan_block + "\n",
        text,
        count=1,
        flags=re.S,
    )

    # Comment out @app.on_event handlers (startup/shutdown) bodies
    text = re.sub(
        r'@app\.on_event\((?:"|\')\w+(?:"|\')\)\s*\ndef\s+\w+\(.*?\):\s*[\s\S]*?(?=\n{2,}|$)',
        '# [migrated to lifespan]\n',
        text,
        flags=re.S,
    )

    app_path.write_text(text, encoding="utf-8")
    print(f"✅ Lifespan context injected; on_event handlers commented in {app_path}")
else:
    if not has_on_event:
        print(f"ℹ️ No @app.on_event handlers found in {app_path}; nothing to migrate.")
    else:
        print(f"ℹ️ Lifespan already present in {app_path}; no changes made.")
PY

echo "✅ FastAPI lifespan patch completed."
