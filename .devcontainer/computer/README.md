# Free AI computer

This codespace is the sandboxed Linux computer that Task mode at spencie.me/chat drives.
It is created, started and stopped by the app. You don't need to keep this tab open.

- Server: `server.py` (FastAPI on port 8787, public port, GitHub-token auth: only the codespace owner)
- Files the agent makes live in `/workspaces/agent`
- Logs: `/tmp/computer.log`
- It stops itself after a few idle minutes, and GitHub's idle timeout is a hard cap on top.
