## Roblox account generator /w gametype-1 funcaptcha solver
## twitter.com/h0nde
## 2020-09-07

from funcaptcha import FunCaptchaSession, Proxy, BadGameTypeOrVariant, BannedProxy
from fingerprint import Fingerprint, Window
from threading import Thread, Lock, Event
from queue import Queue, Full as QueueFull
from counter import Counter, IntervalCounter
import itertools
import random
import imageutil
import pickle
import time
import os
import secrets
import exrex
import requests
import ctypes
import yaml
import uuid
import sys
import traceback
import signal
import json

# --- API imports ---------------------------------------------------------
from flask import Flask, request, jsonify, Response

if not os.path.exists("solver-db"):
    os.mkdir("solver-db")
if not os.path.exists("logs"):
    os.mkdir("logs")

## Load variables from config file
with open("config.yaml") as f:
    config = yaml.safe_load(f)
    hash_length = config["solver"]["hash_length"]
    hash_method = imageutil.methods[config["solver"]["hash_method"]]
    masking = config["solver"]["mask"]
    solver_count = config["threads"]["solver"]
    resubmitter_count = config["threads"]["resubmitter"]
    thread_count = config["threads"]["main"]
    user_agent = config["misc"]["user_agent"]

    un_gen = lambda: exrex.getone(config["generator"]["username"], limit=20)
    pw_gen = lambda: exrex.getone(config["generator"]["password"], limit=50)

bheaders = {
    "User-Agent": user_agent,
    "Origin": "https://www.roblox.com",
    "Referer": "https://www.roblox.com/account/signupredir"
}

## counters
created_counter = IntervalCounter()
solver_success_counter = Counter()
solver_failure_counter = Counter()

## solver variables
solved_queue = Queue()
resubmit_queue = Queue()
appear = {}
cache = {}

## Attempt to load database files into memory
try:
    with open("solver-db/appear.p", "rb") as f:
        appear = pickle.load(f)
    with open("solver-db/cache.p", "rb") as f:
        cache = pickle.load(f)
except: pass

# =========================================================================
# LIVE CONSOLE LOGGING SYSTEM (SSE)
# =========================================================================
CONSOLE_LISTENERS = []
CONSOLE_LOCK = Lock()

def log_to_console(msg_type, message):
    """Pushes a log message to all connected SSE clients."""
    ts = time.strftime("%H:%M:%S")
    data = json.dumps({"type": msg_type, "time": ts, "message": message})
    with CONSOLE_LOCK:
        for q in list(CONSOLE_LISTENERS):
            try:
                q.put_nowait(data)
            except QueueFull:
                pass

## Stuff you can easily mess around with
wlock = Lock()
def account_callback(account, source="CLI"):
    print("Created account:", account)
    created_counter.add()
    log_to_console("CREATED", f"Account created: {account.username}")
    with wlock:
        with open("logs/cookies.txt", "a", encoding="UTF-8", errors="ignore") as f:
            f.write("%s\n" % account.cookie)

        with open("logs/combos_cookies.txt", "a", encoding="UTF-8", errors="ignore") as f:
            f.write("%s:%s:%s\n" % (
                account.username,
                account.password,
                account.safe_cookie()
            ))

def gen_username():
    un = ""
    while not un or un.startswith("_") or un.endswith("_") \
        or un.count("_") > 1 or len(un) < 4 or un.isdigit():
        un = un_gen()
    return un

def gen_password():
    return pw_gen()

## Modify proxy class to add support for storing xsrf tokens
class Proxy(Proxy):
    def __init__(self, proxy):
        self.xsrf_token = None
        super().__init__(proxy, "http")

## Load proxies into memory
with open("proxies.txt") as f:
    proxies = list(map(Proxy, f.read().splitlines()))
    proxies = itertools.cycle(proxies)

