#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."

OUTDIR="weall_node/weall_runtime/proto"
mkdir -p "$OUTDIR"

# Generate Python protobuf classes (no grpc)
protoc -I protos \
  --python_out="$OUTDIR" \
  protos/weall/v1/common.proto \
  protos/weall/v1/events.proto \
  protos/weall/v1/tx.proto \
  protos/weall/v1/receipt.proto \
  protos/weall/v1/block.proto

# Ensure Python packages exist for imports
touch "$OUTDIR/__init__.py"
mkdir -p "$OUTDIR/weall" "$OUTDIR/weall/v1"
touch "$OUTDIR/weall/__init__.py" "$OUTDIR/weall/v1/__init__.py"

echo "✅ Protos generated into $OUTDIR"
