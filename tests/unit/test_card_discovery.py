"""Signed node cards (genuine / edited / wrong key) and discovery record handling — no network needed."""
import shutil
import subprocess

import pytest

from niyantrak import card as C
from niyantrak import discovery as D

pytestmark = pytest.mark.skipif(not shutil.which("ssh-keygen"), reason="ssh-keygen missing")


def keypair(tmp_path, name):
    k = tmp_path / name
    subprocess.run(["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-f", str(k)], check=True)
    return str(k), (tmp_path / f"{name}.pub").read_text()


def sample_card():
    return {"card_version": 1, "node_id": "nyk-0123456789ab", "hostname": "lab-1", "role": "node",
            "os": {"id": "ubuntu", "version": "24.04", "kernel": "6.8", "arch": "x86_64"}, "cpu": {"cores": 8},
            "memory_gb": 15.6, "gpu": [], "addresses": {"ipv4": ["10.77.0.12"], "ipv6": ["fe80::1%eth0"]}}


def test_genuine_card_verifies(tmp_path):
    priv, pub = keypair(tmp_path, "host")
    c = sample_card()
    sig = C.sign(C.card_bytes(c), priv)
    assert C.verify(C.card_bytes(c), sig, pub)


def test_edited_card_fails(tmp_path):
    priv, pub = keypair(tmp_path, "host")
    c = sample_card()
    sig = C.sign(C.card_bytes(c), priv)
    c["memory_gb"] = 256
    assert not C.verify(C.card_bytes(c), sig, pub)


def test_other_nodes_key_fails(tmp_path):
    priv, _ = keypair(tmp_path, "host")
    _, other_pub = keypair(tmp_path, "other")
    c = sample_card()
    assert not C.verify(C.card_bytes(c), C.sign(C.card_bytes(c), priv), other_pub)


def test_card_hash_is_canonical():
    a, b = sample_card(), dict(reversed(list(sample_card().items())))
    assert C.card_sha256(a) == C.card_sha256(b)


def test_collect_has_no_secrets_and_stable_id():
    c = C.collect(role="node")
    assert c["node_id"].startswith("nyk-") and c["node_id"] == C.collect(role="node")["node_id"]
    assert set(c) == {"card_version", "node_id", "hostname", "role", "os", "cpu", "memory_gb", "gpu", "addresses"}


def test_txt_and_parse_roundtrip():
    txt = D.txt_record(sample_card())
    parsed = D.parse_txt({k.encode(): v.encode() for k, v in txt.items()})
    assert parsed["node_id"] == "nyk-0123456789ab" and len(parsed["card_sha256"]) == 64


def test_foreign_service_ignored():
    assert D.parse_txt({b"node_id": b"someone-else"}) is None


def test_peer_prefers_ipv4_keeps_ipv6(tmp_path):
    peers = D.merge_peer({}, {"node_id": "nyk-a", "port": "8770"}, ["fe80::5%eth0", "192.0.2.7"])
    p = peers["nyk-a"]
    assert p["reach"] == "192.0.2.7" and p["ipv6"] == ["fe80::5%eth0"] and p["verified"] is False


def test_ipv6_only_peer_still_reachable():
    p = D.merge_peer({}, {"node_id": "nyk-w"}, ["fe80::9%eth0"])["nyk-w"]
    assert p["reach"] == "fe80::9%eth0"                     # Windows answering over IPv6 only


def test_save_peers_atomic(tmp_path):
    f = tmp_path / "peers.json"
    D.save_peers({"nyk-a": {"node_id": "nyk-a"}}, str(f))
    assert f.read_text().strip().startswith("{")
