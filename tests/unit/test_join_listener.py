"""Two listeners: admin on loopback (everything) and a TLS join-only listener; the client pins the certificate."""
import hashlib
import json
import os
import shutil
import ssl
import subprocess
import sys
import threading
import urllib.error
import urllib.request

import pytest

from niyantrak import join as J
from niyantrak import panel as P
from niyantrak import tls as T

pytestmark = [pytest.mark.skipif(not shutil.which("ssh-keygen"), reason="ssh-keygen missing"),
              pytest.mark.skipif(not shutil.which("openssl"), reason="openssl missing")]


def keypair(tmp_path, name):
    k = tmp_path / name
    subprocess.run(["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-f", str(k)], check=True)
    return str(k)


def sample_card():
    return {"card_version": 1, "node_id": "nyk-0123456789ab", "hostname": "lab-1", "role": "node",
            "os": {"id": "ubuntu", "version": "24.04", "kernel": "6.8", "arch": "x86_64"}, "cpu": {"cores": 8},
            "memory_gb": 15.6, "gpu": [], "addresses": {"ipv4": ["192.0.2.12"], "ipv6": []}}


@pytest.fixture
def two(tmp_path):
    store = str(tmp_path / "join.json")
    admin, joinsrv = P.make_servers("127.0.0.1", 0, join_bind="127.0.0.1", join_port=0,
                                    state_dir=str(tmp_path / "panel"), store=store)
    for s in (admin, joinsrv):
        threading.Thread(target=s.serve_forever, daemon=True).start()
    yield {"admin": f"http://127.0.0.1:{admin.server_address[1]}", "join": f"https://127.0.0.1:{joinsrv.server_address[1]}",
           "jport": joinsrv.server_address[1], "store": store, "fp": joinsrv.fingerprint, "state": str(tmp_path / "panel")}
    admin.shutdown()
    joinsrv.shutdown()


