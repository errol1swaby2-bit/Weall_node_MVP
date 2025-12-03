# weall_node/__main__.py
"""
Entry point for running the WeAll Node as a module:
    python -m weall_node [--host 0.0.0.0] [--port 8443] [--state ./weall_state.json]
                         [--certfile path.pem --keyfile path.key]
                         [--cn weall.local] [--no-self-signed]
Env toggles:
  GENESIS_MODE=1            -> apply genesis bootstrap on first run
  GENESIS_AUTO_SEAL=1       -> seal applied manifest automatically
  WEALL_NODE_SECRET=...     -> at-rest encryption for keys/config
  WEALL_ICE_SERVERS='[...]' -> optional JSON for ICE/TURN servers
"""

from __future__ import annotations
import os
import sys
import time
import signal
import argparse

from .executor import WeAllExecutor


def parse_args(argv=None):
    p = argparse.ArgumentParser(
        prog="weall-node",
        description="Run WeAll Node (HTTPS + PoH onboarding + WebRTC signaling)",
    )
    p.add_argument(
        "--host",
        default=os.environ.get("WEALL_HOST", "0.0.0.0"),
        help="Bind address (default: 0.0.0.0)",
    )
    p.add_argument(
        "--port",
        type=int,
        default=int(os.environ.get("WEALL_PORT", "8443")),
        help="HTTPS port (default: 8443)",
    )
    p.add_argument(
        "--state",
        default=os.environ.get("WEALL_STATE_PATH", "./weall_state.json"),
        help="Path to state JSON",
    )
    p.add_argument(
        "--certfile",
        default=os.environ.get("WEALL_CERTFILE"),
        help="TLS certificate PEM (optional)",
    )
    p.add_argument(
        "--keyfile",
        default=os.environ.get("WEALL_KEYFILE"),
        help="TLS private key PEM (optional)",
    )
    p.add_argument(
        "--cn",
        default=os.environ.get("WEALL_TLS_CN", "weall.local"),
        help="CN for self-signed cert (when generated)",
    )
    p.add_argument(
        "--no-self-signed",
        action="store_true",
        help="Require provided certfile/keyfile; do not generate self-signed",
    )
    return p.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)

    # Ensure the executor uses the chosen state path
    os.environ["WEALL_STATE_PATH"] = args.state

    execu = WeAllExecutor(state_path=args.state)

    # Start HTTPS (self-signed if allowed and no certs provided)
    started = execu.start_network_http(
        host=args.host,
        port=args.port,
        certfile=args.certfile,
        keyfile=args.keyfile,
        generate_self_signed=not args.no_self_signed,
        common_name=args.cn,
    )
    if not started.get("ok"):
        print("Failed to start HTTPS:", started, file=sys.stderr)
        return 2

    host = started["host"]
    port = started["port"]
    print("")
    print("WeAll Node is up ✅")
    print(f"  Peer ID: {execu.state['network'].get('peer_id')}")
    print(f"  HTTPS  : https://{host}:{port}")
    print("  UIs    :")
    print(f"    Panel  (Tier-3 live)  -> https://{host}:{port}/ui/panel")
    print(f"    Tier-2 (async feed)   -> https://{host}:{port}/ui/t2")
    print("")
    print("Press Ctrl+C to stop.")

    # Graceful shutdown
    stop = {"flag": False}

    def _sig(*_):
        if not stop["flag"]:
            stop["flag"] = True
            print("\nShutting down...")

    signal.signal(signal.SIGINT, _sig)
    signal.signal(signal.SIGTERM, _sig)

    try:
        while not stop["flag"]:
            time.sleep(0.5)
    finally:
        execu.stop_network_http()
        print("Stopped. Bye!")


if __name__ == "__main__":
    raise SystemExit(main())
