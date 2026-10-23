"""Niyantrak panel (free edition) — a web app for people who never open a terminal. Standard library only.

    niyantrak panel                    # http://127.0.0.1:8770
    niyantrak panel --bind <tailnet-or-LAN-address>   # keep it off the public internet

Screens: Overview · Fleet · Add machine · Try it · (Pro previews) Compliance · AI access · Approvals · Audit.
API: GET /api/node · GET /api/peers · POST /api/discover · POST /api/scan
     Proof: GET /api/proof (latest summary + last 30 runs; 404 until tools/prove.py has run) and GET /proof/<file>,
     read-only files from proof/latest (coverage HTML, junit.xml) — paths are confined to that folder.
     Activity: GET /api/activity?days=7[&k=who|agent|what|where|why|outcome|machine&v=<label>] — the Activity (5W)
     charts from the 5W store (niyantrak/telemetry); {"empty": true, "reason": ...} when the store has no events or
     the optional [telemetry] extra (pyarrow + duckdb) is not installed, so the screen shows sample activity.
     Join: POST /api/join/token · POST /api/join (machine side) · GET /api/nodes · POST /api/nodes/<id>/approve|reject
     Decisions: GET /api/decisions (graph JSON for the Decisions screen; empty state when no store).
     Docs: GET /api/docs (generated pages) · GET /docs/<file> (read-only, confined, no scripts) ·
     POST /api/docs/regenerate (this machine only) — as-built pages from node cards + the join store.
     Pro screens: GET /api/capabilities (which Pro screens are live) · GET|POST /api/pro/* routed to panel plugins
     (niyantrak/plugins.py; entry point group niyantrak.panel_plugins). No plugin installed = previews only.
     Join listener (--join-bind <LAN/tailnet address or ::>, TLS, default port 8771) serves ONLY POST /api/join and a
     public page with its certificate fingerprint, plus GET /join.ps1 (windows/join.ps1, verified by SHA-256 in the
     Windows one-liner); everything else is 404 there. The admin listener stays on loopback.
Free edition: issuing join tokens and approving/rejecting machines is accepted only from this machine (127.0.0.1 or
::1) — the operator is whoever is logged in here. Do not put the panel behind a reverse proxy on the same machine: the
proxy would make every caller look local. (Paid editions decide this with signed-in roles instead.)
Personal data: /api/scan returns placeholders and per-type counts only; nothing is stored except per-type counts
for this session (in memory).
"""
import hashlib
import json
import os
import re
import socket
import threading
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from . import card as cardmod
from . import discovery
from . import docs as docsmod
from . import join as joinmod
from . import plugins as pluginsmod
from . import proof as proofmod
from . import tls as tlsmod
from .cli import PREFIX, detect, preview
from .recognizers import PACKS
from .paths import state_root
from .decisions import graph as dgraph
from .decisions.store import Store as DecisionStore

MAX_TEXT = 20000
WEB = os.path.join(os.path.dirname(__file__), "web")
STATIC = {"app.css": "text/css; charset=utf-8", "app.js": "text/javascript; charset=utf-8"}
SESSION = {"counts": {}}
LOCK = threading.Lock()
STATE_DIR = os.environ.get("NIYANTRAK_STATE") or os.path.join(state_root(), "panel")
JOIN_PORT = 8771
LOCAL_ADDRESSES = frozenset({"127.0.0.1", "::1", "::ffff:127.0.0.1"})
PROOF_DIR = os.environ.get("NIYANTRAK_PROOF_DIR",
                           os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "proof"))
PROOF_TYPES = {".html": "text/html; charset=utf-8", ".css": "text/css; charset=utf-8", ".js": "text/javascript; charset=utf-8",
               ".json": "application/json", ".xml": "application/xml; charset=utf-8", ".txt": "text/plain; charset=utf-8",
               ".png": "image/png", ".svg": "image/svg+xml"}