def call(url, body=None, insecure=False):
    req = urllib.request.Request(url, data=None if body is None else json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"})
    ctx = ssl._create_unverified_context() if insecure else None
    try:
        r = urllib.request.urlopen(req, context=ctx, timeout=10)
        return r.status, r.read().decode()
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()


# ── certificate ───────────────────────────────────────────────────────────────────────────────────────────
def test_cert_created_once_key_private(tmp_path):
    d = str(tmp_path / "st")
    cert, key = T.ensure_cert(d)
    assert oct(os.stat(key).st_mode)[-3:] == "600" and oct(os.stat(d).st_mode)[-3:] == "700"
    fp = T.fingerprint(cert)
    der = ssl.PEM_cert_to_DER_cert(open(cert).read())
    assert fp == hashlib.sha256(der).hexdigest() and len(fp) == 64
    assert T.ensure_cert(d) == (cert, key) and T.fingerprint(cert) == fp     # reused, not regenerated


def test_pin_normalisation():
    h = "ab" * 32
    assert T.normalise_pin("sha256:" + h.upper()) == h == T.normalise_pin(":".join(["AB"] * 32))
    with pytest.raises(ValueError):
        T.normalise_pin("sha256:1234")


# ── join-only listener ────────────────────────────────────────────────────────────────────────────────────
def test_admin_endpoints_unreachable_via_join_listener(two):
    for path in ("/api/nodes", "/api/node", "/api/peers", "/static/app.js", "/api/join/info"):
        assert call(two["join"] + path, insecure=True)[0] == 404, path
    for path in ("/api/join/token", "/api/nodes/nyk-0123456789ab/approve", "/api/scan", "/api/discover"):
        assert call(two["join"] + path, {}, insecure=True)[0] == 404, path


def test_join_listener_serves_public_fingerprint_page(two):
    code, body = call(two["join"] + "/", insecure=True)
    assert code == 200 and two["fp"] in body and "token" not in body.lower().replace("join token", "")


def test_plain_http_to_join_listener_refused(two):
    with pytest.raises((urllib.error.URLError, ConnectionError, OSError)):
        urllib.request.urlopen(f"http://127.0.0.1:{two['jport']}/", timeout=5).read()


def test_admin_shows_fingerprint_and_both_one_liners(two):
    info = json.loads(call(two["admin"] + "/api/join/info")[1])
    assert info["enabled"] and info["fingerprint"] == two["fp"]
    d = json.loads(call(two["admin"] + "/api/join/token", {})[1])
    by_ip, by_name = d["commands"]["address"], d["commands"]["mdns"]
    assert f"https://127.0.0.1:{two['jport']} " in by_ip and ".local:" in by_name
    for c in (by_ip, by_name):
        assert d["token"] in c and f"--pin sha256:{two['fp']}" in c and c.startswith("sudo python3 -m niyantrak.join https://")


def test_join_with_correct_pin(tmp_path, two):
    tok = json.loads(call(two["admin"] + "/api/join/token", {})[1])["token"]
    r = J.join(two["join"], tok, keypair(tmp_path, "host"), card=sample_card(), pin="sha256:" + two["fp"])
    assert r["state"] == "pending" and J.list_nodes(two["store"])["nyk-0123456789ab"]["state"] == "pending"
    assert "approve" not in r


def test_wrong_pin_refused_before_sending(tmp_path, two):
    tok = json.loads(call(two["admin"] + "/api/join/token", {})[1])["token"]
    with pytest.raises(J.JoinError, match="certificate"):
        J.join(two["join"], tok, keypair(tmp_path, "host"), card=sample_card(), pin="0" * 64)
    assert J.list_nodes(two["store"]) == {}
    # the token was never sent, so it still works with the right pin
    assert J.join(two["join"], tok, str(tmp_path / "host"), card=sample_card(), pin=two["fp"])["state"] == "pending"


def test_https_without_pin_refused(tmp_path, two):
    with pytest.raises(J.JoinError, match="pin"):
        J.join(two["join"], "x", keypair(tmp_path, "host"), card=sample_card())


def test_cli_has_join_bind():
    r = subprocess.run([sys.executable, "-m", "niyantrak.cli", "panel", "--help"], capture_output=True, text=True,
                       cwd=os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
    assert "--join-bind" in r.stdout and "--join-port" in r.stdout


def test_gitignore_coverage():
    root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    lines = open(os.path.join(root, ".gitignore")).read().split()
    assert ".coverage" in lines and "htmlcov/" in lines


def test_plain_http_to_remote_refused_by_client(tmp_path):
    with pytest.raises(J.JoinError, match="https"):
        J.join("http://192.0.2.5:8770", "x", keypair(tmp_path, "host"), card=sample_card())


# ── Windows one-liner ─────────────────────────────────────────────────────────────────────────────────────
def test_windows_one_liner_pins_cert_checks_script_hash_and_has_no_token(two):
    d = json.loads(call(two["admin"] + "/api/join/token", {})[1])
    w = d["commands"]["windows"]
    script = open(P.WINDOWS_JOIN_SCRIPT, "rb").read()
    h = hashlib.sha256(script).hexdigest()
    assert d["windows_script_sha256"] == h
    assert d["token"] not in w, "the Windows script asks for the token; it must not sit in PowerShell history"
    assert f"https://127.0.0.1:{two['jport']}/join.ps1" in w and f"-PanelUrl https://127.0.0.1:{two['jport']}" in w
    assert two["fp"] in w and "ServerCertificateValidationCallback" in w and "GetRawCertData" in w
    assert "Get-FileHash" in w and h.upper() in w and "throw" in w
    assert w.index("Get-FileHash") < w.index("-File ")              # hash checked before the script runs
    assert "-ControlAddress 127.0.0.1" in w and "-Apply" not in w     # dry run first; the admin adds -Apply


def test_join_listener_serves_the_windows_script(two):
    code, body = call(two["join"] + "/join.ps1", insecure=True)
    assert code == 200 and hashlib.sha256(body.encode()).hexdigest() == hashlib.sha256(
        open(P.WINDOWS_JOIN_SCRIPT, "rb").read()).hexdigest()


def test_windows_one_liner_absent_when_script_missing(two, monkeypatch):
    monkeypatch.setattr(P, "WINDOWS_JOIN_SCRIPT", "/nonexistent/join.ps1")
    d = json.loads(call(two["admin"] + "/api/join/token", {})[1])
    assert "windows" not in d["commands"] and "address" in d["commands"]
    assert call(two["join"] + "/join.ps1", insecure=True)[0] == 404


def test_panel_page_shows_windows_command_and_token_separately():
    web = os.path.join(os.path.dirname(P.__file__), "web")
    page, js = open(os.path.join(web, "index.html")).read(), open(os.path.join(web, "app.js")).read()
    assert 'id="cmd-join-win"' in page and 'id="join-token"' in page and 'data-copy="join-token"' in page
    assert "c.windows" in js and "d.token" in js
    assert "ships with the next release" not in page
