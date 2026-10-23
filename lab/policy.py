#!/usr/bin/env python3
"""policy -- safety checks for the install lab (no third-party modules; used by lab.sh and the unit tests).

    python3 lab/policy.py network lab/network.xml
    python3 lab/policy.py seed    <rendered user-data>
    python3 lab/policy.py budget  lab/vms.json [--free-ram-gb N] [--free-disk-gb N]

Each prints one line per problem and exits 1 if there are any, 0 if clean.
"""
import json
import re
import sys
import xml.etree.ElementTree as ET


def check_network_xml(text):
    """The lab network must be its own NAT bridge: no bridge/macvtap/passthrough forward, no physical device."""
    problems = []
    try:
        root = ET.fromstring(text)
    except ET.ParseError as e:
        return [f"network xml does not parse: {e}"]
    fwd = root.find("forward")
    mode = fwd.get("mode", "nat") if fwd is not None else "isolated"
    if mode not in ("nat", "isolated", "none"):
        problems.append(f"forward mode '{mode}' joins the lab to a real network; use nat")
    if fwd is not None and (fwd.get("dev") or fwd.find("interface") is not None or fwd.find("pf") is not None):
        problems.append("forward names a physical device; the lab must not touch a real NIC")
    br = root.find("bridge")
    name = br.get("name", "") if br is not None else ""
    if not name.startswith("virbr-"):
        problems.append(f"bridge '{name}' is not a private virbr-* bridge")
    ip = root.find("ip")
    addr = ip.get("address", "") if ip is not None else ""
    if not re.match(r"^10\.77\.", addr):
        problems.append(f"lab subnet {addr or '(none)'} is not 10.77.0.0/24 (keeps it apart from the home LAN)")
    return problems


SEED_RULES = [
    (re.compile(r"^\s*disable_root:\s*true\b", re.M), True, "root must stay locked (disable_root: true)"),
    (re.compile(r"^\s*allow-pw:\s*false\b", re.M), True, "installer SSH must refuse passwords (allow-pw: false)"),
    (re.compile(r"^\s*ssh_pwauth:\s*false\b", re.M), True, "cloud-init must refuse passwords (ssh_pwauth: false)"),
    (re.compile(r"PermitRootLogin\s+no\b"), True, "sshd must refuse root (PermitRootLogin no)"),
    (re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"), False, "a private key is in the seed"),
    (re.compile(r"\$[0-9a-z]{1,2}\$[^\s\"']{8,}"), False, "a password hash is in the seed (use a locked password '!')"),
    (re.compile(r"^\s*chpasswd:", re.M), False, "chpasswd sets passwords; not allowed"),
    (re.compile(r"^\s*plain_text_passwd:", re.M), False, "plain-text password in the seed"),
    (re.compile(r"@[A-Z_]+@"), False, "unrendered placeholder left in the seed"),
]


def check_seed(text):
    problems = []
    if "NOPASSWD:ALL" in text and "# niyantrak-lab-only" not in text:
        problems.append("password-less sudo for everything is allowed only in lab seeds (# niyantrak-lab-only)")
    installer = "autoinstall:" in text
    for rx, must_match, msg in SEED_RULES:
        if "allow-pw" in msg and not installer:      # installer-only key; cloud-init seeds use ssh_pwauth
            continue
        found = bool(rx.search(text))
        if found != must_match:
            problems.append(msg)
    return problems


def check_budget(vms_doc, free_ram_gb=None, free_disk_gb=None):
    problems = []
    vms = vms_doc.get("vms", [])
    names = [v.get("name") for v in vms]
    if len(names) != len(set(names)):
        problems.append("duplicate VM names")
    for v in vms:
        for k in ("name", "role", "os", "boot", "vcpus", "ram_gb", "disk_gb"):
            if k not in v:
                problems.append(f"{v.get('name', '?')}: missing {k}")
        if v.get("boot") not in ("iso", "pxe", "cloudimg"):
            problems.append(f"{v.get('name')}: boot must be iso, pxe or cloudimg")
    if sum(1 for v in vms if v.get("role") == "control") != 1:
        problems.append("exactly one control VM is required")
    ram = sum(v.get("ram_gb", 0) for v in vms)
    disk = sum(v.get("disk_gb", 0) for v in vms)
    if free_ram_gb is not None and ram > free_ram_gb:
        problems.append(f"all VMs need {ram} GB RAM, host has {free_ram_gb} GB available")
    if free_disk_gb is not None and disk > free_disk_gb:
        problems.append(f"all VMs need {disk} GB disk, host has {free_disk_gb} GB free")
    return problems


def main(argv):
    if len(argv) < 3:
        print(__doc__.strip())
        return 2
    kind, path = argv[1], argv[2]
    text = open(path, encoding="utf-8").read()
    if kind == "network":
        problems = check_network_xml(text)
    elif kind == "seed":
        problems = check_seed(text)
    elif kind == "budget":
        opts = dict(zip(argv[3::2], argv[4::2]))
        problems = check_budget(json.loads(text),
                                float(opts["--free-ram-gb"]) if "--free-ram-gb" in opts else None,
                                float(opts["--free-disk-gb"]) if "--free-disk-gb" in opts else None)
    else:
        print(f"unknown check: {kind}")
        return 2
    for p in problems:
        print(f"FAIL {kind}: {p}")
    if not problems:
        print(f"ok   {kind}: {path}")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
