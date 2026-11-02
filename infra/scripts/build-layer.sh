#!/usr/bin/env bash
# Build the Lambda dependencies layer for the Python backend.
#
# Installs the backend's *runtime* dependencies (from the uv lockfile) into
# infra/layer-build/python/ targeting the Lambda runtime platform
# (manylinux2014 aarch64, cpython 3.12). boto3/botocore are excluded because the
# Lambda Python runtime already provides them.
#
# Run this before `cdk deploy`. `cdk synth` works without it (the layer asset is
# just empty), so CI/offline synth stays green.
#
# Requires: uv (https://astral.sh/uv). No Docker needed.
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
INFRA="$(dirname "$HERE")"
BACKEND="$(dirname "$INFRA")/backend"
OUT="$INFRA/layer-build/python"

echo "Building Lambda dependency layer -> $OUT"
rm -rf "$INFRA/layer-build"
mkdir -p "$OUT"

# Export runtime deps (no dev, no the project itself) to a plain requirements file.
REQ="$(mktemp)"
trap 'rm -f "$REQ"' EXIT
uv export --project "$BACKEND" --no-dev --no-emit-project --no-hashes \
  --format requirements-txt \
  | grep -vE '^(boto3|botocore|s3transfer)([=<>!~ ]|$)' > "$REQ"

echo "Installing into the layer (manylinux2014 aarch64, cp312)..."
uv pip install \
  --target "$OUT" \
  --python-platform aarch64-manylinux2014 \
  --python-version 3.12 \
  --only-binary=:all: \
  --requirement "$REQ"

# Trim bytecode/test bloat. Keep *.dist-info — importlib.metadata needs it.
find "$OUT" -type d -name "__pycache__" -prune -exec rm -rf {} +
find "$OUT" -type d -name "tests" -prune -exec rm -rf {} +

echo "Layer built. Size:"
du -sh "$INFRA/layer-build"
