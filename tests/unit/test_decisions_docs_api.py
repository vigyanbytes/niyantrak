"""Panel: GET /api/decisions, GET /api/docs, GET /docs/<file>, POST /api/docs/regenerate (this machine only)."""
import http.client
import json
import os
import pathlib
import threading
from http.server import ThreadingHTTPServer

import pytest

from niyantrak import docs
from niyantrak import panel as P
from niyantrak.decisions.store import Store
from niyantrak.panel import Handler

ROOT = pathlib.Path(__file__).resolve().parents[2]
FIX = pathlib.Path(__file__).parent / "fixtures" / "docs"


@pytest.fixture
def srv(tmp_path):
    s = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    s.decisions_root = str(tmp_path / "dg")
    s.docs_dir = str(tmp_path / "docs")
    s.join_store = str(tmp_path / "join.json")
    threading.Thread(target=s.serve_forever, daemon=True).start()
    yield s
    s.shutdown()


def call(s, method, path, body=None):
    c = http.client.HTTPConnection("127.0.0.1", s.server_address[1], timeout=10)
    c.putrequest(method, path, skip_accept_encoding=True)
    data = json.dumps(body).encode() if body is not None else b""
    c.putheader("Content-Type", "application/json")
    c.putheader("Content-Length", str(len(data)))
    c.endheaders()
    c.send(data)
    r = c.getresponse()
    out = r.read()
    c.close()
    return r.status, r.getheader("Content-Type"), out, r


def test_api_decisions_empty(srv):
    code, ctype, body, _ = call(srv, "GET", "/api/decisions")
    d = json.loads(body)
    assert code == 200 and ctype.startswith("application/json")
    assert d["empty"] is True and d["nodes"] == [] and d["open"] == [] and "No decisions recorded yet" in d["message"]


def test_api_decisions_populated(srv):
    Store(srv.decisions_root).append([
        {"ts": "2026-01-01T00:00:00", "kind": "DECISION", "src": "DEC-T1", "title": "Old"},
        {"ts": "2026-01-02T00:00:00", "kind": "DECISION", "src": "DEC-T2", "title": "New"},
        {"ts": "2026-01-02T00:00:01", "kind": "SUPERSEDED_BY", "src": "DEC-T1", "dst": "DEC-T2"},
        {"ts": "2026-01-03T00:00:00", "kind": "WORK", "src": "WORK-T1", "title": "Blocked thing"},
        {"ts": "2026-01-03T00:00:01", "kind": "STATUS", "src": "WORK-T1", "title": "blocked"}], writer="test")
    code, _, body, _ = call(srv, "GET", "/api/decisions")
    d = json.loads(body)
    assert code == 200 and d["empty"] is False
    assert {n["id"]: n["status"] for n in d["nodes"]} == {"DEC-T1": "superseded", "DEC-T2": "in force", "WORK-T1": "blocked"}
    assert d["links"] == [{"source": "DEC-T1", "target": "DEC-T2", "kind": "SUPERSEDED_BY"}]
    assert [(g["key"], [i["id"] for i in g["items"]]) for g in d["open"]] == [("w:blocked", ["WORK-T1"])]


def test_api_docs_empty_then_regenerate(srv):
    code, _, body, _ = call(srv, "GET", "/api/docs")
    d = json.loads(body)
    assert code == 200 and d["pages"] == [] and d["empty"] is True
    join = json.loads((FIX / "input.json").read_text())["join"]
    pathlib.Path(srv.join_store).write_text(json.dumps(join))
    code, _, body, _ = call(srv, "POST", "/api/docs/regenerate", {})
    d = json.loads(body)
    assert code == 200 and d["empty"] is False and any(p["title"] == "gpu-01" for p in d["pages"])
    code, ctype, body, r = call(srv, "GET", "/docs/index.html")
    assert code == 200 and ctype.startswith("text/html") and b"Fleet as built" in body
    assert "default-src 'none'" in r.getheader("Content-Security-Policy")
    code, ctype, body, _ = call(srv, "GET", "/docs/network-map.svg")
    assert code == 200 and ctype.startswith("image/svg+xml")
    code, ctype, body, _ = call(srv, "GET", "/docs/index.md")
    assert code == 200 and ctype.startswith("text/markdown")


def test_docs_files_confined(srv, tmp_path):
    docs.write(srv.docs_dir, docs.render(docs.collect({})))
    (tmp_path / "secret.txt").write_text("TOP-SECRET")
    for bad in ("/docs/../secret.txt", "/docs/%2e%2e/secret.txt", "/docs/..%2fsecret.txt", "/docs//etc/passwd", "/docs/"):
        code, _, body, _ = call(srv, "GET", bad)
        assert code == 404 and b"TOP-SECRET" not in body, bad


def test_regenerate_refused_off_localhost(srv, monkeypatch):
    monkeypatch.setattr(P, "LOCAL_ADDRESSES", frozenset())
    code, _, body, _ = call(srv, "POST", "/api/docs/regenerate", {})
    assert code == 403 and "this machine" in json.loads(body)["error"]
    assert not os.path.exists(srv.docs_dir)


def test_join_listener_does_not_expose_new_routes():
    assert P.JoinHandler.do_GET is not Handler.do_GET          # the join listener keeps its own tiny GET


def test_panel_has_decisions_and_docs_screens():
    page = (ROOT / "niyantrak" / "web" / "index.html").read_text()
    gov = page.split('<div class="navgroup">Govern AI</div>', 1)[1].split('<div class="spacer">', 1)[0]
    assert 'data-p="decisions">Decisions' in gov
    assert 'data-p="docs">' in page and 'id="decisions"' in page and 'id="docs"' in page
    assert 'id="dg-chips"' in page and 'id="dg-search"' in page and 'id="dg-open"' in page and 'id="dg-empty"' in page
    js = (ROOT / "niyantrak" / "web" / "app.js").read_text()
    assert 'api("decisions")' in js and 'api("docs")' in js and 'api("docs/regenerate"' in js
    assert "</script" not in js and "<!--" not in js                   # tools/build-demo.py inlines app.js