## Solver functions and workers
def get_identity():
    window = Window("Roblox", "https://www.roblox.com/account/signupredir")
    fp = Fingerprint(
        user_agent=user_agent,
        protochain_hash="5d76839801bc5904a4f12f1731a7b6d1",
        sec_fetch=True,
        content_type_value="application/x-www-form-urlencoded; charset=UTF-8",
        accept_language_value="en-US,en;q=0.9",
        jsbd_gen=lambda w: dict(HL=random.randint(1,5), NCE=True, DT=w.title, NWD="undefined", DA=None, DR=None, DMT=random.randint(1,40), DO=None, DOT=random.randint(30,50)),
        DNT="unknown",
        L="en-US",
        D=24,
        PR=1,
        S="1920,1080",
        AS="1920,1040",
        SS=True,
        LS=True,
        IDB=True,
        B=False,
        ODB=True,
        CPUC="unknown",
        PK="Win32",
        JSF="Arial,Arial Black,Arial Narrow,Book Antiqua,Bookman Old Style,Calibri,Cambria,Cambria Math,Century,Century Gothic,Century Schoolbook,Comic Sans MS,Consolas,Courier,Courier New,Garamond,Georgia,Helvetica,Impact,Lucida Bright,Lucida Calligraphy,Lucida Console,Lucida Fax,Lucida Handwriting,Lucida Sans,Lucida Sans Typewriter,Lucida Sans Unicode,Microsoft Sans Serif,Monotype Corsiva,MS Gothic,MS PGothic,MS Reference Sans Serif,MS Sans Serif,MS Serif,Palatino Linotype,Segoe Print,Segoe Script,Segoe UI,Segoe UI Light,Segoe UI Semibold,Segoe UI Symbol,Tahoma,Times,Times New Roman,Trebuchet MS,Verdana,Wingdings,Wingdings 2,Wingdings 3",
        P="Chrome PDF Plugin,Chrome PDF Viewer,Native Client",
        T="0,false,false",
        H="8",
        SWF=False
    )
    return fp, window

def get_session():
    fp, window = get_identity()
    fcs = FunCaptchaSession(
        public_key="A2A14B1D-1AF3-C791-9BBC-EE33CC7A0A6F",
        service_url="https://roblox-api.arkoselabs.com",
        window=window,
        fingerprint=fp,
        analytics=True,
        whitelisted_types=[1],
        whitelisted_variants=None,
        proxy=next(proxies) if proxies else None
    )
    return fcs

def prepare_image(im, label=None):
    im = imageutil.remove_background(im)
    im = im.crop(im.getbbox())
    if masking:
        im = imageutil.mask(im)
    return im

class SolverDBSaver(Thread):
    interval = 60

    def __init__(self):
        super().__init__()

    def run(self):
        while 1:
            time.sleep(self.interval)
            try:
                ad = pickle.dumps(appear)
                with open("solver-db/appear.p", "wb") as f:
                    f.write(ad)
                cd = pickle.dumps(cache)
                with open("solver-db/cache.p", "wb") as f:
                    f.write(cd)
            except Exception as err:
                print("Save error:", err)

class SolverWorker(Thread):
    def __init__(self):
        super().__init__()

    def get_session(self):
        self.session = get_session()

    def run(self):
        self.get_session()

        while 1:
            try:
                fc = self.session.get_challenge()

                for imdata in fc.images:
                    im = imageutil.to_pil(imdata)
                    mim = prepare_image(im, label="main")
                    mh = imageutil.hash_image(mim, hash_method, hash_length)
                    appear[mh] = 1

                    for rn in range(1, int(360/fc.rotate_degree)):
                        rd = fc.rotate_degree * rn
                        rk = "%s|%.2f" % (mh, rd)
                        rh = cache.get(rk)
                        if not rh:
                            rim = prepare_image(im.rotate(rd*-1), label="rotate")
                            rh = imageutil.hash_image(rim, hash_method, hash_length)
                            cache[rk] = rh
                        if not rh in appear:
                            break

                    solved = fc.check_answer(rd)

                if solved:
                    solved_queue.put(fc)
                    solver_success_counter.add()
                    log_to_console("CAPTCHA", f"Captcha solved: {fc.full_token[:20]}...")
                else:
                    solver_failure_counter.add()
                    log_to_console("FAILED", "Captcha solve failed")

            except (BannedProxy, BadGameTypeOrVariant, Exception) as err:
                self.session.close_conns()
                self.get_session()

