#!/usr/bin/env bash
# Runs once when the codespace is created. Log: /tmp/computer-setup.log
exec >>/tmp/computer-setup.log 2>&1
echo "=== setup $(date -Is) ==="
cd "$(dirname "$0")"
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python -m playwright install --with-deps chromium || echo "playwright install failed (start.sh retries)"
sudo apt-get update -y && sudo apt-get install -y --no-install-recommends imagemagick ffmpeg jq zip unzip || true
mkdir -p /workspaces/agent
echo "setup done"