NO_PROOF = "No proof run yet — run tools/prove.py"
TELEMETRY_DIR = os.environ.get("NIYANTRAK_TELEMETRY") or os.path.join(state_root(), "telemetry")
DOC_TYPES = {".html": "text/html; charset=utf-8", ".md": "text/markdown; charset=utf-8", ".svg": "image/svg+xml",
             ".json": "application/json"}
DOC_CSP = "default-src 'none'; style-src 'unsafe-inline'; img-src 'self'; frame-ancestors 'self'; base-uri 'none'; form-action 'none'"
_PLUGIN_HOST = None          # loaded once on first use when the server has no plugin_host of its own
_PLUGIN_LOCK = threading.Lock()
WINDOWS_JOIN_SCRIPT = os.environ.get("NIYANTRAK_WINDOWS_JOIN",
                                     os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "windows", "join.ps1"))
NODE_ACTION = re.compile(r"^/api/nodes/(nyk-[0-9a-f]{1,64})/(approve|reject)$")


def windows_script():
    """(bytes, sha256 hex) of windows/join.ps1, or (None, None) when this install does not ship it."""
    try:
        with open(WINDOWS_JOIN_SCRIPT, "rb") as f:
            data = f.read()
    except OSError:
        return None, None
    return data, hashlib.sha256(data).hexdigest()


def windows_one_liner(host, port, fingerprint, script_sha256, control_address=None):
    """PowerShell (as Administrator): fetch join.ps1 over the pinned certificate, refuse it unless its SHA-256 matches,
    then run it as a dry run. No token in the line: the script asks for it, so it never lands in PowerShell history."""
    base = f"https://{host}:{port}"
    ctl = f" -ControlAddress {control_address}" if control_address else ""
    return ("$p='" + fingerprint + "';"
            "[Net.ServicePointManager]::SecurityProtocol=[Net.ServicePointManager]::SecurityProtocol -bor 3072;"
            "[Net.ServicePointManager]::ServerCertificateValidationCallback={param($s,$c)"
            "(-join([Security.Cryptography.SHA256]::Create().ComputeHash($c.GetRawCertData())|%{$_.ToString('x2')})) -eq $p};"
            "$f=\"$env:TEMP\\niyantrak-join.ps1\";"
            f"try{{irm {base}/join.ps1 -OutFile $f}}finally{{[Net.ServicePointManager]::ServerCertificateValidationCallback=$null}};"
            f"if((Get-FileHash $f -Algorithm SHA256).Hash -ne '{script_sha256.upper()}'){{Remove-Item $f;throw 'join.ps1 does not match the published SHA-256'}};"
            f"powershell -NoProfile -ExecutionPolicy Bypass -File $f -PanelUrl {base} -Pin sha256:$p{ctl}")


def is_local(addr):
    return addr in LOCAL_ADDRESSES


def node_status():
    root = f"{PREFIX}/var/lib/niyantrak/bootstrap"
    report = f"{root}/report.json"
    c = cardmod.collect()
    base = {"hostname": c["hostname"], "node_id": c["node_id"], "ipv4": c["addresses"]["ipv4"],
            "ipv6": c["addresses"]["ipv6"], "os": f"{c['os']['id']} {c['os']['version']}".strip()}
    if not os.path.isfile(report):
        return {**base, "bootstrapped": False, "checks": []}
    r = json.load(open(report))
    sd = f"{PREFIX}/etc/niyantrak/secret.d"
    checks = [
        ("Audit rules record sensitive changes", os.path.isfile(f"{PREFIX}/etc/audit/rules.d/50-niyantrak.rules")),
        ("Remote login hardened (keys only, no root)", os.path.isfile(f"{PREFIX}/etc/ssh/sshd_config.d/10-niyantrak.conf")),
        ("Secrets folder private", os.path.isdir(sd) and oct(os.stat(sd).st_mode)[-3:] == "700"),
        ("Login status page installed", os.path.isfile(f"{PREFIX}/etc/update-motd.d/10-niyantrak")),
    ]
    return {**base, "bootstrapped": True, "node_id": r.get("node_id") or base["node_id"], "role": r.get("role"),
            "finished": r.get("finished"), "checks": [{"name": n, "ok": ok} for n, ok in checks]}


