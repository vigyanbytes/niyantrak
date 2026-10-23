"""Decision graph: append-only event store, derived statuses, open items, graph export, local-only `ask`.

All fixtures are synthetic (ids DEC-T*/WORK-T*); no real decision content.
"""
import json
import os

import pytest

from niyantrak.decisions import ask as askmod
from niyantrak.decisions import graph, schema
from niyantrak.decisions.store import Store


def ev(kind, src, dst=None, ts="2026-01-01T00:00:00", **kw):
    return {"ts": ts, "kind": kind, "src": src, "dst": dst, **kw}


def sample_rows():
    """Two decisions (one superseded), a pending decision, a retired one, and work in every bucket."""
    return [
        ev("DECISION", "DEC-T1", title="Use a single queue table", ts="2026-01-01T10:00:00", user_id="u-ops", agent_id="agent-a", product="demo"),
        ev("DECISION", "DEC-T2", title="Use a queue per tenant", ts="2026-01-05T10:00:00"),
        ev("SUPERSEDED_BY", "DEC-T1", "DEC-T2", ts="2026-01-05T10:00:01"),
        ev("DECISION", "DEC-T3", title="Pick a backup window", ts="2026-01-06T10:00:00"),
        ev("STATUS", "DEC-T3", title="to do", text="pending", ts="2026-01-06T10:00:01"),
        ev("DECISION", "DEC-T4", title="Old naming rule", ts="2026-01-02T10:00:00"),
        ev("RETIRED", "DEC-T4", ts="2026-01-03T10:00:00"),
        ev("WORK", "WORK-T1", title="Write the queue migration", ts="2026-01-07T10:00:00"),
        ev("STATUS", "WORK-T1", title="in progress", ts="2026-01-07T10:00:01"),
        ev("WORK", "WORK-T2", title="Load test", ts="2026-01-07T11:00:00"),
        ev("STATUS", "WORK-T2", title="blocked", ts="2026-01-07T11:00:01"),
        ev("WORK", "WORK-T3", title="Draft the runbook", ts="2026-01-07T12:00:00"),
        ev("STATUS", "WORK-T3", title="proposed", ts="2026-01-07T12:00:01"),
        ev("WORK", "WORK-T4", title="Pick a library", ts="2026-01-07T13:00:00"),
        ev("STATUS", "WORK-T4", title="to do", ts="2026-01-07T13:00:01"),
        ev("STATUS", "WORK-T4", title="done", ts="2026-01-08T13:00:01"),
        ev("WORK", "WORK-T5", title="Dropped idea", ts="2026-01-07T14:00:00"),
        ev("STATUS", "WORK-T5", title="dropped", ts="2026-01-07T14:00:01"),
        ev("WORK", "WORK-T6", title="Unstarted item", ts="2026-01-07T15:00:00"),
        ev("THING", "queue", title="Queue service"),
        ev("ABOUT", "DEC-T2", "queue"),
        ev("REFERENCES", "WORK-T1", "DEC-T2"),
        ev("DECIDED_IN", "DEC-T2", "sess-001"),
        ev("REFERENCES", "WORK-T1", "NOT-A-NODE"),          # dangling: dropped from the graph
    ]


@pytest.fixture
def store(tmp_path):
    s = Store(str(tmp_path / "dg"))
    s.append(sample_rows(), writer="test")
    return s


# ── schema / privacy ──────────────────────────────────────────────────────────────────────────────────────
def test_schema_has_actor_fields():
    for f in ("ts", "session_id", "op", "kind", "src", "dst", "title", "text", "written_by", "user_id", "agent_id", "product"):
        assert f in schema.FIELDS


def test_normalize_stamps_writer_and_actor_from_env():
    r = schema.normalize({"kind": "DECISION", "src": "DEC-T9", "title": "x", "written_by": "spoofed"}, writer="hook",
                         env={"NIYANTRAK_USER": "u-1", "NIYANTRAK_AGENT": "agent-x", "NIYANTRAK_PRODUCT": "p", "NIYANTRAK_SESSION_ID": "s-1"})
    assert r["written_by"] == "hook"                       # stamped by the store, never by the caller
    assert (r["user_id"], r["agent_id"], r["product"], r["session_id"]) == ("u-1", "agent-x", "p", "s-1")
    assert r["op"] == "add" and r["ts"] and set(r) == set(schema.FIELDS)


