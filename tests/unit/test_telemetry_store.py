"""Store: append-only Parquet segments per writer + hash-chained manifest; materialize; monthly compact; queries."""
import json
import os
from datetime import datetime, timezone

import pytest

pytest.importorskip("pyarrow")
pytest.importorskip("duckdb")

from niyantrak.telemetry import store as T  # noqa: E402

from telemetry_helpers import event  # noqa: E402

NOW = datetime(2026, 10, 23, 12, 0, tzinfo=timezone.utc)


def ev(day, **kw):
    return event(ts=f"2026-10-{day:02d}T09:30:00Z", **kw)


@pytest.fixture
def st(tmp_path):
    return T.Store(str(tmp_path / "tel"), writer="sink-a")


def test_append_writes_segment_and_manifest(st):
    rel = st.append([ev(20), ev(21)])
    assert rel[0].startswith("segments/sink-a/2026-10/") and rel[0].endswith(".parquet")
    live = st.segments()
    assert len(live) == 1 and live[0]["rows"] == 2 and len(live[0]["sha256"]) == 64
    assert st.verify() == []


def test_append_splits_by_month_and_rejects_invalid(st):
    assert len(st.append([ev(20), event(ts="2026-09-30T23:00:00Z")])) == 2
    with pytest.raises(T.EventError):
        st.append([ev(20, message="hello")])
    assert st.append([]) == []


def test_writers_have_separate_manifests(tmp_path):
    a, b = T.Store(str(tmp_path), writer="sink-a"), T.Store(str(tmp_path), writer="sink-b")
    a.append([ev(20)])
    b.append([ev(21)])
    assert sorted(os.listdir(tmp_path / "manifest")) == ["sink-a.jsonl", "sink-b.jsonl"]
    assert len(a.segments()) == 2 and a.verify() == []
    with pytest.raises(ValueError):
        T.Store(str(tmp_path), writer="../escape")


def test_tampered_segment_detected(st):
    rel = st.append([ev(20)])[0]
    with open(os.path.join(st.root, rel), "ab") as f:
        f.write(b"x")
    problems = st.verify()
    assert problems and problems[0]["file"] == rel and "sha256" in problems[0]["problem"]
    with pytest.raises(T.IntegrityError):
        st.materialize()


def test_missing_unlisted_and_manifest_edits_detected(st, tmp_path):
    rel = st.append([ev(20)])[0]
    st.append([ev(21)])
    stray = os.path.join(st.root, "segments", "sink-a", "2026-10", "stray.parquet")
    open(stray, "wb").write(b"PAR1")
    assert any(p["problem"] == "not in manifest" for p in st.verify())
    os.remove(stray)
    mf = os.path.join(st.root, "manifest", "sink-a.jsonl")
    lines = open(mf).read().splitlines()
    first = json.loads(lines[0])
    first["rows"] = 99
    open(mf, "w").write("\n".join([json.dumps(first)] + lines[1:]) + "\n")
    assert any("chain" in p["problem"] for p in st.verify())
    open(mf, "w").write("\n".join(lines) + "\n")
    os.remove(os.path.join(st.root, rel))
    assert any(p["problem"] == "missing" for p in st.verify())


def test_materialize_and_staleness(st):
    assert st.materialize() is None                       # empty store: no view
    st.append([ev(20), ev(21)])
    v = st.materialize()
    assert os.path.isfile(v) and st.count() == 2
    st.append([ev(22)])
    assert st.count() == 3                                # stale view is rebuilt on read


def test_compact_previous_months_only(st):
    st.append([event(ts="2026-09-01T00:00:00Z")])
    st.append([event(ts="2026-09-15T00:00:00Z"), event(ts="2026-09-30T23:59:59Z")])
    st.append([ev(20)])
    st.append([ev(21)])
    before = st.count()
    made = st.compact(now=NOW)
    assert len(made) == 1 and "/2026-09/" in made[0]
    live = st.segments()
    assert len(live) == 3 and sum(s["rows"] for s in live) == before == 5
    assert st.verify() == [] and st.count() == 5
    assert len(os.listdir(os.path.join(st.root, "segments", "sink-a", "2026-09"))) == 1
    assert st.compact(now=NOW) == []                      # already one segment: nothing to do
    assert st.compact(month="2026-10") and len(st.segments()) == 2


def test_compact_refuses_tampered_store(st):
    rel = st.append([event(ts="2026-09-01T00:00:00Z")])[0]
    st.append([event(ts="2026-09-02T00:00:00Z")])
    with open(os.path.join(st.root, rel), "ab") as f:
        f.write(b"x")
    with pytest.raises(T.IntegrityError):
        st.compact(now=NOW)


