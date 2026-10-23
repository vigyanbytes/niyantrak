"""Decision event schema and the privacy gate every write passes through.

One row = one event. Status is never stored; it is derived from the events (see graph.py).

    ts          ISO time, nanosecond precision when stamped here ("latest event wins" must be exact)
    session_id  the agent/chat session that produced it
    op          add | retract              (a retract undoes the matching add; a later add makes it live again)
    kind        DECISION | WORK | THING | STATUS | RETIRED | SUPERSEDED_BY | REFERENCES | ABOUT | DECIDED_IN
    src, dst    ids; dst only for links (the last four kinds)
    title, text short words; STATUS events carry the status bucket in title and the raw word in text
    written_by  stamped by the store, never taken from the caller
    user_id     opaque handle of the person (never an email address or phone number)
    user_ref    that person's directory id from the operating system (niyantrak.identity), when not set by hand
    agent_id    which AI agent / tool wrote it
    product     which product or tenant it belongs to

Privacy: decisions are internal data. A batch that contains a credential or a personal identifier (the same
checksum-validated recognizers as `niyantrak scan`) is refused whole and nothing is written; the refusal names the
kind of finding, never the value.
"""
from .. import identity as _identity
import re
import time

FIELDS = ("ts", "session_id", "op", "kind", "src", "dst", "title", "text", "written_by", "user_id", "agent_id", "product",
          "user_ref")
NODE_KINDS = {"DECISION", "WORK", "THING"}
EDGE_KINDS = {"SUPERSEDED_BY", "REFERENCES", "ABOUT", "DECIDED_IN"}
KINDS = NODE_KINDS | EDGE_KINDS | {"STATUS", "RETIRED"}
OPS = {"add", "retract"}
ACTOR_ENV = {"session_id": "NIYANTRAK_SESSION_ID", "user_id": "NIYANTRAK_USER", "agent_id": "NIYANTRAK_AGENT",
             "product": "NIYANTRAK_PRODUCT"}
MAX = {"src": 200, "dst": 200, "title": 300, "text": 2000, "session_id": 120, "user_id": 120, "agent_id": 120,
       "product": 120, "ts": 40, "user_ref": 200}

SECRET_PATTERNS = [re.compile(p) for p in (
    r"-----BEGIN [A-Z ]*PRIVATE KEY-----", r"\bAKIA[0-9A-Z]{16}\b", r"\bgh[pousr]_[A-Za-z0-9]{36,}\b",
    r"\bsk-[A-Za-z0-9_-]{20,}\b", r"\bxox[baprs]-[A-Za-z0-9-]{10,}\b", r"\bAIza[0-9A-Za-z_-]{35}\b",
    r"AGE-SECRET-KEY-1[0-9A-Z]{50,}", r"\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\b",
    r"(?i)\b(password|passwd|secret|api[_-]?key|token)\s*[:=]\s*\S{8,}")]
ACTOR_FIELDS = ("user_id", "agent_id", "session_id", "product")


class EventError(ValueError):
    """The event does not fit the schema."""


class PrivacyError(ValueError):
    """The batch holds a secret or a personal identifier; nothing was written."""


def stamp(ns=None):
    ns = time.time_ns() if ns is None else ns
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(ns // 10**9)) + f".{ns % 10**9:09d}"


def short(s, n):
    s = re.sub(r"\s+", " ", str(s or "")).strip()
    return s if len(s) <= n else s[:n - 1] + "…"


def normalize(row, writer, env, now_ns=None, actor=None, agent=None):
    """A complete event with every field (None when absent). Raises EventError."""
    if not isinstance(row, dict):
        raise EventError("an event is an object")
    r = {k: (None if row.get(k) in (None, "") else str(row.get(k))) for k in FIELDS}
    r["op"] = r["op"] or "add"
    if r["op"] not in OPS:
        raise EventError(f"op must be one of {sorted(OPS)}")
    if r["kind"] not in KINDS:
        raise EventError(f"unknown kind {str(r['kind'])[:40]!r}")
    if not r["src"] or not r["src"].strip():
        raise EventError("src is required")
    if r["kind"] in EDGE_KINDS and not r["dst"]:
        raise EventError(f"{r['kind']} needs dst")
    if r["kind"] not in EDGE_KINDS:
        r["dst"] = None
    for k, env_name in ACTOR_ENV.items():
        r[k] = r[k] or env.get(env_name) or None
    if r["user_ref"] is not None and not _identity.valid_stable_id(r["user_ref"]):
        raise EventError("user_ref: a directory id like sid:S-1-5-21-..., kanidm:uid:70001 or local:uid:1000@<machine>")
    if r["user_id"] is None and actor is not None:        # the person from the operating system, never typed
        r["user_id"], r["user_ref"] = actor.name, actor.stable_id
    if r["agent_id"] is None and agent:
        r["agent_id"] = str(agent)
    r["ts"] = r["ts"] or stamp(now_ns)
    r["written_by"] = str(writer)
    for k, n in MAX.items():
        if r[k] is not None:
            r[k] = short(r[k], n) if k in ("title", "text") else r[k].strip()[:n]
    return r


def privacy_findings(rows):
    """Kinds of sensitive content in a batch (never the values)."""
    from ..cli import detect
    from ..recognizers import PACKS
    found = set()
    for r in rows:
        blob = " ".join(str(r.get(k) or "") for k in FIELDS if k not in ("ts", "op", "kind", "written_by"))
        if any(p.search(blob) for p in SECRET_PATTERNS):
            found.add("credential")
        for _, _, entity, _ in detect(" | ".join(str(r.get(k) or "") for k in ("title", "text")), list(PACKS)):
            found.add(entity)
        for k in ACTOR_FIELDS:
            if r.get(k) and detect(r[k], list(PACKS)):
                found.add(f"personal data in {k}")
    return sorted(found)


def check_privacy(rows):
    f = privacy_findings(rows)
    if f:
        raise PrivacyError("refused, nothing written: the batch contains " + ", ".join(f)
                           + ". Keep secrets and personal identifiers out of the decision log.")
