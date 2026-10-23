"""Sink: OTLP/HTTP JSON logs and plain JSON events -> 5W; anything outside the allow-list is dropped."""
import json
import threading
import urllib.error
import urllib.request

import pytest

from niyantrak.telemetry import schema as S
from niyantrak.telemetry import sink as K

from telemetry_helpers import EMAIL, IBAN, aadhaar, event, otlp

SALT = "test-salt"


def test_otlp_maps_gen_ai_and_ids_to_5w():
    doc = otlp([{"gen_ai.operation.name": "chat", "gen_ai.agent.name": "Support bot", "gen_ai.provider.name": "openai",
                 "gen_ai.request.model": "gpt-x", "user.id": "u-1001", "session.id": "conv-77",
                 "niyantrak.why": "RB-ROUTE-001 mask personal data", "niyantrak.outcome": "masked",
                 "niyantrak.rule_ids": ["RB-ROUTE-001"], "niyantrak.entity.EMAIL": 3, "niyantrak.entity.IBAN": 1}],
               resource={"service.name": "support-gateway", "host.name": "edge-01"})
    r = K.from_otlp(doc, SALT)
    assert r.rejected == 0 and len(r.events) == 1
    e = r.events[0]
    assert e["what"] == "chat" and e["agent"] == "Support bot" and e["where"] == "openai" and e["route"] == "gpt-x"
    assert e["who"] == S.pseudonym("u-1001", SALT) and e["session"] == S.pseudonym("conv-77", SALT)
    assert e["machine"] == "edge-01" and e["outcome"] == "masked" and e["rule_ids"] == ["RB-ROUTE-001"]
    assert e["entity_counts"] == {"EMAIL": 3, "IBAN": 1} and e["source"] == "otlp"
    assert e["ts"].startswith("2025-10-20T10:00:00")
    assert "u-1001" not in json.dumps(e) and "conv-77" not in json.dumps(e)


def test_otlp_labels_win_and_defaults_fill_in():
    doc = otlp([{"niyantrak.who": "Clinic bot", "event.name": "answer"}], resource={"service.name": "whatsapp-gateway"})
    e = K.from_otlp(doc, SALT).events[0]
    assert e["who"] == "Clinic bot" and e["what"] == "answer" and e["agent"] == "whatsapp-gateway"
    assert e["where"] == "unspecified" and e["why"] == "unspecified" and e["outcome"] == "allowed"


def test_otlp_body_and_unknown_attributes_are_dropped():
    secret_text = f"my aadhaar is {aadhaar()} and iban {IBAN}"
    doc = otlp([{"_body": secret_text, "gen_ai.prompt": secret_text, "gen_ai.completion": "ok", "user.email": EMAIL,
                 "niyantrak.who": "Support bot", "niyantrak.what": "Refund request"}])
    r = K.from_otlp(doc, SALT)
    assert len(r.events) == 1 and r.dropped == 4          # body + 3 attributes outside the allow-list
    blob = json.dumps(r.events)
    assert aadhaar() not in blob and IBAN not in blob and EMAIL not in blob and "my aadhaar" not in blob


def test_otlp_record_with_pii_in_allowed_label_is_rejected():
    r = K.from_otlp(otlp([{"niyantrak.who": EMAIL}, {"niyantrak.who": "Support bot"}]), SALT)
    assert r.rejected == 1 and len(r.events) == 1 and EMAIL not in json.dumps(r.errors)


def test_otlp_bad_shape():
    with pytest.raises(K.BadRequest):
        K.from_otlp(["not", "otlp"], SALT)


def test_plain_json_single_list_and_wrapped():
    for payload in (event(), [event(), event()], {"events": [event()]}):
        r = K.from_json(payload)
        assert r.rejected == 0 and r.events and all(e["source"] == "json" for e in r.events)


def test_plain_json_strict_rejects_forbidden_fields():
    r = K.from_json([event(), event(message=f"card {IBAN}")])
    assert len(r.events) == 1 and r.rejected == 1 and "message" in r.errors[0]["error"] and IBAN not in json.dumps(r.errors)


# ── HTTP sink ────────────────────────────────────────────────────────────────────────────────────────────
class FakeStore:
    def __init__(self):
        self.batches = []

    def append(self, events):
        self.batches.append(list(events))
        return "segments/x.parquet"

    def salt(self):
        return SALT


@pytest.fixture
def sink():
    st = FakeStore()
    srv = K.make_server(st, "127.0.0.1", 0)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield st, f"http://127.0.0.1:{srv.server_address[1]}"
    srv.shutdown()


def post(url, body, ctype="application/json"):
    data = body if isinstance(body, bytes) else json.dumps(body).encode()
    req = urllib.request.Request(url, data=data, headers={"Content-Type": ctype})
    try:
        r = urllib.request.urlopen(req, timeout=10)
        return r.status, json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b"{}")


def test_http_otlp_logs(sink):
    st, url = sink
    code, body = post(url + "/v1/logs", otlp([{"niyantrak.who": "Support bot"}, {"niyantrak.who": EMAIL}]))
    assert code == 200 and body["partialSuccess"]["rejectedLogRecords"] == 1
    assert len(st.batches) == 1 and st.batches[0][0]["who"] == "Support bot"


def test_http_events_and_errors(sink):
    st, url = sink
    assert post(url + "/v1/events", [event()])[0] == 200
    code, body = post(url + "/v1/events", [event(text="free text")])
    assert code == 400 and body["accepted"] == 0
    assert post(url + "/v1/logs", b"\x0a\x00", "application/x-protobuf")[0] == 415
    assert post(url + "/v1/logs", b"{not json")[0] == 400
    assert post(url + "/v1/other", {})[0] == 404
    assert len(st.batches) == 1
