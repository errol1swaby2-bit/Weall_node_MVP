#!/data/data/com.termux/files/usr/bin/bash
# ================================================
# WeAll Node HTTPS Starter
# ================================================
# This script auto-generates self-signed TLS certs
# and launches uvicorn with HTTPS enabled.
# ================================================

set -e

cd "$(dirname "$0")"

CERT="cert.pem"
KEY="key.pem"
PORT=8000

# ---- find local LAN IP ----
LAN_IP=$(ip -4 addr show wlan0 2>/dev/null | grep -oP '(?<=inet\s)\d+(\.\d+){3}' | head -n1)
if [ -z "$LAN_IP" ]; then
  LAN_IP="127.0.0.1"
fi

# ---- generate self-signed cert if missing ----
if [ ! -f "$CERT" ] || [ ! -f "$KEY" ]; then
  echo "🔐 Generating self-signed TLS certificate..."
  openssl req -x509 -newkey rsa:2048 -nodes \
    -keyout "$KEY" -out "$CERT" -days 365 \
    -subj "/CN=$LAN_IP"
  echo "✅ Certificate generated for CN=$LAN_IP"
else
  echo "🔑 Using existing TLS certificate."
fi

# ---- set environment ----
export WEALL_FORCE_HTTPS=1
export UVICORN_CMD="uvicorn weall_node.weall_api:app --host 0.0.0.0 --port $PORT --ssl-keyfile $KEY --ssl-certfile $CERT --reload"

echo
echo "=============================================="
echo "🌐  Starting WeAll Node (HTTPS mode)"
echo "   Address: https://$LAN_IP:$PORT"
echo "=============================================="
echo

# ---- run uvicorn ----
$UVICORN_CMD
