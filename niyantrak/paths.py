"""Where Niyantrak keeps its state (join store, peers, panel certificate).

NIYANTRAK_STATE_ROOT wins; otherwise /var/lib/niyantrak when running as root or when it is writable; otherwise the
user's own ~/.local/share/niyantrak — so the free panel works without root. On Windows (no root, no /var/lib):
%LOCALAPPDATA%\\Niyantrak, else the home-folder path.
"""
import os

SYSTEM_ROOT = "/var/lib/niyantrak"


def _writable(path):
    p = path
    while p and not os.path.exists(p):
        p = os.path.dirname(p)
    return bool(p) and os.access(p, os.W_OK)


def state_root():
    env = os.environ.get("NIYANTRAK_STATE_ROOT")
    if env:
        return env
    if os.name == "nt" or not hasattr(os, "geteuid"):
        local = os.environ.get("LOCALAPPDATA")
        if local:
            return os.path.join(local, "Niyantrak")
    elif os.geteuid() == 0 or _writable(SYSTEM_ROOT):
        return SYSTEM_ROOT
    return os.path.join(os.path.expanduser("~"), ".local", "share", "niyantrak")