## Account creation functions, workers and exceptions
class SignupError(Exception): pass
class CaptchaError(Exception): pass
class CreatedAccount:
    def __init__(self, id, username, password, cookie):
        self.id = id
        self.username = username
        self.password = password
        self.cookie = cookie

    def safe_cookie(self):
        return self.cookie.replace("WARNING:", "WARNING")

    def __repr__(self):
        return self.username

error_assoc = {2: CaptchaError}
def raise_for_error(r):
    d = r.json()
    if not "errors" in d: return
    for err in d["errors"]:
        e = error_assoc.get(err["code"], SignupError)
        raise e("%s (code %d)" % (err["message"], err["code"]))

def create_account(ch):
    username = gen_username()
    password = gen_password()
    
    log_to_console("STARTED", f"Account generation started: {username}")

    def send():
        return requests.post(
            url="https://auth.roblox.com/v2/signup",
            headers={**bheaders, "X-CSRF-TOKEN": ch.proxy.xsrf_token or "-"},
            proxies={"https": "%s:%d" % (ch.proxy.host, ch.proxy.port)},
            timeout=10,
            json=dict(
                username=username,
                password=password,
                gender="Male",
                birthday="2000-01-01",
                isTosAgreementBoxChecked=True,
                captchaToken=ch.full_token,
                captchaProvider="PROVIDER_ARKOSE_LABS"
            )
        )
    r = send()
    if "x-csrf-token" in r.headers:
        ch.proxy.xsrf_token = r.headers["x-csrf-token"]
        r = send()
    raise_for_error(r)
    data = r.json()
    cookie = r.cookies[".ROBLOSECURITY"]
    account = CreatedAccount(data["userId"], username, password, cookie)
    return account

class ResubmitWorker(Thread):
    def __init__(self):
        super().__init__()

    def run(self):
        while 1:
            ch = resubmit_queue.get(True)
            if ch.resubmitted: continue
            try:
                ch.resubmitted = True
                if ch.check_answer(None, bypass=True):
                    solved_queue.put(ch)
            except Exception as err:
                print("Error while attempting to resubmit challenge:", err)

class TitleWorker(Thread):
    interval = 0.1

    def __init__(self):
        super().__init__()

    def run(self):
        while 1:
            time.sleep(self.interval)
            st = solver_success_counter.total+solver_failure_counter.total
            ratio = (solver_success_counter.total/st) * 100 if st else 0
            s = "  |  ".join([
                "Created: %d" % created_counter.total,
                "CPM: %d" % created_counter.cpm(),
                "Solve Ratio: %.2f%% (S:%d,F:%d)" % (ratio, solver_success_counter.total, solver_failure_counter.total)
            ])
            try:
                ctypes.windll.kernel32.SetConsoleTitleW(s)
            except Exception:
                pass

class Worker(Thread):
    def __init__(self):
        super().__init__()

    def run(self):
        while 1:
            ch = solved_queue.get(True)
            try:
                account = create_account(ch)
                resubmit_queue.put(ch)
                account_callback(account, source="CLI")

            except CaptchaError:
                print("Token was rejected by Roblox")
                log_to_console("FAILED", "Token was rejected by Roblox")
            
            except SignupError as err:
                print("Roblox returned error while creating account:", err)
                log_to_console("FAILED", f"Roblox error: {err}")
                resubmit_queue.put(ch)

            except Exception as err:
                print("Unexpected error:", err)
                log_to_console("FAILED", f"Unexpected error: {err}")


# =========================================================================
# API SERVER & WEB CONSOLE
# =========================================================================

API_KEY        = os.environ.get("API_KEY")
CREATE_WORKERS = int(os.environ.get("CREATE_WORKERS", "4"))
JOB_TIMEOUT    = int(os.environ.get("JOB_TIMEOUT", "240"))
MAX_QUEUE      = int(os.environ.get("MAX_QUEUE", "64"))
SOLVE_TIMEOUT  = int(os.environ.get("SOLVE_TIMEOUT", "180"))
API_PORT       = int(os.environ.get("PORT", "5000"))

