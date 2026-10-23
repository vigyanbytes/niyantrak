"""Panel plugin host: discovery (entry points / NIYANTRAK_PLUGINS), routes under /api/pro/, capabilities that switch the
Pro screens from preview to live, localhost-only mutations, and errors that never take the panel down."""
import http.client
import json
import logging
import pathlib
import threading
from http.server import ThreadingHTTPServer

import pytest

from niyantrak import panel as P
from niyantrak import plugins
from niyantrak.panel import Handler

ROOT = pathlib.Path(__file__).resolve().parents[2]
PRO_SCREENS = ("approvals", "rules", "people", "audit", "compliance", "access")


def serve(host):
    s = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    s.plugin_host = host
    threading.Thread(target=s.serve_forever, daemon=True).start()
    return s


def call(s, method, path, body=None, headers=None):
    c = http.client.HTTPConnection("127.0.0.1", s.server_address[1], timeout=10)
    data = json.dumps(body).encode() if body is not None else b""
    c.putrequest(method, path, skip_accept_encoding=True)
    for k, v in {"Content-Type": "application/json", "Content-Length": str(len(data)), **(headers or {})}.items():
        c.putheader(k, v)
    c.endheaders()
    c.send(data)
    r = c.getresponse()
    out = r.read()
    c.close()
    return r.status, json.loads(out or b"{}"), r


@pytest.fixture
def host():
    return plugins.load(specs=["fake_pro_plugin:register"])


@pytest.fixture
def srv(host):
    s = serve(host)
    yield s
    s.shutdown()


# ── discovery ─────────────────────────────────────────────────────────────────────────────────────────────────────
def test_env_spec_loads_plugin(monkeypatch):
    monkeypatch.setenv("NIYANTRAK_PLUGINS", "fake_pro_plugin:register")
    h = plugins.load()
    assert [p["name"] for p in h.plugins] == ["fake-pro"] and h.plugins[0]["version"] == "9.9"
    assert h.capabilities()["screens"]["approvals"]["live"] is True


def test_no_plugins_means_every_pro_screen_is_preview(monkeypatch):
    monkeypatch.setenv("NIYANTRAK_PLUGINS", "")
    h = plugins.load()
    caps = h.capabilities()
    assert caps["edition"] == "free" and caps["plugins"] == [] and caps["errors"] == []
    assert set(caps["screens"]) == set(PRO_SCREENS)
    assert all(v["live"] is False for v in caps["screens"].values())


class FakeEP:
    def __init__(self, name, value, fn=None, boom=None):
        self.name, self.value, self._fn, self._boom = name, value, fn, boom

    def load(self):
        if self._boom:
            raise self._boom
        return self._fn


def test_entry_points_group_is_used_when_env_unset(monkeypatch):
    import fake_pro_plugin
    monkeypatch.delenv("NIYANTRAK_PLUGINS", raising=False)
    seen = {}

    def eps(group):
        seen["group"] = group
        return [FakeEP("fake", "fake_pro_plugin:register", fake_pro_plugin.register)]
    monkeypatch.setattr(plugins, "_entry_points", eps)
    h = plugins.load()
    assert seen["group"] == "niyantrak.panel_plugins" == plugins.GROUP
    assert h.plugins[0]["name"] == "fake-pro"


def test_entry_point_that_fails_to_import_is_isolated(monkeypatch, caplog):
    monkeypatch.delenv("NIYANTRAK_PLUGINS", raising=False)
    monkeypatch.setattr(plugins, "_entry_points", lambda group: [FakeEP("bad", "nope:register",
                                                                         boom=ImportError("No module named 'nope'"))])
    with caplog.at_level(logging.WARNING, logger="niyantrak.plugins"):
        h = plugins.load()
    assert h.plugins == [] and h.errors[0]["plugin"] == "bad" and "nope" in h.errors[0]["error"]
    assert "bad" in caplog.text


