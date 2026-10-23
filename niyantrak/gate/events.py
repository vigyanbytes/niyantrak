"""5W event log for gate decisions: one JSON line per decision, allow included.

    when   UTC timestamp
    who    the OS user the agent runs as
    agent  the CLI that asked (claude, codex, gemini, antigravity, opencode)
    what   command class and tool name -- never the command or its arguments (they can contain secrets)
    where  host role (NIYANTRAK_HOST_ROLE, else the bootstrap report's role) and a short hash of the host name
    why    rule id, outcome and machine mode

plus ``command_sha256`` so a decision can be matched to a command an operator already has, without storing it.
Location: NIYANTRAK_GATE_LOG, else <state root>/gate/events.jsonl. Logging never blocks or breaks a decision.
"""
import datetime
import getpass
import hashlib
import json
import os
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


def build(call, decision, agent):
    return {
        "schema": SCHEMA,
        "when": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ"),
        "who": _who(),
        "agent": agent,
        "what": {"class": decision.command_class, "tool": call.tool},
        "where": {"host_role": host_role(),
                  "host_sha256": hashlib.sha256(socket.gethostname().encode()).hexdigest()[:16]},
        "why": {"rule_id": decision.rule_id, "outcome": decision.outcome, "mode": decision.mode},
        "command_sha256": hashlib.sha256(call.fingerprint().encode("utf-8", "replace")).hexdigest(),
    }


def record(call, decision, agent):
    """Append one event. Returns False (never raises) when the log cannot be written."""
    try:
        path = log_path()
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
        with os.fdopen(fd, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(build(call, decision, agent), sort_keys=True) + "\n")
        return True
    except (OSError, ValueError):
        return False