KEEPALIVE_INTERVAL  = int(os.environ.get("KEEPALIVE_INTERVAL", "60"))
KEEPALIVE_URL       = os.environ.get("KEEPALIVE_URL")
WATCHDOG_INTERVAL   = int(os.environ.get("WATCHDOG_INTERVAL", "30"))
WATCHDOG_MAX_RESTART = int(os.environ.get("WATCHDOG_MAX_RESTART", "10"))

ACCOUNTS      = {}
ACCOUNTS_LOCK = Lock()

def store_account(acct):
    with ACCOUNTS_LOCK:
        ACCOUNTS[acct.id] = acct

def get_account(user_id):
    with ACCOUNTS_LOCK:
        return ACCOUNTS.get(user_id)

class Job:
    __slots__ = ("account", "error", "done", "id")
    def __init__(self):
        self.account = None
        self.error   = None
        self.done    = Event()
        self.id      = uuid.uuid4().hex[:12]

CREATE_QUEUE = Queue(maxsize=MAX_QUEUE)

STATS = dict(created=0, solve_ok=0, solve_fail=0, follow_ok=0, follow_fail=0,
             restarts=0, keepalive_pings=0, keepalive_fails=0)
STATS_LOCK = Lock()

def bump(key, n=1):
    with STATS_LOCK:
        STATS[key] = STATS.get(key, 0) + n

def solve_one_captcha(timeout=SOLVE_TIMEOUT):
    deadline = time.time() + timeout
    session  = get_session()

    while time.time() < deadline:
        try:
            fc = session.get_challenge()
            solved = False
            for imdata in fc.images:
                im   = imageutil.to_pil(imdata)
                mim  = prepare_image(im, label="main")
                mh   = imageutil.hash_image(mim, hash_method, hash_length)
                appear[mh] = 1

                rd = 0.0
                max_steps = int(360 / fc.rotate_degree) if fc.rotate_degree else 0
                for rn in range(1, max_steps):
                    rd = fc.rotate_degree * rn
                    rk = "%s|%.2f" % (mh, rd)
                    rh = cache.get(rk)
                    if not rh:
                        rim = prepare_image(im.rotate(rd * -1), label="rotate")
                        rh  = imageutil.hash_image(rim, hash_method, hash_length)
                        cache[rk] = rh
                    if rh not in appear:
                        break
                solved = bool(fc.check_answer(rd))
                break

            if solved:
                bump("solve_ok")
                log_to_console("CAPTCHA", f"Captcha solved: {fc.full_token[:20]}...")
                return fc
            bump("solve_fail")
            log_to_console("FAILED", "Captcha solve failed")

        except (BannedProxy, BadGameTypeOrVariant):
            session.close_conns()
            session = get_session()
        except Exception as err:
            print("[solver] error:", err)
            session.close_conns()
            session = get_session()

    raise TimeoutError("solver timed out after %ds" % timeout)

def _create_worker_loop():
    while True:
        job = CREATE_QUEUE.get()
        try:
            ch   = solve_one_captcha()
            acct = create_account(ch)
            try:
                ch.check_answer(None, bypass=True)
            except Exception:
                pass
            job.account = acct
            store_account(acct)
            account_callback(acct, source="API")
            bump("created")
        except Exception as err:
            job.error = err
            log_to_console("FAILED", f"API create job failed: {err}")
        finally:
            job.done.set()
            CREATE_QUEUE.task_done()

def resolve_username_to_id(username, timeout=10):
    r = requests.post(
        "https://users.roblox.com/v1/usernames/users",
        json={"usernames": [username], "excludeBannedUsers": True},
        timeout=timeout,
    )
    r.raise_for_status()
    data = r.json().get("data") or []
    if not data:
        raise LookupError("unknown username %r" % username)
    return int(data[0]["id"])

