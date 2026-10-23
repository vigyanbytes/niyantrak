"""5W sink: OTLP/HTTP JSON logs and plain JSON events in, validated 5W events out (to a Store).

    niyantrak telemetry sink [--bind 127.0.0.1] [--port 4318] [--dir <store>] [--writer <name>]

    POST /v1/logs     OTLP/HTTP with Content-Type application/json (protobuf: 415 — set the exporter to json)
    POST /v1/events   one 5W event, a list of them, or {"events": [...]}; strict: an event with any field outside
                      the 5W allow-list is rejected (400 when nothing was accepted)

OTLP mapping (ALLOW below). Everything else — the log body, gen_ai.prompt / completion / message content, any
attribute not listed — is dropped before validation and only counted. user and session ids are pseudonymised with
a per-store salt; a record whose allowed attributes still hold an identifier value is rejected, not stored.
Keep the sink on loopback or a private address: it has no authentication of its own.
"""
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from . import schema as S

MAX_BODY = 5 * 1024 * 1024
ENTITY_PREFIX = "niyantrak.entity."

# 5W field <- OTLP attribute keys, first non-empty wins (record attributes before resource attributes)
ALLOW = {
    "who": ["niyantrak.who", "enduser.role", "user.role"],
    "who_id": ["enduser.id", "user.id"],                                  # pseudonymised into who
    "whom": ["niyantrak.whom"],
    "what": ["niyantrak.what", "gen_ai.operation.name", "event.name"],
    "where": ["niyantrak.where", "gen_ai.provider.name", "gen_ai.system", "server.address"],
    "why": ["niyantrak.why"],
    "agent": ["niyantrak.agent", "gen_ai.agent.name", "service.name"],
    "route": ["niyantrak.route", "gen_ai.request.model"],
    "machine": ["niyantrak.machine", "host.name"],
    "session_id": ["session.id", "gen_ai.conversation.id"],               # pseudonymised into session
    "outcome": ["niyantrak.outcome"],
    "rule_ids": ["niyantrak.rule_ids"],
}
ALLOWED_KEYS = frozenset(k for keys in ALLOW.values() for k in keys)
DEFAULTS = {"who": "unknown", "what": "unspecified", "where": "unspecified", "why": "unspecified", "outcome": "allowed"}


class BadRequest(ValueError):
    pass


@dataclass
class Result:
    events: list = field(default_factory=list)
    rejected: int = 0
    dropped: int = 0                 # body + attributes outside the allow-list (counted, never kept)
    errors: list = field(default_factory=list)


def _any(v):
    if not isinstance(v, dict):
        return v
    for k, f in (("stringValue", str), ("boolValue", bool), ("intValue", int), ("doubleValue", float)):
        if k in v:
            try:
                return f(v[k])
            except (TypeError, ValueError):
                return None
    if "arrayValue" in v:
        return [_any(x) for x in (v["arrayValue"] or {}).get("values", [])]
    return None                      # kvlist / bytes: never part of a 5W event


def _attrs(lst):
    if not isinstance(lst, list):
        raise BadRequest("attributes must be a list")
    return {a["key"]: a.get("value") for a in lst if isinstance(a, dict) and isinstance(a.get("key"), str)}


def _ts(nanos):
    try:
        n = int(nanos or 0)
    except (TypeError, ValueError):
        n = 0
    return n / 1e9 if n else datetime.now(timezone.utc).timestamp()


def map_record(attrs, resource, ts, salt):
    """One OTLP log record (raw attribute dicts) -> (candidate 5W event, dropped count)."""
    merged = {**resource, **attrs}
    dropped = sum(1 for k in merged if k not in ALLOWED_KEYS and not k.startswith(ENTITY_PREFIX))
    pick = lambda f: next((v for v in (_any(merged.get(k)) for k in ALLOW[f]) if v not in (None, "", [])), None)
    ev = {"ts": ts, "source": "otlp"}
    for f in ("who", "whom", "what", "where", "why", "agent", "route", "machine", "outcome", "rule_ids"):
        v = pick(f)
        if v is not None:
            ev[f] = [str(x) for x in v] if f == "rule_ids" and isinstance(v, list) else (v if f == "rule_ids" else str(v))
    if "who" not in ev and pick("who_id") is not None:
        ev["who"] = S.pseudonym(pick("who_id"), salt)
    if pick("session_id") is not None:
        ev["session"] = S.pseudonym(pick("session_id"), salt)
    counts = {}
    for k, v in merged.items():
        if k.startswith(ENTITY_PREFIX):
            n = _any(v)
            counts[k[len(ENTITY_PREFIX):]] = n
    if counts:
        ev["entity_counts"] = counts
    for f, d in DEFAULTS.items():
        ev.setdefault(f, d)
    return ev, dropped


