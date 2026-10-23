"""Join flow: a machine asks the control node to join; trust comes from a single-use token plus its signed card.

Control node (panel):
    tok = issue_token(store)                         # shown once; only sha256(token) is stored
    redeem(store, tok, card, signature, host_pubkey) # called by POST /api/join → node recorded as "pending"
    approve(store, node_id, by="operator")           # or reject(...)

Joining machine (needs root to read its SSH host key):
    sudo python3 -m niyantrak.join https://<control-node>:8771 <token> --pin sha256:<fingerprint>

Rules
- A token is random (256 bits), single-use and expires (default 24 h). The store keeps only its sha256, so a copy of
  the store cannot be used to join.
- The card must verify against the host public key sent with it (ssh-keygen -Y verify, see card.py). An edited card
  or a signature from another key is refused and the token stays usable (a retry after a transmission error is fine).
- A node_id already recorded with a different host key is refused as a possible impersonation, the token is burnt and
  an alert is recorded. The recorded key is never replaced through the join endpoint.
- The store is a JSON file written atomically; it holds no secrets (token hashes, public keys, card hashes, cards).
"""
import argparse
import hashlib
import json
import os
import secrets
import sys
import tempfile
import threading
import time
import http.client
import urllib.parse

from . import card as cardmod
from . import tls as tlsmod
from .paths import state_root

STORE = os.environ.get("NIYANTRAK_JOIN_STORE") or os.path.join(state_root(), "join.json")
DEFAULT_TTL = 86400
HOST_KEY = "/etc/ssh/ssh_host_ed25519_key"
MAX_ALERTS = 500
_LOCK = threading.Lock()


class JoinError(ValueError):
    """Refusal with a reason that is safe to show the joining machine. `code` maps to an HTTP status."""

    def __init__(self, message, code=403):
        super().__init__(message)
        self.code = code


def token_hash(token):
    return hashlib.sha256(str(token).encode()).hexdigest()


def _iso(ts):
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(ts))


def load(store):
    try:
        with open(store) as f:
            d = json.load(f)
    except (OSError, ValueError):
        d = {}
    for k, empty in (("tokens", {}), ("nodes", {}), ("alerts", [])):
        d.setdefault(k, empty)
    return d


