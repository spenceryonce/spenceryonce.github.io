#!/usr/bin/env bash
# Runs every time the codespace starts: launch the server and make its port reachable.
cd "$(dirname "$0")"
mkdir -p /workspaces/agent
pkill -f "uvicorn server:app" 2>/dev/null || true
nohup setsid python -m uvicorn server:app --host 0.0.0.0 --port 8787 > /tmp/computer.log 2>&1 < /dev/null &
for i in $(seq 1 30); do curl -sf localhost:8787/ping >/dev/null && break; sleep 1; done
for i in 1 2 3 4 5 6; do
  gh codespace ports visibility 8787:public -c "$CODESPACE_NAME" && break
  sleep 5
done
echo "computer started"