def from_otlp(doc, salt):
    if not isinstance(doc, dict) or not isinstance(doc.get("resourceLogs", []), list):
        raise BadRequest("not an OTLP logs document")
    r = Result()
    for rl in doc.get("resourceLogs") or []:
        if not isinstance(rl, dict):
            raise BadRequest("resourceLogs entries must be objects")
        resource = _attrs((rl.get("resource") or {}).get("attributes") or [])
        for sl in rl.get("scopeLogs") or []:
            for i, lr in enumerate((sl or {}).get("logRecords") or []):
                if not isinstance(lr, dict):
                    raise BadRequest("logRecords entries must be objects")
                ev, dropped = map_record(_attrs(lr.get("attributes") or []), resource,
                                         _ts(lr.get("timeUnixNano") or lr.get("observedTimeUnixNano")), salt)
                r.dropped += dropped + (1 if _any(lr.get("body")) not in (None, "") else 0)
                try:
                    r.events.append(S.validate(ev))
                except S.EventError as e:
                    r.rejected += 1
                    r.errors.append({"index": i, "error": str(e)})
    return r


def from_json(payload, actor=None, agent=None):
    """Plain 5W events. With actor (niyantrak.identity.Identity) an event without `who` is stamped with that person,
    their directory id and the agent acting for them; whatever the caller set is kept."""
    items = payload.get("events") if isinstance(payload, dict) and "events" in payload else payload
    items = items if isinstance(items, list) else [items]
    r = Result()
    for i, item in enumerate(items):
        try:
            if actor is not None and isinstance(item, dict) and item.get("who") in (None, ""):
                item = {**item, "who": actor.name, "who_id": actor.stable_id,
                        **({"agent": agent} if agent and not item.get("agent") else {})}
            ev = S.validate(item)
            ev["source"] = "json"
            r.events.append(ev)
        except S.EventError as e:
            r.rejected += 1
            r.errors.append({"index": i, "error": str(e)})
    return r


class SinkHandler(BaseHTTPRequestHandler):
    def log_message(self, *a):       # no request logging: bodies may hold text we refuse to keep
        pass

    def _send(self, code, body):
        data = json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        if self.path.split("?", 1)[0] == "/healthz":
            return self._send(200, {"ok": True})
        return self._send(404, {"error": "not found"})

    def do_POST(self):
        path = self.path.split("?", 1)[0]
        n = int(self.headers.get("Content-Length") or 0)
        if n > MAX_BODY:
            return self._send(413, {"error": "too large"})
        raw = self.rfile.read(n)
        if path not in ("/v1/logs", "/v1/events"):
            return self._send(404, {"error": "not found"})
        ctype = (self.headers.get("Content-Type") or "application/json").split(";")[0].strip().lower()
        if ctype != "application/json":
            return self._send(415, {"error": "send OTLP/HTTP as JSON (exporter encoding: json)"})
        try:
            doc = json.loads(raw or b"{}")
            r = from_otlp(doc, self.server.store.salt()) if path == "/v1/logs" else from_json(doc)
        except (ValueError, BadRequest) as e:
            return self._send(400, {"error": str(e) if isinstance(e, BadRequest) else "bad JSON"})
        if r.events:
            self.server.store.append(r.events)
        if path == "/v1/logs":
            body = {}
            if r.rejected:
                body["partialSuccess"] = {"rejectedLogRecords": r.rejected,
                                          "errorMessage": "; ".join(sorted({e["error"] for e in r.errors}))[:500]}
            return self._send(200, body)
        body = {"accepted": len(r.events), "rejected": r.errors, "dropped": r.dropped}
        return self._send(200 if r.events or not r.rejected else 400, body)


def make_server(store, bind="127.0.0.1", port=4318):
    srv = ThreadingHTTPServer((bind, port), SinkHandler)
    srv.daemon_threads = True
    srv.store = store
    return srv


def serve(store, bind="127.0.0.1", port=4318):
    srv = make_server(store, bind, port)
    print(f"Niyantrak 5W sink: http://{bind}:{srv.server_address[1]}/v1/logs (OTLP JSON) and /v1/events -> {store.root}")
    srv.serve_forever()