def _save(store, d):
    folder = os.path.dirname(os.path.abspath(store))
    os.makedirs(folder, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=folder, prefix=".join-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(d, f, indent=2, sort_keys=True)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, store)
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


def issue_token(store=STORE, ttl=DEFAULT_TTL, auto_approve=False, now=None):
    """Return a new single-use token. The value is returned once and never written anywhere."""
    now = time.time() if now is None else now
    tok = secrets.token_urlsafe(32)
    with _LOCK:
        d = load(store)
        d["tokens"] = {h: t for h, t in d["tokens"].items() if not t.get("used_at") and t["expires"] > now}  # prune
        d["tokens"][token_hash(tok)] = {"issued": now, "expires": now + ttl, "auto_approve": bool(auto_approve),
                                        "used_at": None}
        _save(store, d)
    return tok


def _alert(d, kind, node_id, now, **extra):
    d["alerts"].append({"kind": kind, "node_id": node_id, "at": _iso(now), **extra})
    d["alerts"] = d["alerts"][-MAX_ALERTS:]


def redeem(store, token, card, signature, host_pubkey, now=None):
    """Verify and record a join request. Returns the node record; raises JoinError on any refusal."""
    now = time.time() if now is None else now
    if not isinstance(card, dict) or not str(card.get("node_id", "")).startswith("nyk-"):
        raise JoinError("card has no valid node_id", 400)
    if not isinstance(signature, str) or not isinstance(host_pubkey, str) or not host_pubkey.strip():
        raise JoinError("signature and host public key are required", 400)
    node_id, pub = card["node_id"], " ".join(host_pubkey.split()[:2])  # key type + key; comment dropped
    with _LOCK:
        d = load(store)
        h = token_hash(token)
        t = d["tokens"].get(h)
        if t is None:
            raise JoinError("unknown token")
        if t.get("used_at"):
            raise JoinError("token already used")
        if t["expires"] <= now:
            raise JoinError("token expired")
        if not cardmod.verify(cardmod.card_bytes(card), signature, pub):
            raise JoinError("card signature does not verify against the host key")
        prev = d["nodes"].get(node_id)
        if prev and prev["host_pubkey"] != pub:
            t["used_at"] = now
            _alert(d, "host-key-mismatch", node_id, now, offered_key_sha256=hashlib.sha256(pub.encode()).hexdigest())
            _save(store, d)
            raise JoinError("host key differs from the one recorded for this node (possible impersonation)")
        t["used_at"] = now
        state = "approved" if t.get("auto_approve") else (prev["state"] if prev and prev["state"] == "approved" else "pending")
        rec = {"node_id": node_id, "state": state, "host_pubkey": pub, "card_sha256": cardmod.card_sha256(card),
               "card": card, "requested_at": _iso(now), "token_sha256": h,
               "decided_by": "auto-approve token" if t.get("auto_approve") else (prev or {}).get("decided_by"),
               "decided_at": _iso(now) if t.get("auto_approve") else (prev or {}).get("decided_at")}
        d["nodes"][node_id] = rec
        _save(store, d)
        return rec


def _decide(store, node_id, state, by, now=None):
    now = time.time() if now is None else now
    with _LOCK:
        d = load(store)
        n = d["nodes"].get(node_id)
        if n is None:
            raise JoinError("unknown node", 404)
        n.update(state=state, decided_by=str(by), decided_at=_iso(now))
        _save(store, d)
        return n


def approve(store, node_id, by, now=None):
    return _decide(store, node_id, "approved", by, now)


def reject(store, node_id, by, now=None):
    return _decide(store, node_id, "rejected", by, now)


def list_nodes(store=STORE):
    return load(store)["nodes"]


# ── machine side ──────────────────────────────────────────────────────────────────────────────────────────
def join(panel_url, token, key_path=HOST_KEY, card=None, pin=None, timeout=30):
    """Collect this machine's card, sign it with its host key and ask the control node to join.

    https URLs need `pin` (the join listener's certificate SHA-256, shown in the panel and in the one-liner); the
    certificate is checked before the token leaves this machine. Plain http is accepted only to this machine itself.
    """
    u = urllib.parse.urlsplit(panel_url)
    if u.scheme == "https":
        if not pin:
            raise JoinError("https needs --pin sha256:<fingerprint> (shown in the panel next to the token)", 400)
        try:
            conn = tlsmod.PinnedHTTPSConnection(u.hostname, u.port or 443, pin=pin, timeout=timeout)
        except ValueError as e:
            raise JoinError(str(e), 400) from None
    elif u.scheme == "http" and u.hostname in ("127.0.0.1", "::1", "localhost"):
        conn = http.client.HTTPConnection(u.hostname, u.port or 80, timeout=timeout)
    else:
        raise JoinError("use the https join address with its certificate pin; plain http only works on this machine", 400)
    card = card if card is not None else cardmod.collect()
    with open(key_path + ".pub") as f:
        pub = f.read().strip()
    body = {"token": token, "card": card, "signature": cardmod.sign(cardmod.card_bytes(card), key_path), "host_pubkey": pub}
    try:
        conn.connect()                                   # pinned: raises before anything is sent
        conn.request("POST", "/api/join", body=json.dumps(body), headers={"Content-Type": "application/json"})
        r = conn.getresponse()
        raw = r.read()
    except tlsmod.PinMismatch as e:
        raise JoinError(f"refusing to join: {e.args[0] if e.args else e}") from None
    except (OSError, http.client.HTTPException) as e:
        raise JoinError(f"could not reach the control node: {e}", 502) from None
    finally:
        conn.close()
    try:
        d = json.loads(raw)
    except ValueError:
        d = {"error": raw[:200].decode(errors="replace")}
    if r.status != 200:
        raise JoinError(d.get("error", f"HTTP {r.status}"), r.status)
    return d


def main(argv=None):
    ap = argparse.ArgumentParser(prog="python3 -m niyantrak.join", description="Ask a Niyantrak control node to join.")
    ap.add_argument("panel_url")
    ap.add_argument("token")
    ap.add_argument("--pin", help="sha256:<fingerprint> of the join listener's certificate (shown in the panel)")
    ap.add_argument("--key", default=HOST_KEY, help=f"SSH host private key used to sign the card (default {HOST_KEY})")
    a = ap.parse_args(argv)
    try:
        r = join(a.panel_url, a.token, a.key, pin=a.pin)
    except (JoinError, OSError) as e:
        print(f"join refused: {e}", file=sys.stderr)
        return 1
    print(f"{r['node_id']}: {r['state']}" + (" — an operator approves it in the panel under Fleet." if r["state"] == "pending" else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
