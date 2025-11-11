#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from weall_node.weall_executor import run_server, STATE_FILE

if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="0.0.0.0")
    ap.add_argument("--port", type=int, default=8000)
    ap.add_argument("--state", default=STATE_FILE)
    args = ap.parse_args()
    run_server(args.host, args.port, args.state)