def test_normalize_rejects_bad_events():
    with pytest.raises(schema.EventError):
        schema.normalize({"kind": "NOPE", "src": "A"}, writer="t", env={})
    with pytest.raises(schema.EventError):
        schema.normalize({"kind": "SUPERSEDED_BY", "src": "A"}, writer="t", env={})      # edge without dst
    with pytest.raises(schema.EventError):
        schema.normalize({"kind": "DECISION", "src": ""}, writer="t", env={})
    with pytest.raises(schema.EventError):
        schema.normalize({"kind": "DECISION", "src": "A", "op": "delete"}, writer="t", env={})


def test_secrets_are_refused_and_nothing_written(tmp_path):
    s = Store(str(tmp_path / "dg"))
    with pytest.raises(schema.PrivacyError) as e:
        s.append([ev("DECISION", "DEC-T9", title="rotate", text="api_key = sk-" + "A" * 30)], writer="t")
    assert "sk-AAAA" not in str(e.value)                    # the refusal never echoes the value
    assert not s.exists() and s.segments() == []


def test_personal_identifiers_are_refused(tmp_path):
    s = Store(str(tmp_path / "dg"))
    with pytest.raises(schema.PrivacyError) as e:
        s.append([ev("DECISION", "DEC-T9", title="Refund", text="customer PAN ABCPE1234F asked")], writer="t")
    assert "PAN" in str(e.value) and "ABCPE1234F" not in str(e.value)
    with pytest.raises(schema.PrivacyError):
        s.append([ev("DECISION", "DEC-T9", title="x", user_id="someone@example.com")], writer="t")
    assert s.segments() == []


# ── store ────────────────────────────────────────────────────────────────────────────────────────────────
def test_append_only_segments_and_manifest(store):
    first = store.segments()
    assert len(first) == 1
    store.append([ev("WORK", "WORK-T7", title="Another")], writer="test")
    segs = store.segments()
    assert len(segs) == 2 and segs[0] == first[0]           # earlier segment untouched
    lines = [json.loads(l) for l in open(os.path.join(store.root, "manifest.jsonl"))]
    assert [l["rows"] for l in lines] == [len(sample_rows()), 1] and all(len(l["sha256"]) == 64 for l in lines)
    assert store.verify() == (True, [])
    assert len(store.events()) == len(sample_rows()) + 1


def test_verify_detects_tampering(store):
    seg = os.path.join(store.root, store.segments()[0])
    with open(seg, "ab") as f:
        f.write(b"x")
    ok, bad = store.verify()
    assert not ok and bad == [store.segments()[0]]


def test_parquet_segments_when_pyarrow_present(tmp_path):
    pytest.importorskip("pyarrow")
    s = Store(str(tmp_path / "dg"))
    s.append(sample_rows(), writer="t")
    assert s.segments()[0].endswith(".parquet")
    assert graph.derive(s.events())["decisions"]["DEC-T1"]["status"] == "superseded"


def test_works_without_pyarrow(tmp_path, monkeypatch):
    from niyantrak.decisions import store as storemod
    monkeypatch.setattr(storemod, "_pyarrow", lambda: None)
    s = Store(str(tmp_path / "dg"))
    s.append(sample_rows(), writer="t")
    assert s.segments()[0].endswith(".jsonl")
    assert graph.derive(s.events())["decisions"]["DEC-T2"]["status"] == "in force"


def test_mixed_segment_formats_read_together(tmp_path, monkeypatch):
    pytest.importorskip("pyarrow")
    from niyantrak.decisions import store as storemod
    s = Store(str(tmp_path / "dg"))
    s.append(sample_rows()[:3], writer="t")
    monkeypatch.setattr(storemod, "_pyarrow", lambda: None)
    s.append(sample_rows()[3:], writer="t")
    monkeypatch.undo()                                      # reader has pyarrow again
    assert {p.rsplit(".", 1)[1] for p in s.segments()} == {"parquet", "jsonl"}
    assert graph.derive(s.events())["decisions"]["DEC-T1"]["status"] == "superseded"


# ── status derivation ────────────────────────────────────────────────────────────────────────────────────
def test_decision_statuses(store):
    d = graph.derive(store.events())["decisions"]
    assert d["DEC-T1"]["status"] == "superseded" and d["DEC-T1"]["superseded_by"] == ["DEC-T2"]
    assert d["DEC-T2"]["status"] == "in force"
    assert d["DEC-T3"]["status"] == "pending"
    assert d["DEC-T4"]["status"] == "retired"