def activity(tel_dir, query):
    """(status, body) for GET /api/activity. Never raises for an empty, missing or extra-less store."""
    from .telemetry import store as telstore
    qs = urllib.parse.parse_qs(query)
    try:
        days = max(1, min(int((qs.get("days") or ["7"])[0]), telstore.MAX_DAYS))
    except ValueError:
        return 400, {"error": "days must be a whole number"}
    k, v = (qs.get("k") or [None])[0], (qs.get("v") or [None])[0]
    if k is not None and (k not in telstore.FILTER_KEYS or v is None):
        return 400, {"error": f"k must be one of {', '.join(sorted(telstore.FILTER_KEYS))}, with v"}
    if not telstore.available():
        return 200, {"empty": True, "days": days, "reason": "The 5W telemetry store needs the optional extra: "
                                                            "pip install niyantrak[telemetry] (pyarrow + duckdb)."}
    try:
        return 200, telstore.Store(tel_dir).activity(days=days, filter=(k, v) if k else None)
    except telstore.IntegrityError as e:
        return 200, {"empty": True, "days": days, "integrity": "failed", "problems": e.problems[:20],
                     "reason": "The 5W store failed its integrity check (a segment or the manifest was changed). "
                               "Run: niyantrak telemetry verify"}


def plugin_host(server):
    """The server's plugin host (tests set server.plugin_host), else one loaded from entry points / env, once."""
    global _PLUGIN_HOST
    h = getattr(server, "plugin_host", None)
    if h is not None:
        return h
    with _PLUGIN_LOCK:
        if _PLUGIN_HOST is None:
            _PLUGIN_HOST = pluginsmod.load()
        return _PLUGIN_HOST