def follow_user(account, target_id, timeout=15):
    s = requests.Session()
    s.cookies[".ROBLOSECURITY"] = account.cookie
    headers = {
        "User-Agent": user_agent,
        "Origin":     "https://www.roblox.com",
        "Referer":    "https://www.roblox.com/",
        "Content-Type": "application/json",
    }
    r = s.post("https://auth.roblox.com/v1/logout",
               headers=headers, timeout=timeout)
    xsrf = r.headers.get("x-csrf-token")
    if not xsrf:
        raise RuntimeError("could not obtain CSRF token (status %d)" % r.status_code)
    headers["X-CSRF-TOKEN"] = xsrf
    r = s.post(
        "https://friends.roblox.com/v1/users/%d/follow" % target_id,
        headers=headers, timeout=timeout,
    )
    if r.status_code >= 400:
        raise RuntimeError("follow failed: %d %s" % (r.status_code, r.text[:200]))
    return True


# =========================================================================
# KEEP-ALIVE / WATCHDOG
# =========================================================================

SHUTDOWN = Event()

def _spawn(name, target, *args):
    t = Thread(target=target, args=args, name=name, daemon=True)
    t.start()
    return t

MANAGED_THREADS = []
MANAGED_LOCK    = Lock()

def register_managed(name, target, *args):
    with MANAGED_LOCK:
        t = _spawn(name, target, *args)
        MANAGED_THREADS.append((name, target, args, t))
        return t

def watchdog_loop():
    while not SHUTDOWN.is_set():
        time.sleep(WATCHDOG_INTERVAL)
        with MANAGED_LOCK:
            for i, (name, target, args, t) in enumerate(MANAGED_THREADS):
                if not t.is_alive():
                    print("[watchdog] restarting dead thread:", name)
                    if STATS.get("restarts", 0) < WATCHDOG_MAX_RESTART:
                        nt = _spawn(name, target, *args)
                        MANAGED_THREADS[i] = (name, target, args, nt)
                        bump("restarts")

def keepalive_loop():
    local_url = "http://127.0.0.1:%d/api/health" % API_PORT
    headers   = {}
    if API_KEY:
        headers["X-API-Key"] = API_KEY

    while not SHUTDOWN.is_set():
        time.sleep(KEEPALIVE_INTERVAL)
        targets = [local_url]
        if KEEPALIVE_URL: targets.append(KEEPALIVE_URL)
        for url in targets:
            try:
                r = requests.get(url, headers=headers, timeout=10)
                if r.status_code < 500: bump("keepalive_pings")
                else: bump("keepalive_fails")
            except Exception:
                bump("keepalive_fails")


# =========================================================================
# Flask App + Routes
# =========================================================================

app = Flask(__name__)

def require_api_key(fn):
    def wrapper(*a, **kw):
        if API_KEY:
            supplied = request.headers.get("X-API-Key") or request.args.get("api_key")
            if supplied != API_KEY:
                return jsonify(error="unauthorized"), 401
        return fn(*a, **kw)
    wrapper.__name__ = fn.__name__
    return wrapper

@app.errorhandler(Exception)
def _on_unhandled(err):
    traceback.print_exc()
    return jsonify(error="internal error: %s" % err), 500

@app.route("/api/health", methods=["GET"])
def api_health():
    return jsonify(
        ok=True,
        accounts=len(ACCOUNTS),
        queue=CREATE_QUEUE.qsize(),
        uptime=int(time.time() - START_TIME),
    )

@app.route("/api/stats", methods=["GET"])
def api_stats():
    with STATS_LOCK: snap = dict(STATS)
    return jsonify(**snap, accounts=len(ACCOUNTS), queue=CREATE_QUEUE.qsize())