def test_work_statuses_latest_status_wins(store):
    w = graph.derive(store.events())["work"]
    assert {k: v["status"] for k, v in w.items()} == {
        "WORK-T1": "in progress", "WORK-T2": "blocked", "WORK-T3": "proposed",
        "WORK-T4": "done", "WORK-T5": "dropped", "WORK-T6": "to do"}


def test_retracting_supersession_restores_in_force(store):
    store.append([ev("SUPERSEDED_BY", "DEC-T1", "DEC-T2", op="retract", ts="2026-02-01T00:00:00")], writer="t")
    assert graph.derive(store.events())["decisions"]["DEC-T1"]["status"] == "in force"
    store.append([ev("SUPERSEDED_BY", "DEC-T1", "DEC-T2", ts="2026-02-02T00:00:00")], writer="t")   # add after retract: live again
    assert graph.derive(store.events())["decisions"]["DEC-T1"]["status"] == "superseded"


def test_pending_decision_closed_by_done_status(store):
    store.append([ev("STATUS", "DEC-T3", title="done", ts="2026-02-01T00:00:00")], writer="t")
    assert graph.derive(store.events())["decisions"]["DEC-T3"]["status"] == "in force"


def test_bucket_maps_raw_ledger_words():
    assert graph.bucket("idea") == "proposed" and graph.bucket("agreed") == "to do"
    assert graph.bucket("in-progress") == "in progress" and graph.bucket("on-hold") == "blocked"
    assert graph.bucket("completed") == "done" and graph.bucket("deferred") == "dropped"
    assert graph.bucket("") == "to do" and graph.bucket("", archived=True) == "done"


# ── open items ───────────────────────────────────────────────────────────────────────────────────────────
def test_open_items_exact_lists(store):
    groups = {g["key"]: [i["id"] for i in g["items"]] for g in graph.open_items(graph.derive(store.events()))}
    assert groups == {"d:pending": ["DEC-T3"], "w:blocked": ["WORK-T2"], "w:in progress": ["WORK-T1"],
                      "w:proposed": ["WORK-T3"], "w:to do": ["WORK-T6"]}


# ── materialize / export ─────────────────────────────────────────────────────────────────────────────────
def test_materialize_is_idempotent(store):
    paths = graph.materialize(store)
    before = {p: open(p, "rb").read() for p in paths}
    assert any(p.endswith("graph.json") for p in paths)
    graph.materialize(store)
    assert {p: open(p, "rb").read() for p in paths} == before
    for p in paths:                                         # state/ is never the truth: delete and rebuild
        os.unlink(p)
    graph.materialize(store)
    assert {p: open(p, "rb").read() for p in paths} == before


def test_export_graph_shape(store):
    g = graph.export_graph(graph.derive(store.events()))
    assert set(g) >= {"nodes", "links", "counts", "open", "empty"} and g["empty"] is False
    ids = {n["id"] for n in g["nodes"]}
    assert {"DEC-T1", "WORK-T6", "queue", "sess-001"} <= ids and "NOT-A-NODE" not in ids
    for n in g["nodes"]:
        assert set(n) >= {"id", "kind", "status", "title", "ts", "user", "agent", "product"}
        assert n["kind"] in ("DECISION", "WORK", "THING", "SESSION")
    for l in g["links"]:
        assert l["source"] in ids and l["target"] in ids and l["kind"] in schema.EDGE_KINDS
    assert {"source": "DEC-T1", "target": "DEC-T2", "kind": "SUPERSEDED_BY"} in g["links"]
    n1 = next(n for n in g["nodes"] if n["id"] == "DEC-T1")
    assert (n1["user"], n1["agent"], n1["product"]) == ("u-ops", "agent-a", "demo")
    assert g["counts"]["d:superseded"] == 1 and g["counts"]["w:done"] == 1
    assert json.dumps(g, sort_keys=True) == json.dumps(graph.export_graph(graph.derive(store.events())), sort_keys=True)


def test_export_empty():
    g = graph.export_graph(graph.derive([]))
    assert g["empty"] is True and g["nodes"] == [] and g["links"] == []


def test_duckdb_views_agree_when_available(store):
    pytest.importorskip("duckdb")
    c = graph.duckdb_views(store)
    rows = dict(c.execute("SELECT id, status FROM decisions").fetchall())
    assert rows == {k: v["status"] for k, v in graph.derive(store.events())["decisions"].items()}


