"""Discovery on the local network: announce this node and find others, IPv4 and IPv6 (dual-stack).

    python3 -m niyantrak.discovery announce      # long-running (systemd unit), needs: pip install zeroconf
    python3 -m niyantrak.discovery browse        # print nodes seen in 5 seconds and update the peers file

Service `_niyantrak._tcp`; the TXT record carries only a hint: node_id, card_sha256, card_version, state, panel port.
A peer is trusted only after its signed card verifies (card.py). Windows machines do not need to announce: they
resolve the control node's .local name (Windows answers mDNS over IPv6) and join by calling home over HTTPS, so IPv6
stays on everywhere.
"""
import json
import os
import socket
import sys
import time

from . import card as cardmod
from .paths import state_root

SERVICE = "_niyantrak._tcp.local."
PEERS_FILE = os.environ.get("NIYANTRAK_PEERS") or os.path.join(state_root(), "peers.json")


def txt_record(card, state="member", port=8770):
    return {"node_id": card["node_id"], "card_sha256": cardmod.card_sha256(card), "card_version": str(card["card_version"]),
            "state": state, "port": str(port)}


def parse_txt(props):
    d = {(k.decode() if isinstance(k, bytes) else k): (v.decode() if isinstance(v, bytes) else v) for k, v in props.items()}
    if not str(d.get("node_id", "")).startswith("nyk-"):
        return None
    return d


def merge_peer(peers, txt, addresses, seen_at=None):
    """Keep one entry per node_id; prefer IPv4 for reaching it, keep IPv6 (Windows answers over v6)."""
    v4 = sorted(a for a in addresses if ":" not in a)
    v6 = sorted(a for a in addresses if ":" in a)
    peers[txt["node_id"]] = {"node_id": txt["node_id"], "card_sha256": txt.get("card_sha256"), "state": txt.get("state"),
                             "port": int(txt.get("port", 8770)), "ipv4": v4, "ipv6": v6,
                             "reach": (v4 or v6 or [None])[0], "seen_at": seen_at or time.strftime("%Y-%m-%dT%H:%M:%S"),
                             "verified": False}
    return peers


def save_peers(peers, path=PEERS_FILE):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(peers, f, indent=2)
    os.replace(tmp, path)


def _zeroconf():
    try:
        import zeroconf  # noqa: F401
        return zeroconf
    except ImportError:
        sys.exit("discovery needs the zeroconf package: pip install zeroconf")


def announce(port=8770):
    zc_mod = _zeroconf()
    card = cardmod.collect()
    v4, v6 = card["addresses"]["ipv4"], card["addresses"]["ipv6"]
    addrs = [socket.inet_pton(socket.AF_INET, a) for a in v4] + [socket.inet_pton(socket.AF_INET6, a.split("%")[0]) for a in v6]
    info = zc_mod.ServiceInfo(SERVICE, f"{card['node_id']}.{SERVICE}", addresses=addrs, port=port,
                              properties=txt_record(card, port=port), server=f"{socket.gethostname()}.local.")
    zc = zc_mod.Zeroconf(ip_version=zc_mod.IPVersion.All if v6 else zc_mod.IPVersion.V4Only)
    zc.register_service(info)
    print(f"announcing {card['node_id']} on {v4 + v6}", file=sys.stderr)
    try:
        while True:
            time.sleep(60)
    finally:
        zc.unregister_service(info)
        zc.close()


def browse(seconds=5):
    zc_mod = _zeroconf()
    zc = zc_mod.Zeroconf(ip_version=zc_mod.IPVersion.All)
    peers = {}
    if os.path.isfile(PEERS_FILE):
        try:
            peers = json.load(open(PEERS_FILE))
        except ValueError:
            peers = {}

    class L:
        def add_service(self, z, t, name):
            info = z.get_service_info(t, name, timeout=2000)
            if info:
                txt = parse_txt(info.properties or {})
                if txt:
                    merge_peer(peers, txt, info.parsed_scoped_addresses())

        update_service = add_service

        def remove_service(self, *a):
            pass

    zc_mod.ServiceBrowser(zc, SERVICE, L())
    time.sleep(seconds)
    zc.close()
    save_peers(peers)
    return peers


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "browse"
    if cmd == "announce":
        announce()
    else:
        print(json.dumps(browse(), indent=2))
