"""5W querying: ask templates, read-only SQL over ev + decisions, output formats, CLI."""
import csv
import io
import json

import pytest

pytest.importorskip("pyarrow")
pytest.importorskip("duckdb")

from niyantrak import cli  # noqa: E402
from niyantrak.decisions.store import Store as DecisionStore  # noqa: E402
from niyantrak.telemetry import query as Q  # noqa: E402
from niyantrak.telemetry import store as T  # noqa: E402

from telemetry_helpers import event  # noqa: E402


def gate(day, who, agent, machine, rule, outcome="blocked", where="/srv/app", what="Run shell command"):
    return event(ts=f"2026-10-{day:02d}T10:00:00Z", who=who, agent=agent, machine=machine, what=what, where=where,
                 why=f"{rule} hard stop", outcome=outcome, rule_ids=[rule], entity_counts={}, whom=None)


@pytest.fixture
def stores(tmp_path):
    st = T.Store(str(tmp_path / "tel"), writer="demo")
    st.append([
        gate(21, "asha", "Claude Code", "build-01", "git.force_push"),
        gate(22, "asha", "Claude Code", "build-01", "fs.rm_protected"),
        gate(22, "ravi", "Codex", "laptop-ravi", "git.reset_hard"),
        gate(10, "ravi", "Codex", "laptop-ravi", "git.reset_hard"),                     # outside the week
        gate(20, "ravi", "Antigravity", "laptop-ravi", "secret.path", where="/home/ravi/.aws/credentials"),
        gate(23, "asha", "Claude Code", "build-01", "prod.deploy", outcome="needs_approval", what="Deploy"),
        event(ts="2026-10-21T08:00:00Z", who="support-bot", agent="Claude Code", what="Ask a model", where="Cloud model",
              whom="customer", outcome="masked", entity_counts={"EMAIL": 2, "PAN": 1}, machine="gpu-01"),
    ])
    dec = DecisionStore(str(tmp_path / "dec"))
    dec.append([{"kind": "DECISION", "src": "DEC-1", "title": "Agents never force-push", "user_id": "asha"},
                {"kind": "WORK", "src": "WORK-1", "title": "Hook Codex into the gate", "user_id": "ravi"},
                {"kind": "STATUS", "src": "WORK-1", "title": "blocked"}], writer="t", env={})
    return st, dec, tmp_path


def con_for(stores):
    st, dec, _ = stores
    return Q.connect(st, dec.events())


def ask(stores, question):
    t = Q.match(question)
    assert t is not None, question
    return Q.run(con_for(stores), Q.sql_for(t, as_of="2026-10-23"))


def test_every_documented_question_matches_its_own_template():
    for t in Q.QUESTIONS:
        assert Q.match(t["question"]) is t, t["id"]
    assert Q.match("what is the weather") is None


def test_window_is_seven_days_ending_on_as_of():
    assert Q.window("2026-10-23") == ("DATE '2026-10-17'", "DATE '2026-10-24'")


def test_destructive_this_week(stores):
    cols, rows = ask(stores, "who ran destructive commands this week")
    got = {(r[0], r[1], r[2]): r[cols.index("attempts")] for r in rows}
    assert got == {("asha", "Claude Code", "build-01"): 2, ("ravi", "Codex", "laptop-ravi"): 1}   # day 10 is outside
    assert rows[0][cols.index("rules")] == "fs.rm_protected, git.force_push"


def test_credential_files_and_blocked_per_machine(stores):
    cols, rows = ask(stores, "which agent touched credential files")
    assert rows == [("Antigravity", "ravi", "laptop-ravi", "/home/ravi/.aws/credentials", "blocked", 1)]
    cols, rows = ask(stores, "what was blocked per machine")
    assert [(r[0], r[1]) for r in rows] == [("build-01", 2), ("laptop-ravi", 2)]


def test_personal_data_map_and_decisions_table(stores):
    _, rows = ask(stores, "which personal data types reached each agent")
    assert ("Claude Code", "EMAIL", 2, 1) in rows and ("Claude Code", "PAN", 1, 1) in rows
    cols, rows = ask(stores, "decisions by status")
    assert [(r[0], r[1], r[2]) for r in rows] == [("DECISION", "in force", 1), ("WORK", "blocked", 1)]