# ── ask: local model only ────────────────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("url", ["http://127.0.0.1:8000/v1", "http://localhost:8000/v1", "http://[::1]:8000/v1",
                                 "http://10.1.2.3:8000/v1", "http://172.16.0.5/v1", "http://100.64.0.7:8000/v1",
                                 "http://[fd00::5]:8000/v1", "http://gpu-box.local:8000/v1"])
def test_local_endpoints_accepted(url):
    assert askmod.is_local_endpoint(url)


@pytest.mark.parametrize("url", ["https://api.example.com/v1", "http://8.8.8.8/v1", "http://127.0.0.1.example.com/v1",
                                 "http://localhost@example.com/v1", "http://[2001:db8::1]/v1", "ftp://127.0.0.1/",
                                 "http://gpu-box/v1", ""])
def test_non_local_endpoints_refused(url):
    assert not askmod.is_local_endpoint(url)


def test_allow_host_is_exact():
    assert askmod.is_local_endpoint("http://gpu-box:8000/v1", allow_host="gpu-box")
    assert not askmod.is_local_endpoint("http://gpu-box.example.com/v1", allow_host="gpu-box")


def test_ask_refuses_remote_before_sending(store):
    sent = []
    with pytest.raises(askmod.RefusedEndpoint):
        askmod.ask(graph.derive(store.events()), "what is blocked?", endpoint="https://api.example.com/v1",
                   post=lambda *a: sent.append(a))
    assert sent == []


def test_ask_sends_exact_rows_to_local_model(store):
    calls = []

    def post(url, body):
        calls.append((url, body))
        return {"choices": [{"message": {"content": "WORK-T2 is blocked."}}], "usage": {}}

    r = askmod.ask(graph.derive(store.events()), "what is blocked?", endpoint="http://127.0.0.1:9/v1", post=post)
    assert [x["id"] for x in r["rows"]] == ["WORK-T2"] and r["answer"] == "WORK-T2 is blocked."
    assert calls[0][0] == "http://127.0.0.1:9/v1/chat/completions" and "WORK-T2" in json.dumps(calls[0][1])


def test_ask_list_only_and_no_rows_send_nothing(store):
    g = graph.derive(store.events())
    r = askmod.ask(g, "what is pending?", endpoint="http://127.0.0.1:9/v1", list_only=True, post=lambda *a: 1 / 0)
    assert [x["id"] for x in r["rows"]] == ["DEC-T3"] and r["answer"] is None
    r = askmod.ask(g, "zebra unicorn", endpoint="http://127.0.0.1:9/v1", post=lambda *a: 1 / 0)
    assert r["rows"] == [] and r["answer"] is None


# ── command line ─────────────────────────────────────────────────────────────────────────────────────────
def test_cli_write_open_export_verify(tmp_path, capsys):
    from niyantrak.cli import main
    root = str(tmp_path / "dg")
    f = tmp_path / "ev.jsonl"
    f.write_text("\n".join(json.dumps(r) for r in sample_rows()) + "\n")
    assert main(["decisions", "--root", root, "write", str(f)]) == 0
    assert main(["decisions", "--root", root, "open"]) == 0
    out = capsys.readouterr().out
    assert "Decisions waiting for sign-off (1)" in out and "DEC-T3" in out and "WORK-T2" in out
    assert main(["decisions", "--root", root, "export", str(tmp_path / "g.json")]) == 0
    assert json.loads((tmp_path / "g.json").read_text())["empty"] is False
    assert main(["decisions", "--root", root, "materialize"]) == 0
    assert main(["decisions", "--root", root, "verify"]) == 0
    assert main(["decisions", "--root", root, "ask", "what is blocked?", "--endpoint", "https://api.example.com/v1"]) == 2
    assert "refusing" in capsys.readouterr().err


def test_cli_write_refuses_secrets(tmp_path, capsys):
    from niyantrak.cli import main
    f = tmp_path / "ev.jsonl"
    f.write_text(json.dumps({"kind": "DECISION", "src": "DEC-T9", "text": "token = abcdefgh12345678"}) + "\n")
    assert main(["decisions", "--root", str(tmp_path / "dg"), "write", str(f)]) == 1
    assert "refused" in capsys.readouterr().err and not (tmp_path / "dg" / "events").exists()
