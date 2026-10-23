"""The 5W event: what an activity record may contain — and, by omission, everything it may not.

An event says who acted, on whose behalf (whom), what kind of action, where the data went, why it was allowed or
stopped, and how it ended. It never holds message text, prompts, replies or identifier values: personal data shows
up only as per-type counts (entity_counts = {"EMAIL": 2}). validate() enforces that:
  * any field outside FIELDS is rejected (message, text, body, prompt, customer_id, ...)
  * labels are short (64 chars, 8 words; why: 96 chars, 12 words), one line; a label may be a real path
    (/var/log, C:\\Users\\Public, \\\\server\\share) and is checked like any other label
  * every string is run through the identifier recognizers (Aadhaar, PAN, IBAN, card, email, phone, ...) and
    rejected on a hit; long digit runs are rejected as identifier-like
  * session ids must already be pseudonyms (pseudonym()); the sink pseudonymises user and session ids
Errors name the field, never the value.
"""
import hashlib
import hmac
import re
import uuid
from datetime import datetime, timezone

from .. import identity as _identity
from ..cli import detect
from ..recognizers import PACKS

SCHEMA = "niyantrak.5w/1"
OUTCOMES = ("allowed", "masked", "local", "blocked", "needs_approval", "approved", "rejected", "error")
SOURCES = ("json", "otlp")
REQUIRED = ("ts", "who", "what", "where", "why", "outcome")
LABELS = ("who", "whom", "what", "where", "why", "agent", "route", "machine")
FIELDS = frozenset(LABELS + ("ts", "outcome", "rule_ids", "entity_counts", "session", "source", "event_id", "schema",
                             "who_id"))
COLUMNS = ("event_id", "ts", "who", "who_id", "whom", "what", "where", "why", "agent", "route", "machine", "session",
           "rule_ids", "outcome", "entity_counts", "source", "schema")

MAX_LABEL, MAX_WORDS = 64, 8
MAX_WHY, MAX_WHY_WORDS = 96, 12
MAX_RULES, MAX_ENTITY_TYPES, MAX_COUNT = 16, 32, 1_000_000
LABEL_RX = re.compile(r"^[\w][\w .:/()+#&,'·-]*$")
# A label may also be a real path: POSIX absolute (/var/log), Windows drive (C:\Users, D:/data) or UNC
# (\\server\share). Path characters add only @ = ~ and the backslash; shell punctuation (; | ` $ < > " *) stays out,
# and the length, word, one-line, recognizer and digit-run guards below apply to paths exactly as to any label.
_PATH_CHARS = r"[\w .:/\\()+#&,'·@=~-]*"
PATH_RX = re.compile(r"^(?:/|[A-Za-z]:[\\/]|\\\\\w)" + _PATH_CHARS + "$")
RULE_RX = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,63}$")
ENTITY_RX = re.compile(r"^[A-Z][A-Z0-9_]{1,31}$")
PSEUDONYM_RX = re.compile(r"^p-[0-9a-f]{12}$")
EVENT_ID_RX = re.compile(r"^[0-9a-f]{32}$")
DIGIT_RUN = re.compile(r"\d{9,}")
ALL_PACKS = list(PACKS)


class EventError(ValueError):
    """An event that cannot be stored. The message names the field, never its value."""


def pseudonym(value, salt):
    """Stable, salted, one-way stand-in for a user or session id: p-<12 hex>."""
    return "p-" + hmac.new(str(salt).encode(), str(value).encode(), hashlib.sha256).hexdigest()[:12]


def _no_identifiers(field, s):
    if PSEUDONYM_RX.match(s):
        return
    if DIGIT_RUN.search(s.replace(" ", "").replace("-", "")):
        raise EventError(f"{field}: looks like an identifier value")
    if detect(s, ALL_PACKS):
        raise EventError(f"{field}: contains personal data (only per-type counts may be recorded)")


def _label(field, v, required=False):
    if v is None or v == "":
        if required:
            raise EventError(f"{field}: required")
        return None
    if not isinstance(v, str):
        raise EventError(f"{field}: must be text")
    v = v.strip()
    limit, words = (MAX_WHY, MAX_WHY_WORDS) if field == "why" else (MAX_LABEL, MAX_WORDS)
    if len(v) > limit or len(v.split()) > words or "\n" in v or "\r" in v:
        raise EventError(f"{field}: free text is not allowed (at most {limit} characters, {words} words, one line)")
    if not (LABEL_RX.match(v) or PATH_RX.match(v)):
        raise EventError(f"{field}: unexpected characters")
    _no_identifiers(field, v)
    return v


