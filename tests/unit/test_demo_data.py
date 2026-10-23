"""tools/demo-data.py: deterministic, valid, and fictional through and through."""
import importlib.util
import ipaddress
import json
import os

import pytest

pytest.importorskip("pyarrow")
pytest.importorskip("duckdb")

from niyantrak.telemetry import schema as S  # noqa: E402

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
spec = importlib.util.spec_from_file_location("demo_data", os.path.join(ROOT, "tools", "demo-data.py"))
demo = importlib.util.module_from_spec(spec)
spec.loader.exec_module(demo)
END = demo.date(2026, 10, 23)
DOC_NETS = [ipaddress.ip_network(n) for n in ("192.0.2.0/24", "198.51.100.0/24", "2001:db8::/32")]


def test_same_seed_same_bytes(tmp_path):
    a, b = tmp_path / "a", tmp_path / "b"
    demo.build(str(a), END)
    demo.build(str(b), END)
    for f in ("events.json", "decisions.jsonl", "bundle.json"):
        assert (a / f).read_bytes() == (b / f).read_bytes(), f
    demo.build(str(b), END, seed=8)
    assert (a / "events.json").read_bytes() != (b / "events.json").read_bytes()


def test_events_are_valid_and_inside_the_window(tmp_path):
    b = demo.build(str(tmp_path), END)
    events = json.loads((tmp_path / "events.json").read_text())
    assert len(events) == b["events"] > 500
    for e in events:
        S.validate(e)
        assert "2026-10-10" <= e["ts"][:10] <= "2026-10-23"
    agents = {e["agent"] for e in events}
    assert {"Claude Code", "Codex", "Antigravity"} <= agents
    assert {o for e in events for o in [e["outcome"]]} >= {"allowed", "blocked", "masked", "local", "needs_approval", "approved"}


def test_only_fictional_people_machines_and_documentation_addresses(tmp_path):
    b = demo.build(str(tmp_path), END)
    events = json.loads((tmp_path / "events.json").read_text())
    people = set(demo.PEOPLE) | {"support-bot"}
    machines = {f[0] for f in demo.FLEET}
    assert {e["who"] for e in events} <= people
    assert {e["machine"] for e in events} <= machines
    hosts = [b["node"]] + list(b["peers"].values())
    for n in hosts:
        for addr in n["ipv4"] + n["ipv6"]:
            assert any(ipaddress.ip_address(addr) in net for net in DOC_NETS), addr
    blob = (tmp_path / "events.json").read_text() + (tmp_path / "decisions.jsonl").read_text()
    assert "@" not in blob.replace("@example", "")               # no email-shaped strings anywhere


def test_stores_verify_and_bundle_is_labelled(tmp_path):
    from niyantrak.decisions.store import Store as DecisionStore
    from niyantrak.telemetry.store import Store
    b = demo.build(str(tmp_path), END)
    assert Store(str(tmp_path / "telemetry")).verify() == []
    assert DecisionStore(str(tmp_path / "decisions")).verify()[0]
    assert b["label"].startswith("Sample data") and b["activity"]["sample"] == b["label"]
    assert b["activity"]["total"] > 0 and b["activity"]["to"] == "2026-10-23"
    statuses = {n["status"] for n in b["decisions"]["nodes"] if n["kind"] == "DECISION"}
    assert statuses == {"in force", "pending", "superseded", "retired"}


def test_build_demo_embeds_the_bundle(tmp_path):
    spec2 = importlib.util.spec_from_file_location("build_demo", os.path.join(ROOT, "tools", "build-demo.py"))
    bd = importlib.util.module_from_spec(spec2)
    spec2.loader.exec_module(bd)
    demo.build(str(tmp_path / "d"), END)
    html = bd.build(str(tmp_path / "demo.html"), bundle=str(tmp_path / "d" / "bundle.json"))
    assert "window.NIYANTRAK_DEMO_DATA = {" in html and "const DEMO = true;" in html
    assert html.index("window.NIYANTRAK_DEMO_DATA") < html.index("window.niyantrakApi = async function")
    assert "Sample data" in html and "laptop-asha" in html
    plain = bd.build(str(tmp_path / "plain.html"))
    assert "window.NIYANTRAK_DEMO_DATA = {" not in plain