@pytest.mark.parametrize("spec", ["no_such_module_xyz:register", "fake_pro_plugin:missing", "fake_pro_plugin:not_callable",
                                  "fake_pro_plugin", "fake_pro_plugin:register_broken",
                                  "fake_pro_plugin:register_bad_route", "fake_pro_plugin:register_bad_screen"])
def test_bad_plugins_are_recorded_and_contribute_nothing(spec):
    h = plugins.load(specs=[spec])
    assert h.plugins == [] and len(h.errors) == 1 and h.errors[0]["plugin"] == spec
    caps = h.capabilities()
    assert all(v["live"] is False for v in caps["screens"].values())    # register_broken's audit is rolled back
    assert h.match("GET", "/api/pro/audit") is None


def test_good_plugin_survives_a_broken_one():
    h = plugins.load(specs=["fake_pro_plugin:register_broken", "fake_pro_plugin:register"])
    assert [p["name"] for p in h.plugins] == ["fake-pro"] and len(h.errors) == 1
    assert h.capabilities()["screens"]["approvals"]["live"] and h.capabilities()["edition"] == "pro"


def test_route_rules():
    h = plugins.PluginHost()
    reg = h.registrar("x")
    for method, path in (("GET", "/api/node"), ("GET", "/api/proX"), ("TRACE", "/api/pro/a"), ("GET", "/api/pro/../node")):
        with pytest.raises(plugins.PluginError):
            reg.route(method, path, lambda ctx: (200, {}))
    with pytest.raises(plugins.PluginError):
        reg.capability("overview")


# ── capabilities over HTTP ────────────────────────────────────────────────────────────────────────────────────────
def test_capabilities_endpoint(srv):
    code, d, _ = call(srv, "GET", "/api/capabilities")
    assert code == 200 and d["edition"] == "pro"
    assert d["screens"]["approvals"] == {"live": True, "plugin": "fake-pro", "api": "/api/pro/approvals",
                                         "label": "Approvals (live)"}
    assert d["screens"]["people"]["live"] is True
    for s in ("rules", "audit", "compliance", "access"):
        assert d["screens"][s]["live"] is False


def test_capabilities_without_host_attribute_uses_env(monkeypatch):
    monkeypatch.setenv("NIYANTRAK_PLUGINS", "")
    monkeypatch.setattr(P, "_PLUGIN_HOST", None)
    s = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=s.serve_forever, daemon=True).start()
    try:
        code, d, _ = call(s, "GET", "/api/capabilities")
        assert code == 200 and d["edition"] == "free"
        code, d, _ = call(s, "GET", "/api/pro/approvals")
        assert code == 404 and d.get("preview") is True
    finally:
        s.shutdown()


# ── routing ───────────────────────────────────────────────────────────────────────────────────────────────────────
def test_get_route_with_query(srv):
    code, d, _ = call(srv, "GET", "/api/pro/approvals?state=waiting")
    assert code == 200 and d["items"] == [{"id": "PL-1"}] and d["q"] == {"state": "waiting"}


def test_post_route_gets_body_and_context(srv):
    code, d, _ = call(srv, "POST", "/api/pro/approvals/PL-1/approve", {"reason": "ok"})
    assert code == 200 and d == {"echo": {"reason": "ok"}, "local": True, "path": "/api/pro/approvals/PL-1/approve"}


def test_unknown_pro_route_is_404(srv):
    assert call(srv, "GET", "/api/pro/nothing")[0] == 404
    assert call(srv, "POST", "/api/pro/people", {})[0] == 404      # only GET registered there


def test_plugin_enforces_its_own_roles(srv):
    assert call(srv, "GET", "/api/pro/people")[0] == 403
    assert call(srv, "GET", "/api/pro/people", headers={"X-Role": "owner"})[0] == 200


def test_headers_and_cookies_pass_through(srv):
    code, d, r = call(srv, "GET", "/api/pro/cookie", headers={"Cookie": "s=abc"})
    assert code == 200 and d["cookie"] == "s=abc" and "HttpOnly" in r.getheader("Set-Cookie")
    assert r.getheader("Cache-Control") == "no-store"


