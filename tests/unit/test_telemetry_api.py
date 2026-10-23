"""Panel GET /api/activity: empty store (and no telemetry extra) -> empty; populated -> the chart shapes."""
import json
import threading
import urllib.error
import urllib.request
from datetime import datetime, timezone
from http.server import ThreadingHTTPServer

import pytest

from niyantrak import panel as P

from telemetry_helpers import event


def start(tel_dir):
    srv = ThreadingHTTPServer(("127.0.0.1", 0), P.Handler)
    srv.telemetry_dir = str(tel_dir)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, f"http://127.0.0.1:{srv.server_address[1]}"


def get(url):
    return json.load(urllib.request.urlopen(url, timeout=10))


def test_activity_empty_store(tmp_path):
    srv, url = start(tmp_path / "tel")
    try:
        d = get(url + "/api/activity?days=7")
        assert d["empty"] is True and d["reason"]
    finally:
        srv.shutdown()


def test_activity_without_telemetry_extra(tmp_path, monkeypatch):
    from niyantrak.telemetry import store as T
    monkeypatch.setattr(T, "available", lambda: False)
    srv, url = start(tmp_path / "tel")
    try:
        d = get(url + "/api/activity")
        assert d["empty"] is True and "telemetry" in d["reason"]
    finally:
        srv.shutdown()


def test_activity_populated_and_filtered(tmp_path):
    pytest.importorskip("pyarrow")
    pytest.importorskip("duckdb")
    from niyantrak.telemetry import store as T
    today = datetime.now(timezone.utc).strftime("%Y-%m-%dT08:00:00Z")
    T.Store(str(tmp_path / "tel"), writer="t").append([event(ts=today), event(ts=today, who="Clinic bot")])
    srv, url = start(tmp_path / "tel")
    try:
        d = get(url + "/api/activity?days=7")
        assert d["empty"] is False and d["total"] == 2 and d["days"] == 7
        assert {"sankey", "week", "why", "rules", "infra", "by"} <= set(d)
        assert len(d["week"]["days"]) == 7
        f = get(url + "/api/activity?days=7&k=who&v=Clinic%20bot")
        assert f["total"] == 1
        assert get(url + "/api/activity?days=999")["days"] == 90
        try:
            urllib.request.urlopen(url + "/api/activity?k=message&v=x", timeout=10)
            raise AssertionError("expected 400")
        except urllib.error.HTTPError as e:
            assert e.code == 400 and json.load(e)["error"]
    finally:
        srv.shutdown()


def test_activity_tampered_store_reports_integrity(tmp_path):
    pytest.importorskip("pyarrow")
    pytest.importorskip("duckdb")
    import os
    from niyantrak.telemetry import store as T
    rel = T.Store(str(tmp_path / "tel"), writer="t").append([event()])[0]
    with open(os.path.join(tmp_path, "tel", rel), "ab") as f:
        f.write(b"x")
    srv, url = start(tmp_path / "tel")
    try:
        d = get(url + "/api/activity")
        assert d["empty"] is True and d["integrity"] == "failed"
    finally:
        srv.shutdown()


def test_demo_build_keeps_sample_activity(tmp_path):
    import importlib.util
    import os
    spec = importlib.util.spec_from_file_location("build_demo", os.path.join(os.path.dirname(P.__file__), "..", "tools", "build-demo.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    html = mod.build(str(tmp_path / "demo.html"))
    assert "Sample activity" in html and '=== "activity"' in html
