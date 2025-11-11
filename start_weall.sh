#!/bin/bash
cd ~/Weall_node_MVP || exit 1
echo "[*] Starting IPFS & WeAll Node..."
pkill -f "ipfs daemon" 2>/dev/null || true
nohup ipfs daemon > ipfs.log 2>&1 &
sleep 2
pkill -f "uvicorn .*weall_node.weall_api:app" 2>/dev/null || true
PYTHONUNBUFFERED=1 python3 -m uvicorn weall_node.weall_api:app --host 127.0.0.1 --port 8000 --log-level info
