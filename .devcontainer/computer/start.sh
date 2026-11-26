#!/usr/bin/env bash
# Runs every time the codespace starts: launch the tool server and make its port reachable.
# Log: /tmp/computer-start.log
SELF="$(readlink -f "$0")"
exec >>/tmp/computer-start.log 2>&1
echo "=== start $(date -Is) ==="
cd "$(dirname "$SELF")"
# Pick up fixes pushed since this codespace was created, then run the newest version of this script.
if [ -z "${FREE_AI_UPDATED:-}" ]; then
  git -C "$(git rev-parse --show-toplevel)" pull --ff-only -q || echo "git pull skipped"
  FREE_AI_UPDATED=1 exec bash "$SELF"
fi
mkdir -p /workspaces/agent
# Repair anything the first-time setup missed.
python -c "import fastapi, uvicorn, httpx" 2>/dev/null || python -m pip install -q -r requirements.txt
pkill -f "uvicorn server:app" 2>/dev/null || true
nohup setsid python -m uvicorn server:app --host 0.0.0.0 --port 8787 > /tmp/computer.log 2>&1 < /dev/null &
for i in $(seq 1 40); do curl -sf localhost:8787/ping >/dev/null && { echo "server up"; break; }; sleep 1; done
# The app stores your GitHub token as the GH_TOKEN Codespaces secret; it can change port visibility.
for tok in "${GH_TOKEN:-}" "${GITHUB_TOKEN:-}"; do
  [ -z "$tok" ] && continue
  for i in 1 2 3 4 5 6 7 8; do
    if GH_TOKEN="$tok" gh codespace ports visibility 8787:public -c "$CODESPACE_NAME"; then echo "port 8787 is public"; break 2; fi
    sleep 5
  done
done
# Install the browser in the background if first-time setup didn't finish it.
( python -c "from playwright.sync_api import sync_playwright as p; b=p().start().chromium.launch(); b.close()" >/dev/null 2>&1 \
  || python -m playwright install --with-deps chromium ) &
echo "start done"
