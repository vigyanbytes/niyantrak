"""Join flow: single-use tokens + signed node cards; operator approval; impersonation alerts; panel API; client."""
import json
import shutil
import subprocess
import threading
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer

import pytest

from niyantrak import card as C
from niyantrak import join as J
from niyantrak import panel as P

pytestmark = pytest.mark.skipif(not shutil.which("ssh-keygen"), reason="ssh-keygen missing")


def keypair(tmp_path, name):
    k = tmp_path / name
    subprocess.run(["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-f", str(k)], check=True)
    return str(k), (tmp_path / f"{name}.pub").read_text()


def keyline(pub):
    """Stored form of a public key: type + key, comment (user@host) dropped."""
    return " ".join(pub.split()[:2])


def sample_card(node="nyk-0123456789ab"):
    return {"card_version": 1, "node_id": node, "hostname": "lab-1", "role": "node",
            "os": {"id": "ubuntu", "version": "24.04", "kernel": "6.8", "arch": "x86_64"}, "cpu": {"cores": 8},
            "memory_gb": 15.6, "gpu": [], "addresses": {"ipv4": ["192.0.2.12"], "ipv6": ["fe80::1%eth0"]}}


def signed(tmp_path, name="host", card=None):
    priv, pub = keypair(tmp_path, name)
    c = card or sample_card()
    return c, C.sign(C.card_bytes(c), priv), pub


@pytest.fixture
def store(tmp_path):
    return str(tmp_path / "state" / "join.json")


# ── join.py ───────────────────────────────────────────────────────────────────────────────────────────────
def test_happy_path_pending_then_approved(tmp_path, store):
    tok = J.issue_token(store)
    c, sig, pub = signed(tmp_path)
    rec = J.redeem(store, tok, c, sig, pub)
    assert rec["state"] == "pending" and rec["node_id"] == c["node_id"]
    assert rec["card_sha256"] == C.card_sha256(c) and rec["host_pubkey"] == keyline(pub)
    J.approve(store, c["node_id"], by="operator")
    n = J.list_nodes(store)[c["node_id"]]
    assert n["state"] == "approved" and n["decided_by"] == "operator"


def test_auto_approve_token(tmp_path, store):
    tok = J.issue_token(store, auto_approve=True)
    c, sig, pub = signed(tmp_path)
    assert J.redeem(store, tok, c, sig, pub)["state"] == "approved"


def test_replay_refused(tmp_path, store):
    tok = J.issue_token(store)
    c, sig, pub = signed(tmp_path)
    J.redeem(store, tok, c, sig, pub)
    with pytest.raises(J.JoinError, match="used"):
        J.redeem(store, tok, c, sig, pub)


def test_unknown_token_refused(tmp_path, store):
    J.issue_token(store)
    c, sig, pub = signed(tmp_path)
    with pytest.raises(J.JoinError, match="unknown"):
        J.redeem(store, "not-a-real-token", c, sig, pub)


def test_expired_token_refused(tmp_path, store):
    tok = J.issue_token(store, ttl=60, now=1000.0)
    c, sig, pub = signed(tmp_path)
    with pytest.raises(J.JoinError, match="expired"):
        J.redeem(store, tok, c, sig, pub, now=1061.0)


def test_edited_card_refused(tmp_path, store):
    tok = J.issue_token(store)
    c, sig, pub = signed(tmp_path)
    c["memory_gb"] = 256
    with pytest.raises(J.JoinError, match="signature"):
        J.redeem(store, tok, c, sig, pub)
    assert J.list_nodes(store) == {}


def test_wrong_key_refused(tmp_path, store):
    tok = J.issue_token(store)
    c, sig, _ = signed(tmp_path)
    _, other_pub = keypair(tmp_path, "other")
    with pytest.raises(J.JoinError, match="signature"):
        J.redeem(store, tok, c, sig, other_pub)


def test_impersonation_refused_and_alerted(tmp_path, store):
    c, sig, pub = signed(tmp_path, "host")
    J.redeem(store, J.issue_token(store), c, sig, pub)
    c2, sig2, pub2 = signed(tmp_path, "imposter", card=sample_card())   # same node_id, different host key
    with pytest.raises(J.JoinError, match="host key"):
        J.redeem(store, J.issue_token(store), c2, sig2, pub2)
    n = J.list_nodes(store)[c["node_id"]]
    assert n["host_pubkey"] == keyline(pub)                               # original key kept
    alerts = J.load(store)["alerts"]
    assert alerts and alerts[-1]["kind"] == "host-key-mismatch" and alerts[-1]["node_id"] == c["node_id"]


def test_same_key_rejoin_allowed(tmp_path, store):
    priv, pub = keypair(tmp_path, "host")
    c = sample_card()
    J.redeem(store, J.issue_token(store), c, C.sign(C.card_bytes(c), priv), pub)
    J.approve(store, c["node_id"], by="operator")
    c["memory_gb"] = 31.2                                                # new RAM, same machine
    rec = J.redeem(store, J.issue_token(store), c, C.sign(C.card_bytes(c), priv), pub)
    assert rec["card_sha256"] == C.card_sha256(c)


