set -euo pipefail

# Allow optional first arg, else auto-detect
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

# Use env var so we don't depend on argv plumbing
APP_PATH="${APP_PATH}" python3 - <<'PY'
import os, re, pathlib
from pathlib import Path

app_path = Path(os.environ["APP_PATH"])
text = app_path.read_text(encoding="utf-8", errors="ignore")

# 1) Remove brittle 307 redirects to /frontend/index.html if present
text = re.sub(
    r"@app\.get\(\"/index/\"[\s\S]*?return RedirectResponse\([\s\S]*?\)\n\n",
    "",
    text,
    flags=re.M,
)

# 2) Ensure StaticFiles mount uses html=True
text = re.sub(
    r'StaticFiles\(directory="dist"(.*?)\)',
    r'StaticFiles(directory="dist", html=True\1)',
    text,
    flags=re.M,
)

# 3) Add SPA catch-all route if missing
if "def spa_catch_all" not in text:
    text += """

from fastapi.responses import FileResponse, Response
from starlette.requests import Request
import os

@app.get("/{full_path:path}", include_in_schema=False)
async def spa_catch_all(full_path: str, request: Request):
    index_path = os.path.join("dist", "index.html")
    if os.path.exists(index_path):
        return FileResponse(index_path, media_type="text/html")
    return Response(status_code=404)
"""

app_path.write_text(text, encoding="utf-8")
print(f"✅ SPA mount updated in {app_path}")
PY

echo "✅ FastAPI SPA serving patched."
