"""Privacy: Aadhaar / IBAN / email / health identifiers (NHS, ABHA, KVNR, NPI) in a forbidden field or a label is rejected or dropped and never reaches disk."""
import json
import os
import threading
import urllib.error
import urllib.request

import pytest

pytest.importorskip("pyarrow")
pytest.importorskip("duckdb")

from niyantrak.telemetry import sink as K  # noqa: E402
from niyantrak.telemetry import store as T  # noqa: E402

from telemetry_helpers import ABHA_ADDRESS, EMAIL, IBAN, KVNR, NHS, NPI, aadhaar, event, otlp  # noqa: E402

VALUES = [aadhaar(), IBAN, EMAIL, NHS, ABHA_ADDRESS, KVNR, NPI]


def raw_values():
    out = set(VALUES)
    for v in VALUES:
        out.add(v.replace(" ", ""))
    return out


def disk_bytes(root):
    blob = b""
    for d, _, files in os.walk(root):
        for f in files:
            blob += open(os.path.join(d, f), "rb").read()
    return blob


def test_pii_never_stored(tmp_path):
    st = T.Store(str(tmp_path / "tel"), writer="sink")
    srv = K.make_server(st, "127.0.0.1", 0)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{srv.server_address[1]}"

    def post(path, body):
        req = urllib.request.Request(url + path, data=json.dumps(body).encode(), headers={"Content-Type": "application/json"})
        try:
            return urllib.request.urlopen(req, timeout=10).status
        except urllib.error.HTTPError as e:
            return e.code
    try:
        for v in VALUES:
            # forbidden fields in plain JSON: the whole event is rejected
            assert post("/v1/events", [event(message=f"customer {v}")]) == 400
            assert post("/v1/events", [event(customer_id=v)]) == 400
            # identifier inside an allowed label: rejected
            assert post("/v1/events", [event(whom=v)]) == 400
            # OTLP: body and unknown attributes dropped, the record itself kept
            assert post("/v1/logs", otlp([{"_body": f"pay {v}", "gen_ai.prompt": v, "user.email": v,
                                           "niyantrak.who": "Support bot", "niyantrak.what": "Refund request"}])) == 200
            # OTLP: identifier in an allowed attribute -> record rejected
            assert post("/v1/logs", otlp([{"niyantrak.why": v}])) == 200
            # user id that IS an identifier value is pseudonymised, never stored as is
            assert post("/v1/logs", otlp([{"user.id": v, "niyantrak.what": "Login"}])) == 200
    finally:
        srv.shutdown()
    assert st.count() == 2 * len(VALUES)
    st.compact(month="2025-10")
    blob = disk_bytes(st.root)
    for v in raw_values():
        assert v.encode() not in blob, "identifier value reached disk"
    assert b"customer" not in blob and b"pay " not in blob
