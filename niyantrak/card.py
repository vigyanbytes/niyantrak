"""Node card: what a machine is (hardware, OS, addresses), signed with its own SSH host key.

An mDNS announcement is only a hint; trust comes from verifying the card against the host key recorded when the
machine was approved. Signing uses OpenSSH's file signatures (`ssh-keygen -Y sign/verify`, namespace below), so
no extra crypto library is needed and the key is the one the machine already has.

    card = collect()                            # facts, no secrets
    sig = sign(card_bytes(card), "/etc/ssh/ssh_host_ed25519_key")
    ok = verify(card_bytes(card), sig, host_public_key_line)
"""
import hashlib
import json
import os
import platform
import shutil
import socket
import subprocess
import tempfile

NAMESPACE = "niyantrak-node-card"
CARD_VERSION = 1


def node_id(uuid_file="/sys/class/dmi/id/product_uuid"):
    """Same scheme as the bootstrap: nyk-<sha256(lowercased SMBIOS uuid)[:12]>, machine-id as fallback."""
    raw = ""
    for f in (uuid_file, "/etc/machine-id"):
        try:
            raw = open(f).read().strip().lower()
            if raw:
                break
        except OSError:
            continue
    return "nyk-" + hashlib.sha256((raw or socket.gethostname()).encode()).hexdigest()[:12]


SKIP_IFACES = ("lo", "docker", "br-", "veth", "virbr", "vnet", "cni", "flannel", "kube", "tap")


def _addresses():
    """Addresses people can reach this node on: physical/LAN/VPN interfaces only (container and VM bridges skipped).
    IPv6 keeps link-local (with %interface) because Windows answers mDNS over it."""
    v4, v6 = set(), set()
    if shutil.which("ip"):
        out = subprocess.run(["ip", "-o", "addr", "show"], capture_output=True, text=True).stdout
        for line in out.splitlines():
            parts = line.split()
            iface = parts[1].rstrip(":").split("@")[0]
            if iface.startswith(SKIP_IFACES):
                continue
            if "inet" in parts:
                v4.add(parts[parts.index("inet") + 1].split("/")[0])
            if "inet6" in parts and "temporary" not in parts:
                a = parts[parts.index("inet6") + 1].split("/")[0]
                v6.add(a + (f"%{iface}" if a.startswith("fe80") else ""))
    else:
        try:
            for fam, _, _, _, sa in socket.getaddrinfo(socket.gethostname(), None):
                (v4 if fam == socket.AF_INET else v6).add(sa[0])
        except socket.gaierror:
            pass
    v4 = {a for a in v4 if not a.startswith("127.")}
    v6 = {a for a in v6 if a != "::1"}
    return sorted(v4), sorted(v6)


def _gpu():
    if not shutil.which("nvidia-smi"):
        return []
    out = subprocess.run(["nvidia-smi", "--query-gpu=name,memory.total", "--format=csv,noheader,nounits"],
                         capture_output=True, text=True).stdout
    return [{"name": n.strip(), "vram_mb": int(m)} for n, m in (l.split(",") for l in out.splitlines() if "," in l)]


def collect(role=None):
    mem_kb = 0
    try:
        mem_kb = int(next(l for l in open("/proc/meminfo") if l.startswith("MemTotal")).split()[1])
    except (OSError, StopIteration):
        pass
    osr = {}
    try:
        osr = dict(l.strip().split("=", 1) for l in open("/etc/os-release") if "=" in l)
    except OSError:
        pass
    v4, v6 = _addresses()
    return {"card_version": CARD_VERSION, "node_id": node_id(), "hostname": socket.gethostname(),
            "role": role or open("/etc/niyantrak/role").read().strip() if os.path.isfile("/etc/niyantrak/role") else role,
            "os": {"id": osr.get("ID", platform.system()).strip('"'), "version": osr.get("VERSION_ID", "").strip('"'),
                   "kernel": platform.release(), "arch": platform.machine()},
            "cpu": {"cores": os.cpu_count()}, "memory_gb": round(mem_kb / 1048576, 1), "gpu": _gpu(),
            "addresses": {"ipv4": v4, "ipv6": v6}}


def card_bytes(card):
    """Canonical bytes: what is signed and what card_sha256 covers."""
    return json.dumps(card, sort_keys=True, separators=(",", ":")).encode()


def card_sha256(card):
    return hashlib.sha256(card_bytes(card)).hexdigest()


def sign(data, private_key_path):
    with tempfile.TemporaryDirectory() as d:
        f = os.path.join(d, "card.json")
        open(f, "wb").write(data)
        subprocess.run(["ssh-keygen", "-q", "-Y", "sign", "-f", private_key_path, "-n", NAMESPACE, f],
                       check=True, capture_output=True)
        return open(f + ".sig").read()


def verify(data, signature, public_key_line, principal="node"):
    """True only if `signature` over `data` was made by the key in `public_key_line` (an authorized host key)."""
    with tempfile.TemporaryDirectory() as d:
        signers = os.path.join(d, "allowed")
        open(signers, "w").write(f"{principal} {public_key_line.strip()}\n")
        sigf = os.path.join(d, "card.sig")
        open(sigf, "w").write(signature)
        r = subprocess.run(["ssh-keygen", "-Y", "verify", "-f", signers, "-I", principal, "-n", NAMESPACE, "-s", sigf],
                           input=data, capture_output=True)
        return r.returncode == 0
