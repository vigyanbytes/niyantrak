"""5W events and decisions carry the acting person from the operating system (niyantrak.identity), not typed names.

End users inside customer data stay pseudonymised (OTLP who_id -> pseudonym, unchanged); this covers the people
operating Niyantrak and the agents acting for them.
"""
import pytest

from niyantrak import identity as I
from niyantrak.decisions import schema as D
from niyantrak.telemetry import schema as S
from niyantrak.telemetry import sink

from telemetry_helpers import event

ASHA = I.Identity(name="asha", uid=1000, directory="local", stable_id="local:uid:1000@0123456789ab")
RAVI = I.Identity(name="ravi", uid=1500000001, directory="sssd",
                  stable_id="sid:S-1-5-21-3623811015-3361044348-30300820-1013")


# --- 5W ------------------------------------------------------------------------------------------------------------

def test_who_id_accepts_directory_ids_with_long_digit_runs():
    e = S.validate(event(who_id=RAVI.stable_id))
    assert e["who_id"] == RAVI.stable_id
    assert S.validate(event())["who_id"] is None


@pytest.mark.parametrize("bad", ["+919999999999", "asha@example.com", "sid:nope", "anything else"])
def test_who_id_rejects_anything_that_is_not_a_directory_id(bad):
    with pytest.raises(S.EventError) as ei:
        S.validate(event(who_id=bad))
    assert "who_id" in str(ei.value)


def test_who_id_is_a_stored_column():
    assert "who_id" in S.COLUMNS


def test_ingest_fills_the_actor_from_the_system():
    payload = [{k: v for k, v in event().items() if k not in ("who", "agent")}]
    r = sink.from_json(payload, actor=ASHA, agent="claude")
    assert not r.errors
    ev = r.events[0]
    assert (ev["who"], ev["who_id"], ev["agent"]) == ("asha", ASHA.stable_id, "claude")


def test_ingest_keeps_what_the_caller_set():
    r = sink.from_json([event(who="Priya (DevOps)", agent="codex")], actor=ASHA, agent="claude")
    ev = r.events[0]
    assert ev["who"] == "Priya (DevOps)" and ev["agent"] == "codex" and ev["who_id"] is None


def test_ingest_without_actor_behaves_as_before():
    r = sink.from_json([{k: v for k, v in event().items() if k != "who"}])
    assert r.rejected == 1 and "who" in r.errors[0]["error"]


def test_old_segments_without_who_id_still_read(tmp_path):
    pa = pytest.importorskip("pyarrow")
    pq = pytest.importorskip("pyarrow.parquet")
    from niyantrak.telemetry import store
    new = store._arrow_schema()
    old = pa.schema([f for f in new if f.name != "who_id"])
    path = tmp_path / "old.parquet"
    pq.write_table(pa.Table.from_pylist([{"event_id": "a" * 32, "who": "asha", "what": "x"}], schema=old), path)
    t = pq.read_table(path, schema=new)
    assert t.column("who_id").to_pylist() == [None] and t.column("who").to_pylist() == ["asha"]


# --- decisions -----------------------------------------------------------------------------------------------------

def row():
    return {"kind": "DECISION", "src": "DEC-T9", "title": "Pick a backup window"}


def test_decision_takes_the_person_from_the_system():
    r = D.normalize(row(), "cli", env={}, actor=RAVI, agent="claude")
    assert (r["user_id"], r["user_ref"], r["agent_id"]) == ("ravi", RAVI.stable_id, "claude")


def test_explicit_settings_still_win():
    r = D.normalize(row(), "cli", env={"NIYANTRAK_USER": "u-ops", "NIYANTRAK_AGENT": "codex"}, actor=RAVI,
                    agent="claude")
    assert (r["user_id"], r["agent_id"], r["user_ref"]) == ("u-ops", "codex", None)


def test_decision_privacy_check_allows_directory_ids():
    D.check_privacy([D.normalize(row(), "cli", env={}, actor=RAVI, agent=None)])


def test_decision_rejects_a_forged_user_ref():
    with pytest.raises(D.EventError):
        D.normalize({**row(), "user_ref": "+919999999999"}, "cli", env={})