def test_sql_is_read_only(stores):
    con = con_for(stores)
    for bad in ("DELETE FROM ev", "SELECT 1; SELECT 2", "COPY ev TO 'x.csv'", "SET enable_external_access = true",
                "ATTACH 'x.db'", "not sql at all"):
        with pytest.raises(Q.QueryError):
            Q.run(con, bad)
    for sneaky in ("SELECT * FROM read_csv('/etc/hostname')", "SELECT * FROM read_text('/etc/passwd')"):
        with pytest.raises(Q.QueryError):
            Q.run(con, sneaky)
    assert Q.run(con, "SELECT count(*) AS n FROM ev")[1] == [(7,)]


def test_row_limit(stores):
    with pytest.raises(Q.QueryError, match="more than 3 rows"):
        Q.run(con_for(stores), "SELECT * FROM range(10)", limit=3)


def test_empty_store_still_has_both_tables(tmp_path):
    con = Q.connect(T.Store(str(tmp_path / "none")), [])
    assert Q.run(con, "SELECT count(*) FROM ev")[1] == [(0,)]
    assert Q.run(con, "SELECT count(*) FROM decisions")[1] == [(0,)]


def test_formats_round_trip():
    cols, rows = ["who", "n", "rules"], [("asha", 2, ["git.force_push"]), ("ravi | x", 1, None)]
    assert list(csv.reader(io.StringIO(Q.render(cols, rows, "csv")))) == [cols, ["asha", "2", '["git.force_push"]'], ["ravi | x", "1", ""]]
    assert json.loads(Q.render(cols, rows, "json")) == [{"who": "asha", "n": 2, "rules": ["git.force_push"]},
                                                        {"who": "ravi | x", "n": 1, "rules": None}]
    md = Q.render(cols, rows, "md").splitlines()
    assert md[0] == "| who | n | rules |" and md[1] == "|---|---|---|" and md[3] == "| ravi \\| x | 1 |  |"
    table = Q.render(cols, rows, "table").splitlines()
    assert table[0].split() == cols and table[-1] == "(2 rows)"
    with pytest.raises(ValueError):
        Q.render(cols, rows, "xml")


def test_parquet_output(stores, tmp_path):
    import pyarrow.parquet as pq
    con = con_for(stores)
    out = tmp_path / "who.parquet"
    assert Q.write_parquet(con, "SELECT who, count(*) AS n FROM ev GROUP BY 1 ORDER BY 1", str(out)) == 3
    assert pq.read_table(out).to_pylist()[0] == {"who": "asha", "n": 3}


def test_cli_ask_prints_sql_and_answer(stores, capsys):
    st, dec, tmp = stores
    base = ["telemetry", "--dir", st.root, "--decisions", dec.root]
    assert cli.main(base + ["ask", "who ran destructive commands this week", "--as-of", "2026-10-23", "--format", "md"]) == 0
    out = capsys.readouterr().out
    assert "FROM ev, unnest(rule_ids)" in out and "| asha | Claude Code | build-01 | 2 |" in out
    assert cli.main(base + ["ask", "what is the weather"]) == 2
    assert "Questions ask understands" in capsys.readouterr().out
    assert cli.main(base + ["ask", "--list"]) == 0
    assert "decisions-by-status" in capsys.readouterr().out


def test_cli_sql_formats_and_refusal(stores, capsys, tmp_path):
    st, dec, _ = stores
    base = ["telemetry", "--dir", st.root, "--decisions", dec.root]
    assert cli.main(base + ["sql", "SELECT who, count(*) AS n FROM ev GROUP BY 1 ORDER BY 1", "--format", "json"]) == 0
    assert json.loads(capsys.readouterr().out)[0] == {"who": "asha", "n": 3}
    out = tmp_path / "r.parquet"
    assert cli.main(base + ["sql", "SELECT * FROM decisions", "--format", "parquet", "--out", str(out)]) == 0
    assert out.exists() and "wrote 2 row(s)" in capsys.readouterr().out
    assert cli.main(base + ["sql", "SELECT 1", "--format", "parquet"]) == 2           # parquet needs --out
    assert cli.main(base + ["sql", "DROP TABLE ev"]) == 1
    assert "read-only" in capsys.readouterr().err
    csv_out = tmp_path / "r.csv"
    assert cli.main(base + ["sql", "SELECT who FROM ev ORDER BY 1 LIMIT 1", "--format", "csv", "--out", str(csv_out)]) == 0
    assert csv_out.read_text() == "who\nasha\n"