def test_reject_and_unknown_node(tmp_path, store):
    c, sig, pub = signed(tmp_path)
    J.redeem(store, J.issue_token(store), c, sig, pub)
    J.reject(store, c["node_id"], by="operator")
    assert J.list_nodes(store)[c["node_id"]]["state"] == "rejected"
    with pytest.raises(J.JoinError, match="unknown node"):
        J.approve(store, "nyk-ffffffffffff", by="operator")


def test_token_value_never_stored(tmp_path, store):
    toks = [J.issue_token(store), J.issue_token(store, auto_approve=True)]
    c, sig, pub = signed(tmp_path)
    J.redeem(store, toks[0], c, sig, pub)
    raw = open(store).read()
    for t in toks:
        assert len(t) >= 32 and t not in raw
    assert J.token_hash(toks[1]) in raw


def test_store_has_no_private_material(tmp_path, store):
    c, sig, pub = signed(tmp_path)
    J.redeem(store, J.issue_token(store), c, sig, pub)
    raw = open(store).read()
    assert "PRIVATE KEY" not in raw and "SSH SIGNATURE" not in raw
    assert json.loads(raw)["nodes"]


# ── panel API ─────────────────────────────────────────────────────────────────────────────────────────────
@pytest.fixture
def panel(store):
    srv = ThreadingHTTPServer(("127.0.0.1", 0), P.Handler)
    srv.join_store = store
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_address[1]}"
    srv.shutdown()


def call(url, body=None):
    req = urllib.request.Request(url, data=None if body is None else json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"})
    try:
        r = urllib.request.urlopen(req)
        return r.status, json.load(r)
    except urllib.error.HTTPError as e:
        return e.code, json.load(e)


def test_panel_token_join_list_approve(tmp_path, panel, store):
    code, d = call(panel + "/api/join/token", {})
    assert code == 200 and len(d["token"]) >= 32 and d["expires"]
    c, sig, pub = signed(tmp_path)
    code, r = call(panel + "/api/join", {"token": d["token"], "card": c, "signature": sig, "host_pubkey": pub})
    assert code == 200 and r["state"] == "pending"
    code, r = call(panel + "/api/join", {"token": d["token"], "card": c, "signature": sig, "host_pubkey": pub})
    assert code == 403                                                    # replay
    nodes = call(panel + "/api/nodes")[1]["nodes"]
    assert nodes[c["node_id"]]["state"] == "pending" and d["token"] not in json.dumps(nodes)
    code, r = call(panel + f"/api/nodes/{c['node_id']}/approve", {})
    assert code == 200 and r["state"] == "approved"
    code, r = call(panel + f"/api/nodes/{c['node_id']}/reject", {})
    assert code == 200 and r["state"] == "rejected"
    assert call(panel + "/api/nodes/nyk-ffffffffffff/approve", {})[0] == 404


def test_panel_join_bad_input(panel):
    assert call(panel + "/api/join", {"token": "x"})[0] == 400


def test_panel_decisions_refused_off_localhost(tmp_path, panel, store, monkeypatch):
    c, sig, pub = signed(tmp_path)
    J.redeem(store, J.issue_token(store), c, sig, pub)
    monkeypatch.setattr(P, "LOCAL_ADDRESSES", frozenset())               # every caller now counts as remote
    for action in ("approve", "reject"):
        code, r = call(panel + f"/api/nodes/{c['node_id']}/{action}", {})
        assert code == 403 and "this machine" in r["error"]
    assert call(panel + "/api/join/token", {})[0] == 403
    assert J.list_nodes(store)[c["node_id"]]["state"] == "pending"


def test_is_local():
    assert P.is_local("127.0.0.1") and P.is_local("::1") and P.is_local("::ffff:127.0.0.1")
    assert not P.is_local("192.0.2.5") and not P.is_local("2001:db8::5")


# ── client ────────────────────────────────────────────────────────────────────────────────────────────────
def test_client_join_end_to_end(tmp_path, panel, store):
    priv, pub = keypair(tmp_path, "host")
    tok = call(panel + "/api/join/token", {})[1]["token"]
    r = J.join(panel, tok, priv, card=sample_card())
    assert r["state"] == "pending"
    n = J.list_nodes(store)["nyk-0123456789ab"]
    assert n["host_pubkey"] == keyline(pub) and n["card_sha256"] == C.card_sha256(sample_card())
    with pytest.raises(J.JoinError):
        J.join(panel, tok, priv, card=sample_card())                     # replay through the client too


def test_no_join_listener_says_how_to_enable_it(panel):
    d = call(panel + "/api/join/token", {"ttl": 600})[1]
    assert d["ttl"] == 600 and d["commands"] == {} and "--join-bind" in d["note"]


# ── web ───────────────────────────────────────────────────────────────────────────────────────────────────
def test_fleet_screen_wires_join_requests(panel):
    page = urllib.request.urlopen(panel + "/").read().decode()
    js = urllib.request.urlopen(panel + "/static/app.js").read().decode()
    assert 'id="join-requests"' in page and 'id="invite"' in page and 'id="join-fp"' in page
    assert 'api("nodes")' in js and "/approve" in js and "/reject" in js and 'api("join/token"' in js and "commands" in js and 'api("join/info")' in js
    assert "if (!DEMO)" in js                                           # demo mode never calls the join API


def test_demo_shim_answers_nodes():
    import os
    shim = open(os.path.join(os.path.dirname(P.__file__), "web", "standalone-shim.js")).read()
    assert 'path === "nodes"' in shim