def test_mutations_are_localhost_only_in_the_free_host(srv, monkeypatch):
    monkeypatch.setattr(P, "LOCAL_ADDRESSES", frozenset())
    code, d, _ = call(srv, "POST", "/api/pro/approvals/PL-1/approve", {})
    assert code == 403 and "this machine" in d["error"]
    assert call(srv, "GET", "/api/pro/approvals")[0] == 200          # reads are fine from the LAN


def test_plugin_exception_is_isolated_and_logged(srv, caplog):
    with caplog.at_level(logging.ERROR, logger="niyantrak.plugins"):
        code, d, _ = call(srv, "GET", "/api/pro/boom")
    assert code == 500 and d["degraded"] is True and "database exploded" not in json.dumps(d)
    assert "database exploded" in caplog.text
    assert call(srv, "GET", "/api/capabilities")[1]["screens"]["approvals"]["live"] is True   # panel keeps running
    assert call(srv, "GET", "/api/peers")[0] == 200


def test_bad_return_value_is_a_500(host):
    reg = host.registrar("odd")
    reg.route("GET", "/api/pro/odd", lambda ctx: "not a tuple")
    host.commit(reg)
    s = serve(host)
    try:
        code, d, _ = call(s, "GET", "/api/pro/odd")
        assert code == 500 and d["degraded"] is True
    finally:
        s.shutdown()


def test_bad_json_body_is_400(srv):
    c = http.client.HTTPConnection("127.0.0.1", srv.server_address[1], timeout=10)
    c.request("POST", "/api/pro/approvals", body=b"{not json", headers={"Content-Type": "application/json"})
    assert c.getresponse().status == 400


def test_join_listener_never_routes_to_plugins():
    assert P.JoinHandler.do_GET is not Handler.do_GET and P.JoinHandler.do_POST is not Handler.do_POST


# ── boundary: the public tree never imports the commercial packages ───────────────────────────────────────────────
def test_public_tree_never_imports_commercial_packages():
    import ast
    bad = []
    for f in ROOT.rglob("*.py"):
        rel = f.relative_to(ROOT)
        if rel.parts[0] in (".venv", "venv", "build", "dist", ".git", "node_modules") or ".venv" in rel.parts:
            continue
        tree = ast.parse(f.read_text(encoding="utf-8"), str(f))
        for n in ast.walk(tree):
            names = []
            if isinstance(n, ast.Import):
                names = [a.name for a in n.names]
            elif isinstance(n, ast.ImportFrom) and n.module and n.level == 0:
                names = [n.module]
            elif isinstance(n, ast.Call) and getattr(n.func, "attr", getattr(n.func, "id", None)) in (
                    "import_module", "__import__") and n.args and isinstance(n.args[0], ast.Constant):
                names = [str(n.args[0].value)]
            bad += [f"{rel}:{n.lineno} {m}" for m in names if m.split(".")[0].startswith("niyantrak_")]
    assert bad == [], "the free edition must not import the commercial packages: " + ", ".join(bad)


# ── web app ───────────────────────────────────────────────────────────────────────────────────────────────────────
def test_web_app_switches_pro_screens_on_capabilities():
    js = (ROOT / "niyantrak" / "web" / "app.js").read_text()
    page = (ROOT / "niyantrak" / "web" / "index.html").read_text()
    assert 'api("capabilities")' in js and "function applyCaps" in js and "const isLive" in js
    for screen in ("approvals", "rules", "people", "audit", "compliance"):
        assert f'live-{screen}' in page, screen                       # a live container per screen
    assert ".lock" in js and "remove()" in js                         # the Pro pill goes away when live
    assert '"api/pro/"' in js and all(f'pro("{p}")' in js for p in ("session", "approvals", "people", "rules", "audit"))
    assert "degraded" in js                                           # a plugin error shows a degraded state
    assert "</script" not in js and "<!--" not in js