@app.route("/api/create", methods=["POST"])
@require_api_key
def api_create():
    body   = request.get_json(silent=True) or {}
    target = body.get("follow")

    job = Job()
    try:
        CREATE_QUEUE.put_nowait(job)
    except QueueFull:
        return jsonify(error="queue full, retry later"), 503

    if not job.done.wait(timeout=JOB_TIMEOUT):
        return jsonify(error="timeout", job_id=job.id), 504

    if job.error:
        return jsonify(error=str(job.error), job_id=job.id), 500

    acct = job.account
    resp = dict(
        job_id   = job.id,
        user_id  = acct.id,
        username = acct.username,
        password = acct.password,
        cookie   = acct.safe_cookie(),
    )

    if target:
        try:
            tid = int(target)
        except (TypeError, ValueError):
            try: tid = resolve_username_to_id(str(target))
            except Exception as e:
                resp["follow_error"] = "lookup failed: %s" % e
                return jsonify(resp)
        try:
            follow_user(acct, tid)
            bump("follow_ok")
            resp["followed"] = tid
            log_to_console("FOLLOWED", f"Account {acct.username} followed user {tid}")
        except Exception as e:
            bump("follow_fail")
            resp["follow_error"] = str(e)
            log_to_console("FAILED", f"Follow failed for {acct.username}: {e}")

    return jsonify(resp)

@app.route("/api/follow", methods=["POST"])
@require_api_key
def api_follow():
    body = request.get_json(silent=True) or {}
    uid  = body.get("user_id")
    tgt  = body.get("target_id") or body.get("target")

    if not uid or not tgt:
        return jsonify(error="user_id and target/target_id required"), 400

    acct = get_account(int(uid))
    if not acct:
        return jsonify(error="unknown user_id %s" % uid), 404

    if isinstance(tgt, str) and not tgt.isdigit():
        try: tid = resolve_username_to_id(tgt)
        except Exception as e: return jsonify(error="lookup failed: %s" % e), 404
    else:
        tid = int(tgt)

    try:
        follow_user(acct, tid)
        bump("follow_ok")
        log_to_console("FOLLOWED", f"Account {acct.username} followed user {tid}")
    except Exception as e:
        bump("follow_fail")
        log_to_console("FAILED", f"Follow failed for {acct.username}: {e}")
        return jsonify(error=str(e)), 502

    return jsonify(ok=True, user_id=int(uid), target_id=tid)

@app.route("/api/account/<int:uid>", methods=["GET"])
@require_api_key
def api_account(uid):
    acct = get_account(uid)
    if not acct: return jsonify(error="not found"), 404
    return jsonify(
        user_id  = acct.id, username = acct.username,
        password = acct.password, cookie = acct.safe_cookie()
    )

# -------------------------------------------------------------------------
# Live Web Console (SSE)
# -------------------------------------------------------------------------
@app.route("/api/console")
def console_page():
    html = """
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <title>Account Generator Console</title>
        <style>
            body { background-color: #1e1e1e; color: #d4d4d4; font-family: 'Consolas', 'Courier New', monospace; margin: 0; padding: 20px; }
            .header { display: flex; justify-content: space-between; border-bottom: 1px solid #333; padding-bottom: 10px; margin-bottom: 10px; color: #fff; }
            .title { color: #4ec9b0; font-weight: bold; }
            .stats { font-size: 0.9em; color: #9cdcfe; }
            #console { height: calc(100vh - 80px); overflow-y: auto; font-size: 14px; line-height: 1.5; }
            .log-line { white-space: pre-wrap; word-wrap: break-word; }
            .time { color: #569cd6; }
            .CREATED { color: #4ec9b0; font-weight: bold; }
            .STARTED { color: #dcdcaa; }
            .CAPTCHA { color: #ce9178; }
            .FAILED  { color: #f48771; font-weight: bold; }
            .FOLLOWED { color: #c586c0; }
        </style>
    </head>
    <body>
        <div class="header">
            <div class="title">Roblox Account Generator // Live Console</div>
            <div class="stats" id="stats">Connecting...</div>
        </div>
        <div id="console"></div>
        
        <script>
            const consoleDiv = document.getElementById('console');
            const statsDiv = document.getElementById('stats');
            const evtSource = new EventSource("/api/console/stream");
            
            evtSource.onmessage = function(e) {
                const data = JSON.parse(e.data);
                const div = document.createElement('div');
                div.className = 'log-line';
                div.innerHTML = `<span class="time">[${data.time}]</span> <span class="${data.type}">[${data.type}]</span> ${data.message}`;
                consoleDiv.appendChild(div);
                consoleDiv.scrollTop = consoleDiv.scrollHeight;
            };

            setInterval(() => {
                fetch('/api/stats').then(r => r.json()).then(d => {
                    statsDiv.innerHTML = `Created: ${d.created} | Solve OK: ${d.solve_ok} | Followed: ${d.follow_ok} | Queue: ${d.queue}`;
                });
            }, 2000);
        </script>
    </body>
    </html>
    """
    return Response(html, mimetype="text/html")