# ── queries: exactly the shapes the Activity (5W) screen draws ─────────────────────────────────────────
def seed(st):
    st.append([ev(21, who="Clinic bot", agent="WhatsApp gateway", what="Answer query", where="Cloud", outcome="masked",
                  why="RB-ROUTE-001 mask personal data", rule_ids=["RB-ROUTE-001"], machine="edge-01")] * 3)
    st.append([ev(22, who="Priya (DevOps)", agent="Claude Code", what="Open port", where="Edge", outcome="needs_approval",
                  why="RB-INFRA-EDGE-002 approval", rule_ids=["RB-INFRA-EDGE-002"], machine="edge-01"),
               ev(23, who="Priya (DevOps)", agent="Claude Code", what="Read secrets", where="Local", outcome="blocked",
                  why="Hard stop secret access", rule_ids=[], machine="control-01")])
    st.append([event(ts="2026-10-01T09:00:00Z")])        # outside a 7-day window


def test_activity_shapes(st):
    seed(st)
    a = st.activity(days=7, now=NOW)
    assert a["empty"] is False and a["total"] == 5 and a["days"] == 7
    names = {n["name"]: n["col"] for n in a["sankey"]["nodes"]}
    assert names["Clinic bot"] == "who" and names["Claude Code"] == "agent" and names["Open port"] == "what"
    links = {(l["source"], l["target"]): l["value"] for l in a["sankey"]["links"]}
    assert links[("Clinic bot", "WhatsApp gateway")] == 3 and links[("Answer query", "Cloud")] == 3
    assert links[("Claude Code", "Open port")] == 1
    w = a["week"]
    assert w["days"] == ["2026-10-17", "2026-10-18", "2026-10-19", "2026-10-20", "2026-10-21", "2026-10-22", "2026-10-23"]
    series = {s["name"]: s["data"] for s in w["series"]}
    assert series["masked"] == [0, 0, 0, 0, 3, 0, 0] and series["blocked"][6] == 1 and set(w["outcomes"]) == set(series)
    assert a["why"][0] == {"name": "RB-ROUTE-001 mask personal data", "value": 3}
    assert {r["name"]: r["value"] for r in a["rules"]} == {"RB-ROUTE-001": 3, "RB-INFRA-EDGE-002": 1}
    infra = a["infra"]
    assert infra["hosts"] == ["edge-01", "control-01"]
    assert {s["name"]: s["data"] for s in infra["series"]}["masked"] == [3, 0]
    assert a["by"]["who"][0] == {"name": "Clinic bot", "value": 3} and set(a["by"]) == {"who", "agent", "what", "where", "why", "which"}


def test_activity_filter_and_empty(st):
    assert st.activity(days=7, now=NOW)["empty"] is True
    seed(st)
    f = st.activity(days=7, now=NOW, filter=("who", "Priya (DevOps)"))
    assert f["total"] == 2 and f["filter"] == {"k": "who", "v": "Priya (DevOps)"}
    with pytest.raises(ValueError):
        st.activity(filter=("message", "x"))


def test_sankey_names_shared_between_columns_stay_acyclic(st):
    st.append([ev(22, what="Local", where="Local")])
    nodes = st.activity(days=7, now=NOW)["sankey"]
    names = [n["name"] for n in nodes["nodes"]]
    assert len(names) == len(set(names)) and any(l["source"] != l["target"] for l in nodes["links"])
    assert all(l["source"] != l["target"] for l in nodes["links"])


def test_cli_ingest_verify_compact_activity(tmp_path, capsys):
    from niyantrak.cli import main
    d = str(tmp_path / "tel")
    f = tmp_path / "events.json"
    f.write_text(json.dumps([event(ts="2026-09-01T00:00:00Z"), event(ts="2026-09-02T00:00:00Z")]))
    assert main(["telemetry", "--dir", d, "ingest", str(f)]) == 0
    assert main(["telemetry", "--dir", d, "ingest", str(f)]) == 0
    assert main(["telemetry", "--dir", d, "verify"]) == 0
    assert main(["telemetry", "--dir", d, "compact", "--month", "2026-09"]) == 0
    assert main(["telemetry", "--dir", d, "activity", "--days", "90"]) == 0
    out = capsys.readouterr().out
    assert '"total"' in out
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps([event(message="hi")]))
    assert main(["telemetry", "--dir", d, "ingest", str(bad)]) == 1
    seg = T.Store(d).segments()[0]["file"]
    with open(os.path.join(d, seg), "ab") as fh:
        fh.write(b"x")
    assert main(["telemetry", "--dir", d, "verify"]) == 1


def test_cached_view_is_not_used_after_a_segment_is_changed(st):
    """materialize() used to return the cached view while the manifest was unchanged, so a segment edited afterwards
    went unnoticed by activity() and SQL queries (only `telemetry verify` saw it). Reported by the dashboard build."""
    st.append([ev(20), ev(21)])
    assert st.activity(days=7, now=NOW)["total"] == 2               # view built and cached
    seg = st._p(st.segments()[0]["file"])
    with open(seg, "ab") as f:
        f.write(b"tampered")
    with pytest.raises(T.IntegrityError):
        st.materialize()
    with pytest.raises(T.IntegrityError):
        st.activity(days=7, now=NOW)
