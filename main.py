from fastapi.middleware.cors import CORSMiddleware
"""
WeAll Node Launcher — Android Entry Point
-----------------------------------------
Runs the FastAPI backend (uvicorn) in a background thread,
then loads the local dashboard via a WebView.

Reads bind & public URL from weall_config.yaml:
  server.host, server.port, server.public_base_url
"""

import threading, subprocess, time, os, sys
import socket

# Optional: pywebview may not be available in some envs
try:
    import webview
except Exception:
    webview = None

# --- Config hooks ---
from weall_node.config import (
    load_config,
    get_bind_host,
    get_bind_port,
    get_public_base_url,
)

BASE_DIR = os.path.dirname(__file__)
CFG = load_config(repo_root=BASE_DIR)

BIND_HOST = get_bind_host(CFG)  # e.g., "127.0.0.1" or "0.0.0.0"
BIND_PORT = get_bind_port(CFG)  # e.g., 8000
PUBLIC_BASE = get_public_base_url(CFG)  # e.g., "http://127.0.0.1:8000"

# If your frontend is served by FastAPI under a subpath, keep this:
FRONTEND_PATH = "/frontendtendtend/index.html"
# If you serve a SPA separately (Vite/NGINX), change to "/" or your SPA entry.


def start_server():
    """Run the FastAPI backend via uvicorn."""
    os.chdir(BASE_DIR)
    cmd = [
        sys.executable,
        "-m",
        "uvicorn",
        "weall_node.weall_api:app",
        "--host",
        str(BIND_HOST),
        "--port",
        str(BIND_PORT),
    ]
    # In production, consider logging to a file instead of DEVNULL
    subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def wait_for_server(host: str, port: int, timeout: float = 20.0) -> bool:
    start = time.time()
    while time.time() - start < timeout:
        try:
            with socket.create_connection((host, port), timeout=2.0):
                return True
        except OSError:
            time.sleep(0.5)
    return False


def main():
    # Start backend
    threading.Thread(target=start_server, daemon=True).start()
    print(f"Starting WeAll Node (uvicorn {BIND_HOST}:{BIND_PORT}) ...")

    # For 0.0.0.0 bind, the local loopback for readiness is 127.0.0.1
    probe_host = "127.0.0.1" if BIND_HOST in ("0.0.0.0", "localhost") else BIND_HOST

    if wait_for_server(probe_host, BIND_PORT):
        print(f"Backend ready at {PUBLIC_BASE}")
    else:
        print("Warning: backend not reachable yet; continuing to open WebView")

    # Launch WebView pointing to configured public base + frontend path
    url = f"{PUBLIC_BASE.rstrip('/')}{FRONTEND_PATH}"
    print(f"Opening UI at {url}")

    if webview:
        webview.create_window("WeAll Node", url)
        webview.start()
    else:
        # Fallback: open in default browser if pywebview is unavailable
        try:
            import webbrowser

            webbrowser.open(url)
        except Exception:
            pass


if __name__ == "__main__":
    main()


from fastapi.responses import FileResponse, Response
from starlette.requests import Request
import os

@app.get("/{full_path:path}", include_in_schema=False)
async def spa_catch_all(full_path: str, request: Request):
    index_path = os.path.join("dist", "index.html")
    if os.path.exists(index_path):
        return FileResponse(index_path, media_type="text/html")
    return Response(status_code=404)
