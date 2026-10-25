"""6W event log for gate decisions: one JSON line per decision, allow included.

    when   UTC timestamp
    who    the OS user the agent runs as
    agent  the CLI that asked (claude, codex, gemini, antigravity, opencode)
    what   command class and tool name -- never the command or its arguments (they can contain secrets)
    where  host role (NIYANTRAK_HOST_ROLE, else the bootstrap report's role) and a short hash of the host name
    why    rule id, outcome and machine mode
    which  the project the agent works in: the git remote as owner/repo (credentials and host dropped; origin first,
           else the first remote), else the repository's or the working folder's name. Never the home folder or
           the filesystem root, and null when the name fails the 6W label checks (personal data, digit runs).
           The folder is the hook payload's `cwd` when the CLI sends one, else the gate's working directory.

plus ``command_sha256`` so a decision can be matched to a command an operator already has, without storing it.
Location: NIYANTRAK_GATE_LOG, else <state root>/gate/events.jsonl. Logging never blocks or breaks a decision.
"""
import datetime
import getpass
import hashlib
import json
import os
import re
import socket

from ..paths import state_root

SCHEMA = "niyantrak.gate.event/1"


def log_path():
    return os.environ.get("NIYANTRAK_GATE_LOG") or os.path.join(state_root(), "gate", "events.jsonl")


def _who():
    try:
        return getpass.getuser()
    except Exception:  # noqa: BLE001 -- no passwd entry / no env: still log
        return "unknown"


def host_role():
    if os.environ.get("NIYANTRAK_HOST_ROLE"):
        return os.environ["NIYANTRAK_HOST_ROLE"]
    report = os.path.join(os.environ.get("NIYANTRAK_ROOT", "") + "/var/lib/niyantrak/bootstrap", "report.json")
    try:
        with open(report, encoding="utf-8") as fh:
            return str(json.load(fh).get("role") or "unknown")
    except (OSError, ValueError, AttributeError):
        return "unknown"


def _git_dir(top):
    """The git directory of the checkout at `top` (handles the `gitdir:` file of worktrees and submodules)."""
    dot = os.path.join(top, ".git")
    if os.path.isdir(dot):
        return dot
    try:
        with open(dot, encoding="utf-8") as fh:
            line = fh.readline().strip()
    except OSError:
        return None
    if not line.startswith("gitdir:"):
        return None
    gd = line[len("gitdir:"):].strip()
    return gd if os.path.isabs(gd) else os.path.normpath(os.path.join(top, gd))


def _remote_url(git_dir):
    """origin's url from the repository config, else the first remote's; None without one. Read, never run git."""
    common = git_dir
    try:
        with open(os.path.join(git_dir, "commondir"), encoding="utf-8") as fh:
            c = fh.read().strip()
        common = c if os.path.isabs(c) else os.path.normpath(os.path.join(git_dir, c))
    except OSError:
        pass
    remotes, section = {}, None
    try:
        with open(os.path.join(common, "config"), encoding="utf-8", errors="replace") as fh:
            for raw in fh:
                line = raw.strip()
                m = re.match(r'^\[\s*remote\s+"([^"]*)"\s*\]$', line)
                if m:
                    section = m.group(1)
                elif line.startswith("["):
                    section = None
                elif section is not None and re.match(r"^url\s*=", line, re.I):
                    remotes.setdefault(section, line.split("=", 1)[1].strip())
    except OSError:
        return None
    return remotes.get("origin") or next(iter(remotes.values()), None)


def which(cwd=None):
    """The `which` label for a working folder (see the module docstring), or None. Never raises."""
    try:
        return _which(cwd)
    except Exception:  # noqa: BLE001 -- an unreadable checkout must not cost the decision its log line
        return None


def _which(cwd):
    from ..telemetry import schema as S
    try:
        cwd = os.path.realpath(cwd or os.getcwd())
    except OSError:
        return None
    if not os.path.isdir(cwd):
        return None
    home = os.path.realpath(os.path.expanduser("~"))
    skip = lambda d: d == home or os.path.dirname(d) == d                     # home folder, filesystem root
    label, d = None, cwd
    while True:
        if os.path.exists(os.path.join(d, ".git")):
            gd = _git_dir(d)
            url = _remote_url(gd) if gd else None
            label = S.repo_label(url) if url else (None if skip(d) else os.path.basename(d))
            break
        parent = os.path.dirname(d)
        if parent == d:
            label = None if skip(cwd) else os.path.basename(cwd)
            break
        d = parent
    try:
        return S._label("which", label)
    except S.EventError:
        return None


def build(call, decision, agent, cwd=None):
    return {
        "schema": SCHEMA,
        "when": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ"),
        "who": _who(),
        "agent": agent,
        "what": {"class": decision.command_class, "tool": call.tool},
        "where": {"host_role": host_role(),
                  "host_sha256": hashlib.sha256(socket.gethostname().encode()).hexdigest()[:16]},
        "why": {"rule_id": decision.rule_id, "outcome": decision.outcome, "mode": decision.mode},
        "which": which(cwd),
        "command_sha256": hashlib.sha256(call.fingerprint().encode("utf-8", "replace")).hexdigest(),
    }


def record(call, decision, agent, cwd=None):
    """Append one event. Returns False (never raises) when the log cannot be written."""
    try:
        path = log_path()
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
        with os.fdopen(fd, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(build(call, decision, agent, cwd), sort_keys=True) + "\n")
        return True
    except (OSError, ValueError):
        return False
