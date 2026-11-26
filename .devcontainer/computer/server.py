"""Free AI computer: the tool server that Task mode at spencie.me/chat talks to.

Runs inside a GitHub Codespace. Every request must carry the codespace owner's
GitHub token (Authorization: Bearer ...). The server checks it against the
GitHub API and only lets the owner in. It also stops its own codespace when it
has been idle for a while, so a forgotten session can't keep running.
"""
import asyncio, base64, hashlib, mimetypes, os, shlex, subprocess, threading, time
from pathlib import Path
from urllib.parse import quote

import httpx
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse

HOME = Path(os.environ.get("AGENT_HOME", "/workspaces/agent")).resolve()
HOME.mkdir(parents=True, exist_ok=True)
OWNER = (os.environ.get("GITHUB_USER") or "").lower()
CODESPACE = os.environ.get("CODESPACE_NAME", "")
ORIGINS = os.environ.get("ALLOWED_ORIGINS", "https://spencie.me,https://spenceryonce.github.io,http://localhost:8000").split(",")
STARTED = time.time()
MAX_OUT = 20000

state = {"last": time.time(), "inflight": 0, "idle_min": 10.0, "max_min": 120.0, "token": None, "stopping": False}
_auth_cache: dict[str, float] = {}

app = FastAPI(title="Free AI computer")
app.add_middleware(CORSMiddleware, allow_origins=ORIGINS, allow_methods=["*"], allow_headers=["*"], max_age=600)


# ---------- auth ----------
async def check_token(token: str) -> bool:
    h = hashlib.sha256(token.encode()).hexdigest()
    if _auth_cache.get(h, 0) > time.time():
        return True
    async with httpx.AsyncClient(timeout=10) as c:
        r = await c.get("https://api.github.com/user", headers={"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"})
    if r.status_code != 200:
        return False
    login = (r.json().get("login") or "").lower()
    if OWNER and login != OWNER:
        return False
    _auth_cache[h] = time.time() + 600
    return True


@app.middleware("http")
async def guard(request: Request, call_next):
    if request.method == "OPTIONS" or request.url.path == "/ping":
        return await call_next(request)
    auth = request.headers.get("authorization", "")
    token = auth[7:] if auth.lower().startswith("bearer ") else request.query_params.get("token", "")
    if not token or not await check_token(token):
        return JSONResponse({"error": "unauthorized"}, status_code=401, headers={"Access-Control-Allow-Origin": request.headers.get("origin", "*")})
    state["token"] = token
    state["last"] = time.time()
    state["inflight"] += 1
    try:
        return await call_next(request)
    finally:
        state["inflight"] -= 1
        state["last"] = time.time()


def safe_path(p: str) -> Path:
    q = (HOME / (p or ".")).resolve() if not str(p).startswith("/") else Path(p).resolve()
    return q


