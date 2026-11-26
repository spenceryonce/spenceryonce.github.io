#!/usr/bin/env bash
# Runs once when the codespace is created.
set -euo pipefail
cd "$(dirname "$0")"
python -m pip install --upgrade pip >/dev/null
python -m pip install -r requirements.txt
python -m playwright install --with-deps chromium
sudo apt-get update -y >/dev/null && sudo apt-get install -y --no-install-recommends imagemagick ffmpeg jq zip unzip >/dev/null || true
mkdir -p "${AGENT_HOME:-/workspaces/agent}"
echo "setup done"