def load_peers():
    try:
        return json.load(open(discovery.PEERS_FILE))
    except (OSError, ValueError):
        return {}


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):                 # no request logging: bodies may hold personal data
        pass

    def _send(self, code, body, ctype="application/json", headers=None):
        data = body if isinstance(body, bytes) else body.encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        for k, v in (headers or {}).items():
            self.send_header(k, v)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Referrer-Policy", "no-referrer")
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        path = self.path.split("?", 1)[0].split("#", 1)[0]
        if path in ("/", "/index.html"):
            return self._send(200, open(os.path.join(WEB, "index.html"), "rb").read(), "text/html; charset=utf-8")
        if path.startswith("/static/") and path[8:] in STATIC:
            return self._send(200, open(os.path.join(WEB, path[8:]), "rb").read(), STATIC[path[8:]])
        if path == "/api/capabilities":
            return self._send(200, json.dumps(plugin_host(self.server).capabilities()))
        if path.startswith("/api/pro/"):
            return self._pro("GET", path, {})
        if path == "/api/node":
            return self._send(200, json.dumps(node_status()))
        if path == "/api/peers":
            return self._send(200, json.dumps({"peers": load_peers()}))
        if path == "/api/nodes":
            return self._send(200, json.dumps({"nodes": joinmod.list_nodes(self._store())}))
        if path == "/api/activity":
            code, body = activity(getattr(self.server, "telemetry_dir", None) or TELEMETRY_DIR,
                                  self.path.split("?", 1)[1] if "?" in self.path else "")
            return self._send(code, json.dumps(body, default=str))
        if path == "/api/proof":
            d = proofmod.load_proof(self._proof_dir())
            if d is None:
                return self._send(404, json.dumps({"error": NO_PROOF, "empty": True}))
            return self._send(200, json.dumps(d))
        if path.startswith("/proof/"):
            return self._proof_file(path[len("/proof/"):])
        if path == "/api/decisions":
            return self._decisions()
        if path == "/api/docs":
            pages = docsmod.list_pages(self._docs_dir())
            return self._send(200, json.dumps({"pages": pages, "empty": not pages}))
        if path.startswith("/docs/"):
            return self._doc_file(path[len("/docs/"):])
        if path == "/api/join/info":
            j = getattr(self.server, "join_info", None)
            return self._send(200, json.dumps({"enabled": bool(j), "fingerprint": j["fingerprint"] if j else None,
                                               "port": j["port"] if j else None}))
        return self._send(404, json.dumps({"error": "not found"}))

    def _pro(self, method, path, body):
        """Hand /api/pro/* to the plugin host. Mutations only from this machine in the free host; the plugin checks
        its own sign-in and roles. Plugin failures come back as a 500 with degraded=true; the panel keeps running."""
        ctx = pluginsmod.RequestContext(
            method=method, path=path, body=body if isinstance(body, dict) else {},
            query={k: v[-1] for k, v in urllib.parse.parse_qs(self.path.split("?", 1)[1] if "?" in self.path else "").items()},
            headers={k.lower(): v for k, v in self.headers.items()}, client=self.client_address[0],
            local=is_local(self.client_address[0]))
        if ctx.mutating and self._refuse_remote():
            return None
        code, out, headers = plugin_host(self.server).dispatch(ctx)
        return self._send(code, json.dumps(out, default=str), headers=headers)

    def _proof_dir(self):
        return getattr(self.server, "proof_dir", None) or PROOF_DIR

    def _proof_file(self, rel):
        """Read-only files from proof/latest; anything outside it (.., absolute, symlinks out) is a 404."""
        full = proofmod.safe_path(os.path.join(self._proof_dir(), "latest"), urllib.parse.unquote(rel))
        ctype = PROOF_TYPES.get(os.path.splitext(full or "")[1].lower())
        if not full or not ctype:
            return self._send(404, json.dumps({"error": "not found"}))
        with open(full, "rb") as f:
            return self._send(200, f.read(), ctype)

    def _decisions(self):
        store = DecisionStore(getattr(self.server, "decisions_root", None))
        try:
            g = dgraph.export_graph(dgraph.derive(store.events()))
        except (OSError, ValueError, RuntimeError) as e:
            return self._send(503, json.dumps({"error": f"Decision store could not be read: {e}", "empty": True}))
        return self._send(200, json.dumps(g))

    def _docs_dir(self):
        return getattr(self.server, "docs_dir", None) or docsmod.default_dir()

    def _doc_file(self, rel):
        """Generated documents, read-only; anything outside the docs folder is a 404. No scripts can run in them."""
        full = proofmod.safe_path(self._docs_dir(), urllib.parse.unquote(rel))
        ctype = DOC_TYPES.get(os.path.splitext(full or "")[1].lower())
        if not full or not ctype:
            return self._send(404, json.dumps({"error": "not found"}))
        with open(full, "rb") as f:
            return self._send(200, f.read(), ctype, {"Content-Security-Policy": DOC_CSP})

    def _regenerate_docs(self):
        if self._refuse_remote():
            return None
        st = node_status()
        local = {"card": cardmod.collect(), "checks": st.get("checks") or []}
        try:
            changed = docsmod.generate(self._docs_dir(), self._store(), local=local)
        except (OSError, ValueError) as e:
            return self._send(500, json.dumps({"error": f"Documents were not written: {e}"}))
        pages = docsmod.list_pages(self._docs_dir())
        return self._send(200, json.dumps({"pages": pages, "empty": not pages, "changed": changed}))

    def _store(self):
        return getattr(self.server, "join_store", None) or joinmod.STORE

    def _refuse_remote(self):
        """True (and a 403 sent) when the caller is not on this machine; see the module note on editions."""
        if is_local(self.client_address[0]):
            return False
        self._send(403, json.dumps({"error": "In the free edition this is done only on this machine "
                                             "(open the panel at http://127.0.0.1). Paid editions use roles."}))
        return True

    def _join_routes(self, path, req):
        if path == "/api/join/token":
            if self._refuse_remote():
                return None
            try:
                ttl = max(60, min(int(req.get("ttl") or joinmod.DEFAULT_TTL), 7 * 86400))   # 1 minute .. 7 days
            except (TypeError, ValueError):
                return self._send(400, json.dumps({"error": "ttl must be seconds"}))
            tok = joinmod.issue_token(self._store(), ttl=ttl, auto_approve=bool(req.get("auto_approve")))
            body = {"token": tok, "ttl": ttl, "expires": joinmod._iso(time.time() + ttl), "commands": {}}
            j = getattr(self.server, "join_info", None)
            if j:
                pin = f"--pin sha256:{j['fingerprint']}"
                cmd = lambda host: f"sudo python3 -m niyantrak.join https://{host}:{j['port']} {tok} {pin}"
                # by name needs mDNS on the joining machine (Linux: avahi; Windows answers .local over IPv6);
                # by address works anywhere the join listener is reachable (LAN or tailnet)
                body["commands"] = {"mdns": cmd(f"{socket.gethostname()}.local")}
                if j.get("address"):
                    body["commands"]["address"] = cmd(f"[{j['address']}]" if ":" in j["address"] else j["address"])
                body["fingerprint"] = j["fingerprint"]
                _, wsha = windows_script()
                if wsha:
                    whost = (f"[{j['address']}]" if ":" in j["address"] else j["address"]) if j.get("address") \
                        else f"{socket.gethostname()}.local"
                    body["commands"]["windows"] = windows_one_liner(whost, j["port"], j["fingerprint"], wsha, j.get("address"))
                    body["windows_script_sha256"] = wsha
            else:
                body["note"] = ("Other machines cannot reach this panel yet: start it with "
                                "--join-bind <LAN or tailnet address> to open the join listener.")
            return self._send(200, json.dumps(body))
        if path == "/api/join":
            try:
                rec = joinmod.redeem(self._store(), str(req.get("token", "")), req.get("card"),
                                     req.get("signature"), req.get("host_pubkey"))
            except joinmod.JoinError as e:
                return self._send(e.code, json.dumps({"error": str(e)}))
            return self._send(200, json.dumps({"node_id": rec["node_id"], "state": rec["state"],
                                               "card_sha256": rec["card_sha256"]}))
        m = NODE_ACTION.match(path)
        if m:
            if self._refuse_remote():
                return None
            fn = joinmod.approve if m.group(2) == "approve" else joinmod.reject
            try:
                n = fn(self._store(), m.group(1), by="operator@localhost")
            except joinmod.JoinError as e:
                return self._send(e.code, json.dumps({"error": str(e)}))
            return self._send(200, json.dumps({"node_id": n["node_id"], "state": n["state"]}))
        return False

    def _body(self):
        n = int(self.headers.get("Content-Length") or 0)
        if n > MAX_TEXT * 4:
            raise ValueError("too long")
        return json.loads(self.rfile.read(n) or b"{}")

    def do_POST(self):
        path = self.path.split("?", 1)[0]
        try:
            req = self._body()
        except ValueError:
            return self._send(400, json.dumps({"error": "bad request"}))
        if path.startswith(("/api/join", "/api/nodes/")):
            if not isinstance(req, dict):
                return self._send(400, json.dumps({"error": "bad request"}))
            if self._join_routes(path, req) is not False:
                return
        if path.startswith("/api/pro/"):
            return self._pro("POST", path, req)
        if path == "/api/docs/regenerate":
            return self._regenerate_docs()
        if path == "/api/scan":
            text = str(req.get("text", ""))[:MAX_TEXT]
            packs = [p for p in req.get("packs", list(PACKS)) if p in PACKS] or list(PACKS)
            masked, counts = preview(text, detect(text, packs))
            with LOCK:
                for k, v in counts.items():
                    SESSION["counts"][k] = SESSION["counts"].get(k, 0) + v
                session_counts = dict(SESSION["counts"])
            return self._send(200, json.dumps({"masked": masked, "counts": counts, "session_counts": session_counts}))
        if path == "/api/discover":
            try:
                import zeroconf  # noqa: F401
            except ImportError:
                return self._send(200, json.dumps({"peers": load_peers(),
                                                   "message": "Discovery needs the zeroconf package on this machine (pip install zeroconf)."}))
            try:
                peers = discovery.browse(5)
            except (OSError, SystemExit) as e:
                return self._send(200, json.dumps({"peers": load_peers(), "message": f"Discovery could not run: {e}"}))
            return self._send(200, json.dumps({"peers": peers, "message": f"Found {len(peers)} machine(s)."}))
        return self._send(404, json.dumps({"error": "not found"}))