def _ts(v):
    if isinstance(v, bool) or v is None:
        raise EventError("ts: required (ISO 8601 or epoch seconds)")
    try:
        if isinstance(v, (int, float)):
            d = datetime.fromtimestamp(float(v), tz=timezone.utc)
        else:
            s = str(v).strip()
            d = datetime.fromisoformat(s[:-1] + "+00:00" if s.endswith("Z") else s)
            d = d.replace(tzinfo=timezone.utc) if d.tzinfo is None else d.astimezone(timezone.utc)
    except (ValueError, OverflowError, OSError):
        raise EventError("ts: not a timestamp") from None
    return d.strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def parse_ts(s):
    """ISO string from validate() -> naive UTC datetime (how the store keeps it)."""
    return datetime.strptime(s, "%Y-%m-%dT%H:%M:%S.%fZ")


def validate(event):
    """Return a normalised copy of a 5W event, or raise EventError."""
    if not isinstance(event, dict):
        raise EventError("event: must be an object")
    extra = sorted(str(k) for k in event if k not in FIELDS)
    if extra:
        raise EventError(f"field not allowed: {', '.join(k[:40] for k in extra[:5])} (5W events carry no values or text)")
    for f in REQUIRED:
        if event.get(f) in (None, ""):
            raise EventError(f"{f}: required")
    out = {"schema": SCHEMA, "ts": _ts(event["ts"])}
    if event.get("schema") not in (None, SCHEMA):
        raise EventError("schema: unsupported version")
    eid = event.get("event_id")
    if eid is not None and not (isinstance(eid, str) and EVENT_ID_RX.match(eid)):
        raise EventError("event_id: 32 lowercase hex characters")
    out["event_id"] = eid or uuid.uuid4().hex
    for f in LABELS:
        out[f] = _label(f, event.get(f), required=f in REQUIRED)
    if event["outcome"] not in OUTCOMES:
        raise EventError(f"outcome: one of {', '.join(OUTCOMES)}")
    out["outcome"] = event["outcome"]
    sess = event.get("session")
    if sess is not None and not (isinstance(sess, str) and PSEUDONYM_RX.match(sess)):
        raise EventError("session: must be a pseudonym (p-<12 hex>), never the raw id")
    out["session"] = sess
    who_id = event.get("who_id")      # the acting person's directory id (niyantrak.identity), never a raw identifier
    if who_id is not None and not _identity.valid_stable_id(who_id):
        raise EventError("who_id: a directory id like sid:S-1-5-21-..., kanidm:uid:70001 or local:uid:1000@<machine>")
    out["who_id"] = who_id
    src = event.get("source")
    if src is not None and src not in SOURCES:
        raise EventError(f"source: one of {', '.join(SOURCES)}")
    out["source"] = src
    rules = event.get("rule_ids") or []
    if not isinstance(rules, list) or len(rules) > MAX_RULES:
        raise EventError(f"rule_ids: a list of at most {MAX_RULES} rule ids")
    for r in rules:
        if not (isinstance(r, str) and RULE_RX.match(r)):
            raise EventError("rule_ids: rule ids are short codes like RB-ROUTE-001")
        _no_identifiers("rule_ids", r)
    out["rule_ids"] = list(rules)
    counts = event.get("entity_counts") or {}
    if not isinstance(counts, dict) or len(counts) > MAX_ENTITY_TYPES:
        raise EventError(f"entity_counts: an object of at most {MAX_ENTITY_TYPES} types")
    for k, n in counts.items():
        if not (isinstance(k, str) and ENTITY_RX.match(k)):
            raise EventError("entity_counts: keys are entity types like EMAIL or AADHAAR")
        if isinstance(n, bool) or not isinstance(n, int) or not 0 <= n <= MAX_COUNT:
            raise EventError("entity_counts: counts are whole numbers >= 0")
    out["entity_counts"] = dict(counts)
    return out