@app.route("/api/console/stream")
def console_stream():
    def event_stream(q):
        yield "data: " + json.dumps({"type": "STARTED", "time": time.strftime("%H:%M:%S"), "message": "Connected to live stream."}) + "\n\n"
        while True:
            try:
                msg = q.get(timeout=20)
                yield f"data: {msg}\n\n"
            except QueueEmpty:
                yield "data: " + json.dumps({"type": "PING", "time": time.strftime("%H:%M:%S"), "message": ""}) + "\n\n"
                
    q = Queue(maxsize=100)
    with CONSOLE_LOCK:
        CONSOLE_LISTENERS.append(q)
        
    def on_close():
        with CONSOLE_LOCK:
            CONSOLE_LISTENERS.remove(q)
            
    resp = Response(event_stream(q), mimetype="text/event-stream")
    resp.headers['Cache-Control'] = 'no-cache'
    resp.headers['X-Accel-Buffering'] = 'no'
    resp.call_on_close(on_close)
    return resp

# Ensure QueueEmpty is imported correctly
from queue import Empty as QueueEmpty

# =========================================================================
# Startup
# =========================================================================

START_TIME = time.time()

def start_api():
    for i in range(CREATE_WORKERS):
        register_managed("create_worker_%d" % i, _create_worker_loop)

    register_managed("watchdog", watchdog_loop)
    register_managed("keepalive", keepalive_loop)

    print("[api] listening on 0.0.0.0:%d (workers=%d, keepalive=%ds)"
          % (API_PORT, CREATE_WORKERS, KEEPALIVE_INTERVAL))
    try:
        app.run(host="0.0.0.0", port=API_PORT, threaded=True, use_reloader=False)
    except Exception as err:
        print("[api] Flask died:", err)

def start_workers():
    def _title():
        while not SHUTDOWN.is_set():
            time.sleep(0.1)
            st = solver_success_counter.total + solver_failure_counter.total
            ratio = (solver_success_counter.total / st) * 100 if st else 0
            s = "  |  ".join([
                "Created: %d" % created_counter.total,
                "CPM: %d" % created_counter.cpm(),
                "Solve Ratio: %.2f%% (S:%d,F:%d)" % (ratio, solver_success_counter.total, solver_failure_counter.total)
            ])
            try: ctypes.windll.kernel32.SetConsoleTitleW(s)
            except Exception: pass

    register_managed("solver_db_saver", SolverDBSaver().run)
    if os.name == "nt": register_managed("title", _title)
    
    for i in range(thread_count): register_managed("worker_%d" % i, Worker().run)
    for i in range(resubmitter_count): register_managed("resubmitter_%d" % i, ResubmitWorker().run)
    for i in range(solver_count): register_managed("solver_%d" % i, SolverWorker().run)

def _install_signal_handlers():
    def _on_sig(sig, frame):
        SHUTDOWN.set()
        sys.exit(0)
    for s in (signal.SIGINT, signal.SIGTERM):
        try: signal.signal(s, _on_sig)
        except Exception: pass

if __name__ == "__main__":
    _install_signal_handlers()
    mode = os.environ.get("MODE", "api").lower()

    if mode == "cli":
        start_workers()
        SHUTDOWN.wait()
    elif mode == "both":
        start_workers()
        start_api()
        SHUTDOWN.wait()
    else:
        start_api()
        SHUTDOWN.wait()