class JoinHandler(Handler):
    """The only thing other machines can reach: POST /api/join, a public fingerprint page and the Windows join script
    (GET /join.ps1, public, checked by its SHA-256 in the one-liner). Everything else 404."""
    timeout = 30

    def do_GET(self):
        path = self.path.split("?", 1)[0]
        if path == "/join.ps1":
            data, _ = windows_script()
            if data is None:
                return self._send(404, json.dumps({"error": "not found"}))
            return self._send(200, data, "text/plain; charset=utf-8")
        if path in ("/", "/fingerprint"):
            fp = self.server.join_info["fingerprint"]
            return self._send(200, f"Niyantrak join endpoint.\nCertificate SHA-256: sha256:{fp}\n"
                                   "Compare this with the fingerprint shown in the panel before joining.\n",
                              "text/plain; charset=utf-8")
        return self._send(404, json.dumps({"error": "not found"}))

    def do_POST(self):
        try:
            req = self._body()                   # read first: replying with unread data resets the connection
        except ValueError:
            return self._send(400, json.dumps({"error": "bad request"}))
        if self.path.split("?", 1)[0] != "/api/join":
            return self._send(404, json.dumps({"error": "not found"}))
        if not isinstance(req, dict):
            return self._send(400, json.dumps({"error": "bad request"}))
        return self._join_routes("/api/join", req)