def clip(s: str, n: int = MAX_OUT) -> str:
    return s if len(s) <= n else s[: n // 2] + f"\n…[{len(s) - n} characters cut]…\n" + s[-n // 2 :]


# ---------- self-stop watchdog ----------
def stop_self(reason: str):
    if state["stopping"] or not CODESPACE or not state["token"]:
        return
    state["stopping"] = True
    print(f"stopping codespace: {reason}", flush=True)
    try:
        httpx.post(f"https://api.github.com/user/codespaces/{CODESPACE}/stop",
                   headers={"Authorization": f"Bearer {state['token']}", "Accept": "application/vnd.github+json"}, timeout=20)
    except Exception as e:  # GitHub's own idle timeout is the backstop
        print("self-stop failed:", e, flush=True)
        state["stopping"] = False


def watchdog():
    while True:
        time.sleep(30)
        idle = (time.time() - state["last"]) / 60
        up = (time.time() - STARTED) / 60
        if state["inflight"] == 0 and idle >= state["idle_min"] and up > 3:
            stop_self(f"idle {idle:.1f} min")
        elif up >= state["max_min"]:
            stop_self(f"session cap {state['max_min']} min")


threading.Thread(target=watchdog, daemon=True).start()


# ---------- basics ----------
@app.get("/ping")
async def ping():
    return {"ok": True}


@app.get("/health")
async def health():
    return {"ok": True, "owner": OWNER, "codespace": CODESPACE, "home": str(HOME),
            "uptime_s": int(time.time() - STARTED), "idle_min": state["idle_min"], "max_min": state["max_min"]}


@app.post("/config")
async def config(body: dict):
    if "idle_min" in body:
        state["idle_min"] = max(2.0, min(240.0, float(body["idle_min"])))
    if "max_min" in body:
        state["max_min"] = max(5.0, min(240.0, float(body["max_min"])))
    return {"idle_min": state["idle_min"], "max_min": state["max_min"]}


@app.post("/stop")
async def stop():
    threading.Thread(target=stop_self, args=("requested by app",), daemon=True).start()
    return {"stopping": True}


# ---------- shell & files ----------
@app.post("/run")
async def run(body: dict):
    cmd = body.get("command") or ""
    timeout = max(1, min(int(body.get("timeout") or 120), 900))
    cwd = safe_path(body.get("cwd") or ".")
    t0 = time.time()

    def go():
        try:
            p = subprocess.run(["bash", "-lc", cmd], cwd=cwd, capture_output=True, text=True, timeout=timeout,
                               env={**os.environ, "HOME": os.environ.get("HOME", "/home/vscode"), "TERM": "dumb"})
            return p.returncode, p.stdout, p.stderr, False
        except subprocess.TimeoutExpired as e:
            return -1, (e.stdout or b"").decode() if isinstance(e.stdout, bytes) else (e.stdout or ""), f"timed out after {timeout}s", True

    code, out, err, to = await asyncio.to_thread(go)
    return {"exit_code": code, "stdout": clip(out), "stderr": clip(err, 6000), "timed_out": to, "seconds": round(time.time() - t0, 1)}


@app.post("/write")
async def write(body: dict):
    p = safe_path(body["path"])
    p.parent.mkdir(parents=True, exist_ok=True)
    if body.get("base64"):
        p.write_bytes(base64.b64decode(body["base64"]))
    else:
        p.write_text(body.get("content", ""))
    return {"path": str(p), "bytes": p.stat().st_size}


@app.post("/read")
async def read(body: dict):
    p = safe_path(body["path"])
    if not p.exists():
        raise HTTPException(404, f"{p} does not exist")
    if p.is_dir():
        raise HTTPException(400, f"{p} is a folder")
    data = p.read_bytes()
    try:
        return {"path": str(p), "content": clip(data.decode()), "bytes": len(data)}
    except UnicodeDecodeError:
        return {"path": str(p), "binary": True, "bytes": len(data), "mime": mimetypes.guess_type(p.name)[0]}


@app.get("/ls")
async def ls(path: str = "."):
    p = safe_path(path)
    if not p.exists():
        raise HTTPException(404, f"{p} does not exist")
    items = []
    for c in sorted(p.iterdir(), key=lambda c: (not c.is_dir(), c.name.lower()))[:500]:
        st = c.stat()
        items.append({"name": c.name, "dir": c.is_dir(), "bytes": st.st_size, "modified": int(st.st_mtime)})
    return {"path": str(p), "items": items}


@app.get("/download")
async def download(path: str):
    p = safe_path(path)
    if not p.is_file():
        raise HTTPException(404, "not a file")
    return FileResponse(p, filename=p.name, media_type=mimetypes.guess_type(p.name)[0] or "application/octet-stream")


# ---------- web search ----------
@app.post("/search")
async def search(body: dict):
    q = body.get("query") or ""
    n = max(1, min(int(body.get("max_results") or 8), 20))

    def go():
        from ddgs import DDGS
        with DDGS() as d:
            return list(d.text(q, max_results=n))

    try:
        rows = await asyncio.to_thread(go)
    except Exception as e:
        raise HTTPException(502, f"search failed: {e}")
    return {"query": q, "results": [{"title": r.get("title"), "url": r.get("href") or r.get("url"), "snippet": r.get("body")} for r in rows]}


# ---------- browser (one persistent Chromium tab) ----------
_pw = {"pw": None, "browser": None, "page": None}
_browser_lock = asyncio.Lock()


async def page():
    if _pw["page"] and not _pw["page"].is_closed():
        return _pw["page"]
    from playwright.async_api import async_playwright
    if not _pw["pw"]:
        _pw["pw"] = await async_playwright().start()
    if not _pw["browser"] or not _pw["browser"].is_connected():
        _pw["browser"] = await _pw["pw"].chromium.launch(args=["--no-sandbox"])
    ctx = await _pw["browser"].new_context(viewport={"width": 1280, "height": 860}, accept_downloads=True,
                                           user_agent="Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0 Safari/537.36")
    _pw["page"] = await ctx.new_page()
    return _pw["page"]


@app.post("/browser")
async def browser(body: dict):
    action = body.get("action", "read")
    async with _browser_lock:
        pg = await page()
        try:
            if action == "goto":
                url = body.get("url", "")
                if not url.startswith(("http://", "https://", "file://")):
                    url = "https://" + url
                await pg.goto(url, wait_until="domcontentloaded", timeout=45000)
                try:
                    await pg.wait_for_load_state("networkidle", timeout=6000)
                except Exception:
                    pass
            elif action == "click":
                if body.get("selector"):
                    await pg.click(body["selector"], timeout=10000)
                else:
                    await pg.get_by_text(body.get("text", ""), exact=False).first.click(timeout=10000)
                await pg.wait_for_timeout(1200)
            elif action == "type":
                sel = body.get("selector") or "input:visible, textarea:visible"
                await pg.locator(sel).first.fill(body.get("text", ""), timeout=10000)
                if body.get("submit"):
                    await pg.keyboard.press("Enter")
                    await pg.wait_for_timeout(1500)
            elif action == "press":
                await pg.keyboard.press(body.get("key", "Enter"))
                await pg.wait_for_timeout(800)
            elif action == "scroll":
                await pg.mouse.wheel(0, int(body.get("amount") or 800))
                await pg.wait_for_timeout(500)
            elif action == "back":
                await pg.go_back(timeout=20000)
            elif action != "read":
                raise HTTPException(400, f"unknown action {action}")
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(502, f"browser {action} failed: {str(e)[:300]}")
        text = await pg.evaluate("() => document.body ? document.body.innerText : ''")
        links = await pg.evaluate("""() => Array.from(document.querySelectorAll('a[href]')).slice(0,60)
            .map(a => ({text:(a.innerText||'').trim().slice(0,80), href:a.href})).filter(l => l.text)""")
        shot = await pg.screenshot(type="jpeg", quality=55)
        return {"url": pg.url, "title": await pg.title(), "text": clip(text, 12000), "links": links,
                "screenshot": "data:image/jpeg;base64," + base64.b64encode(shot).decode()}


# ---------- images ----------
@app.post("/image")
async def image(body: dict):
    prompt = body.get("prompt") or ""
    p = safe_path(body.get("path") or f"images/{int(time.time())}.jpg")
    p.parent.mkdir(parents=True, exist_ok=True)
    w, h = int(body.get("width") or 1024), int(body.get("height") or 1024)
    url = f"https://image.pollinations.ai/prompt/{quote(prompt)}?width={w}&height={h}&nologo=true&seed={int(time.time())}"
    async with httpx.AsyncClient(timeout=120, follow_redirects=True) as c:
        r = await c.get(url)
    if r.status_code != 200 or not r.headers.get("content-type", "").startswith("image"):
        raise HTTPException(502, f"image service returned {r.status_code}")
    p.write_bytes(r.content)
    return {"path": str(p), "bytes": len(r.content)}
