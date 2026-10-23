"""Who is acting, derived from the operating system: never typed in, never a role label.

    who = identity.current()     # Identity(name, uid, directory, stable_id)
    identity.agent()             # "claude", "codex", ... when an AI agent acts on that person's behalf

* The person is the LOGIN user: the kernel's login record (/proc/self/loginuid) survives sudo and is inherited by
  agents started in that session; then SUDO_UID; then the process uid.
* The name comes from NSS (getpwuid), so local accounts, SSSD (Active Directory / LDAP), authd (Entra ID, Google)
  and Kanidm (kanidm-unixd) all resolve the same way. Niyantrak keeps no user list of its own.
* The directory is the NSS module that answered: "local" when the account is in /etc/passwd, else the first
  directory module on the passwd line of /etc/nsswitch.conf.
* The stable id survives renames: the AD SID when SSSD can give it, else the directory-assigned uid (the same on
  every machine joined to that directory), else the local uid scoped to this machine.
Standard library only; the SID lookup uses SSSD's python binding when it is installed.
"""
import os
import pwd
import re
from dataclasses import dataclass

LOGINUID = "/proc/self/loginuid"
UNSET_LOGINUID = 4294967295
NSS_DIRECTORIES = {"sss": "sssd", "authd": "authd", "kanidm": "kanidm", "ldap": "ldap", "winbind": "winbind"}
SID_RX = re.compile(r"^sid:S-1-\d{1,3}(-\d{1,10}){1,15}$")
UID_RX = re.compile(r"^[a-z]{3,10}:uid:\d{1,10}(@[0-9a-f]{12})?$")
KNOWN_AGENTS = (("CLAUDECODE", "claude"),)


@dataclass(frozen=True)
class Identity:
    name: str
    uid: int
    directory: str
    stable_id: str


def login_uid(proc_loginuid=LOGINUID, env=None, getuid=os.getuid):
    env = os.environ if env is None else env
    try:
        with open(proc_loginuid, encoding="ascii") as f:
            uid = int(f.read().strip())
        if uid != UNSET_LOGINUID:
            return uid
    except (OSError, ValueError):
        pass
    if str(env.get("SUDO_UID", "")).isdigit():
        return int(env["SUDO_UID"])
    return getuid()


def _local_names(passwd_path):
    try:
        with open(passwd_path, encoding="utf-8", errors="replace") as f:
            return {line.split(":", 1)[0] for line in f if line.strip() and not line.startswith("#")}
    except OSError:
        return set()


def directory_for(name, passwd_path="/etc/passwd", nsswitch_path="/etc/nsswitch.conf"):
    if name in _local_names(passwd_path):
        return "local"
    try:
        with open(nsswitch_path, encoding="utf-8", errors="replace") as f:
            for line in f:
                key, _, rest = line.partition(":")
                if key.strip() == "passwd":
                    for module in re.findall(r"[A-Za-z_]+", rest.split("#", 1)[0]):
                        if module in NSS_DIRECTORIES:
                            return NSS_DIRECTORIES[module]
    except OSError:
        pass
    return "unknown"


def _machine(machine_id_path):
    try:
        with open(machine_id_path, encoding="ascii") as f:
            m = f.read().strip().lower()
        return m[:12] if re.fullmatch(r"[0-9a-f]{12,}", m) else None
    except OSError:
        return None


def sssd_sid(name):
    """The AD SID of a SSSD user, or None (binding missing, not an AD user, lookup failed)."""
    try:
        import pysss_nss_idmap  # noqa: PLC0415  (optional, ships with sssd)
        sid = (pysss_nss_idmap.getsidbyname(name) or {}).get(name, {}).get("sid")
        return sid if sid and SID_RX.match("sid:" + sid) else None
    except Exception:  # noqa: BLE001 — an identity lookup must never stop a write
        return None


def current(getpwuid=pwd.getpwuid, env=None, getuid=os.getuid, proc_loginuid=LOGINUID, passwd_path="/etc/passwd",
            nsswitch_path="/etc/nsswitch.conf", machine_id_path="/etc/machine-id", sid_lookup=sssd_sid):
    uid = login_uid(proc_loginuid, env, getuid)
    try:
        name = getpwuid(uid).pw_name
        directory = directory_for(name, passwd_path, nsswitch_path)
    except KeyError:
        name, directory = f"uid-{uid}", "unknown"
    sid = sid_lookup(name) if directory in ("sssd", "winbind") else None
    if sid:
        stable = f"sid:{sid}"
    elif directory in ("local", "unknown"):
        m = _machine(machine_id_path)
        stable = f"{directory}:uid:{uid}" + (f"@{m}" if m else "")
    else:
        stable = f"{directory}:uid:{uid}"
    return Identity(name=name, uid=uid, directory=directory, stable_id=stable)


def agent(env=None):
    env = os.environ if env is None else env
    if env.get("NIYANTRAK_AGENT"):
        return str(env["NIYANTRAK_AGENT"])
    for var, name in KNOWN_AGENTS:
        if env.get(var) == "1":
            return name
    return None


def valid_stable_id(s):
    s = str(s or "")
    return len(s) <= 200 and bool(SID_RX.match(s) or UID_RX.match(s))