class TLSJoinServer(ThreadingHTTPServer):
    """TLS handshake per connection in its worker thread, so a slow or plain-HTTP client cannot stall accept()."""
    daemon_threads = True

    def __init__(self, addr, handler, ssl_ctx):
        self.address_family = socket.AF_INET6 if ":" in addr[0] else socket.AF_INET
        self.ssl_ctx = ssl_ctx
        super().__init__(addr, handler)

    def finish_request(self, request, client_address):
        request.settimeout(JoinHandler.timeout)
        try:
            request = self.ssl_ctx.wrap_socket(request, server_side=True)
        except (OSError, ValueError):            # plain HTTP, scanners, timeouts: drop the connection
            request.close()
            return
        super().finish_request(request, client_address)


def _join_address(join_bind):
    if join_bind not in ("", "0.0.0.0", "::"):
        return join_bind
    a = cardmod.collect()["addresses"]
    return next(iter(a["ipv4"] + [x for x in a["ipv6"] if not x.startswith("fe80")]), None)


def make_servers(bind="127.0.0.1", port=8770, join_bind=None, join_port=JOIN_PORT, state_dir=None, store=None):
    """Admin server (everything, loopback) and, with join_bind, the TLS join-only server. Not started."""
    admin = ThreadingHTTPServer((bind, port), Handler)
    admin.join_store = store
    if not join_bind:
        return admin, None
    cert, key = tlsmod.ensure_cert(state_dir or STATE_DIR)
    js = TLSJoinServer((join_bind, join_port), JoinHandler, tlsmod.server_context(cert, key))
    js.join_store = store
    info = {"fingerprint": tlsmod.fingerprint(cert), "port": js.server_address[1], "address": _join_address(join_bind)}
    admin.join_info = js.join_info = info
    admin.fingerprint = js.fingerprint = info["fingerprint"]
    return admin, js


def serve(bind="127.0.0.1", port=8770, join_bind=None, join_port=JOIN_PORT):
    admin, js = make_servers(bind, port, join_bind, join_port)
    print(f"Niyantrak panel: http://{bind}:{port}/  (host {socket.gethostname()})")
    if js:
        print(f"Join listener: https://{join_bind}:{js.server_address[1]}/  certificate sha256:{js.fingerprint}")
        threading.Thread(target=js.serve_forever, daemon=True).start()
    admin.serve_forever()
