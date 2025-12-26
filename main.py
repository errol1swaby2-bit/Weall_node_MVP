"""main.py (repo root)

WeAll Node Launcher — Android/desktop helper entrypoint

This file is intentionally *standalone* and should not contain FastAPI routes.
The FastAPI app lives in: weall_node/weall_api.py

Usage:
  python main.py

It will:
- start uvicorn for weall_node.weall_api:app
- optionally open a local WebView (if pywebview is installed)

Config:
- Reads bind & public URL from weall_config.yaml (if present) via weall_node.config_loader
- Falls back to localhost defaults
"""

from __future__ import annotations

import os
import sys
import threading
import time
import webbrowser
from pathlib import Path
from typing import Optional

import uvicorn

try:
    import webview  # type: ignore
except Exception:
    webview = None  # optional

from weall_node.config_loader import load_config
from weall_node.weall_api import app

DEFAULT_BIND_HOST = os.getenv("WEALL_BIND_HOST", "127.0.0.1")
DEFAULT_BIND_PORT = int(os.getenv("WEALL_BIND_PORT", "8000"))
DEFAULT_PUBLIC_URL = os.getenv("WEALL_PUBLIC_URL", f"http://{DEFAULT_BIND_HOST}:{DEFAULT_BIND_PORT}")

# For local webview, point at the actual frontend route exposed by weall_node/weall_api.py
FRONTEND_PATH = "/frontend/index.html"


def _run_uvicorn(host: str, port: int) -> None:
    uvicorn.run(app, host=host, port=port, log_level="info")


def _open_browser(url: str) -> None:
    # Delay slightly so server is up
    time.sleep(0.6)
    try:
        webbrowser.open(url, new=1)
    except Exception:
        pass


def _open_webview(url: str) -> None:
    if webview is None:
        _open_browser(url)
        return
    time.sleep(0.6)
    try:
        webview.create_window("WeAll", url, width=1200, height=800)
        webview.start()
    except Exception:
        _open_browser(url)


def main() -> int:
    # Optional config yaml in repo root
    cfg_path = Path("weall_config.yaml")
    cfg = load_config(str(cfg_path)) if cfg_path.exists() else {}

    host = str(cfg.get("bind_host") or DEFAULT_BIND_HOST)
    port = int(cfg.get("bind_port") or DEFAULT_BIND_PORT)

    public_url = str(cfg.get("public_url") or DEFAULT_PUBLIC_URL).rstrip("/")
    ui_url = public_url + FRONTEND_PATH

    # Start API server
    t = threading.Thread(target=_run_uvicorn, args=(host, port), daemon=True)
    t.start()

    # Open UI
    use_webview = str(os.getenv("WEALL_USE_WEBVIEW", "0")).lower() in ("1", "true", "yes")
    if use_webview:
        _open_webview(ui_url)
    else:
        _open_browser(ui_url)

    # Keep alive while uvicorn thread runs
    try:
        while t.is_alive():
            time.sleep(0.5)
    except KeyboardInterrupt:
        return 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
