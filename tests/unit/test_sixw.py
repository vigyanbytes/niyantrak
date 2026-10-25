"""6W: the `which` field (project / repository / workspace), the 5w/1 -> 6w/1 schema step, the store setting that
pseudonymises it, OTLP mapping, the agent gate filling it from git, the panel's project breakdown, ask questions."""
import json
import os
from datetime import datetime, timezone

import pytest

from niyantrak.telemetry import schema as S

from telemetry_helpers import IBAN, EMAIL, aadhaar, event

NOW = datetime(2026, 10, 23, 12, 0, tzinfo=timezone.utc)


# ── schema ────────────────────────────────────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("which", ["acme/payments-api", "ws-01:~/projects/app", "/srv/repos/clinic-bot",
                                   "C:\\code\\infra", "payments-api", "gitlab group/sub/repo"])
def test_which_accepts_repo_workspace_and_path_forms(which):
    e = S.validate(event(which=which))
    assert e["which"] == which and e["schema"] == "niyantrak.6w/1" == S.SCHEMA


@pytest.mark.parametrize("value", [aadhaar(), IBAN, EMAIL, "+91 98450 12345", "4111 1111 1111 1111"])
def test_which_rejects_identifier_values(value):
    with pytest.raises(S.EventError) as ei:
        S.validate(event(which=f"acme/{value}"[:64]))
    assert value not in str(ei.value) and "which" in str(ei.value)


@pytest.mark.parametrize("bad", ["acme/repo-123456789012", "x" * 65, "a b c d e f g h i", "line\nbreak",
                                 "acme/repo; rm -rf /", "$(whoami)/repo", "~/no-host-prefix"])
def test_which_follows_label_rules(bad):
    with pytest.raises(S.EventError) as ei:
        S.validate(event(which=bad))
    assert "which" in str(ei.value)


def test_5w_events_are_still_accepted_and_which_is_null():
    e = S.validate(event(schema="niyantrak.5w/1"))
    assert e["which"] is None and e["schema"] == S.SCHEMA
    assert S.validate(event())["which"] is None
    assert "niyantrak.5w/1" in S.ACCEPTED_SCHEMAS
    with pytest.raises(S.EventError):
        S.validate(event(schema="niyantrak.7w/1"))


def test_which_is_a_column():
    assert "which" in S.COLUMNS and "which" in S.LABELS


# ── store ─────────────────────────────────────────────────────────────────────────────────────────────────────
pa = pytest.importorskip("pyarrow")
pytest.importorskip("duckdb")
from niyantrak.telemetry import store as T  # noqa: E402


def ev(day, **kw):
    return event(ts=f"2026-10-{day:02d}T09:30:00Z", **kw)


@pytest.fixture
def st(tmp_path):
    return T.Store(str(tmp_path / "tel"), writer="sink-a")


def _write_5w_segment(st, rows):
    """A segment exactly as v0.1.0 wrote it: the 5W columns, no `which`."""
    old = pa.schema([f for f in T._arrow_schema() if f.name != "which"])
    assert len(old) == len(T._arrow_schema()) - 1
    rows = [{k: v for k, v in T._row(S.validate(r)).items() if k != "which"} | {"schema": "niyantrak.5w/1"} for r in rows]
    rel, entry = st._write(pa.Table.from_pylist(rows, schema=old), "2026-10")
    st._record({"op": "add", **entry})
    return rel


def test_old_5w_segments_read_with_which_null_and_verify_and_compact_unaffected(st):
    _write_5w_segment(st, [ev(20), ev(21)])
    st.append([ev(22, which="acme/infra")])
    assert st.verify() == []
    con = st._con()
    rows = con.execute("SELECT schema, which FROM ev ORDER BY ts").fetchall()
    assert rows == [("niyantrak.5w/1", None), ("niyantrak.5w/1", None), ("niyantrak.6w/1", "acme/infra")]
    made = st.compact(month="2026-10")
    assert len(made) == 1 and st.verify() == [] and st.count() == 3


def test_view_built_before_6w_is_rebuilt(st):
    st.append([ev(20, which="acme/infra")])
    view = st.materialize()
    state = os.path.join(os.path.dirname(view), "state.json")
    s = json.load(open(state))
    # a v0.1.0 view: same segments digest, but the old digest formula and a file without the which column
    import hashlib
    import pyarrow.parquet as pq
    old_digest = hashlib.sha256("".join(e["file"] + e["sha256"] for e in st.segments()).encode()).hexdigest()
    pq.write_table(pq.read_table(view).drop(["which"]), view)
    s.update(digest=old_digest, sha256=T._sha(view))
    json.dump(s, open(state, "w"))
    assert "which" in pq.read_schema(st.materialize()).names


def test_activity_filter_by_which_breakdown_and_sankey(st):
    st.append([ev(21, which="acme/payments-api"), ev(21, which="acme/payments-api"), ev(22, which="acme/infra"),
               ev(22, who="Clinic bot", agent="WhatsApp gateway", what="Answer query")])
    a = st.activity(days=7, now=NOW)
    assert a["by"]["which"] == [{"name": "acme/payments-api", "value": 2}, {"name": "acme/infra", "value": 1}]
    cols = {n["name"]: n["col"] for n in a["sankey"]["nodes"]}
    assert cols["acme/payments-api"] == "which" and "(no which)" not in cols
    links = {(l["source"], l["target"]): l["value"] for l in a["sankey"]["links"]}
    assert links[("Claude Code", "acme/payments-api")] == 2 and links[("acme/payments-api", "Edit code")] == 2
    assert links[("WhatsApp gateway", "Answer query")] == 1           # no which: agent -> what directly
    assert ("Claude Code", "Edit code") not in links
    f = st.activity(days=7, now=NOW, filter=("which", "acme/infra"))
    assert f["total"] == 1 and f["filter"] == {"k": "which", "v": "acme/infra"}
    assert "which" in T.FILTER_KEYS and T.FLOW == ("who", "agent", "which", "what", "where")


def test_pseudonymise_which_setting(st):
    assert st.settings() == {"pseudonymise_which": False}
    st.append([ev(20, which="acme/infra")])
    st.set_setting("pseudonymise_which", True)
    assert st.settings()["pseudonymise_which"] is True
    st.append([ev(21, which="acme/infra"), ev(21)])
    rows = st._con().execute("SELECT which FROM ev ORDER BY ts, which NULLS LAST").fetchall()
    expected = S.pseudonym("acme/infra", st.salt())
    assert rows == [("acme/infra",), (expected,), (None,)] and S.PSEUDONYM_RX.match(expected)
    st.append([ev(22, which=expected)])                               # already a pseudonym: kept, not hashed twice
    assert st._con().execute("SELECT count(*) FROM ev WHERE which = ?", [expected]).fetchone()[0] == 2
    raw = b"".join(open(os.path.join(d, f), "rb").read() for d, _, fs in os.walk(st.root) for f in fs
                   if f.endswith(".parquet") and "segments" in d)
    with pytest.raises(ValueError):
        st.set_setting("message", True)
    with pytest.raises(ValueError):
        st.set_setting("pseudonymise_which", "yes")
    assert raw.count(b"acme/infra") >= 1                              # only the event written before the switch


def test_cli_settings(tmp_path, capsys):
    from niyantrak.cli import main
    d = str(tmp_path / "tel")
    assert main(["telemetry", "--dir", d, "settings"]) == 0
    assert json.loads(capsys.readouterr().out) == {"pseudonymise_which": False}
    assert main(["telemetry", "--dir", d, "settings", "--pseudonymise-which", "on"]) == 0
    assert json.loads(capsys.readouterr().out) == {"pseudonymise_which": True}
    assert T.Store(d).settings()["pseudonymise_which"] is True


# ── OTLP ──────────────────────────────────────────────────────────────────────────────────────────────────────
from niyantrak.telemetry import sink as K  # noqa: E402

from telemetry_helpers import otlp  # noqa: E402

BASE = {"niyantrak.who": "Support bot", "niyantrak.what": "Ask a model"}


@pytest.mark.parametrize("attrs,want", [
    ({"niyantrak.which": "acme/clinic-bot", "vcs.repository.url.full": "https://github.com/acme/other"}, "acme/clinic-bot"),
    ({"vcs.repository.url.full": "https://bot:ghp_notarealtoken@github.com/acme/payments-api.git"}, "acme/payments-api"),
    ({"vcs.repository.url.full": "https://gitlab.example/acme/team/repo?x=1#y", "vcs.repository.name": "repo"}, "acme/team/repo"),
    ({"vcs.repository.name": "payments-api"}, "payments-api"),
    ({"code.namespace": "acme.billing"}, "acme.billing"),
    ({}, None),
])
def test_otlp_which_mapping(attrs, want):
    r = K.from_otlp(otlp([{**BASE, **attrs}]), salt="s")
    assert r.rejected == 0 and r.events[0]["which"] == want
    assert "ghp_" not in json.dumps(r.events)


def test_repo_label_strips_credentials_and_forms():
    assert K.repo_label("git@github.com:acme/infra.git") == "acme/infra"
    assert K.repo_label("ssh://git@gitlab.example:2222/acme/infra.git") == "acme/infra"
    assert K.repo_label("https://user:pass@github.com/acme/infra/") == "acme/infra"
    assert K.repo_label("/srv/git/infra.git") == "infra"
    assert K.repo_label("") is None and K.repo_label(None) is None


# ── agent gate ────────────────────────────────────────────────────────────────────────────────────────────────
from niyantrak.gate import adapters, events as G  # noqa: E402


def _repo(root, url=None, remote="origin"):
    os.makedirs(os.path.join(root, ".git"))
    cfg = "[core]\n\tbare = false\n"
    if url:
        cfg += f'[remote "{remote}"]\n\turl = {url}\n\tfetch = +refs/heads/*:refs/remotes/{remote}/*\n'
    open(os.path.join(root, ".git", "config"), "w").write(cfg)
    return root


def test_gate_which_from_git_remote_without_credentials(tmp_path):
    root = _repo(str(tmp_path / "work" / "pay"), "https://bot:ghp_notarealtoken@github.com/acme/payments-api.git")
    sub = os.path.join(root, "src", "deep")
    os.makedirs(sub)
    assert G.which(sub) == "acme/payments-api"


def test_gate_which_prefers_origin_then_any_remote_then_folder(tmp_path):
    assert G.which(_repo(str(tmp_path / "a"), "git@github.com:acme/infra.git", remote="upstream")) == "acme/infra"
    assert G.which(_repo(str(tmp_path / "clinic-bot"))) == "clinic-bot"         # no remote: the repository folder
    plain = tmp_path / "scratch-app"
    plain.mkdir()
    assert G.which(str(plain)) == "scratch-app"                                 # not a repository: the folder name


def test_gate_which_worktree_gitfile(tmp_path):
    main = _repo(str(tmp_path / "main"), "https://github.com/acme/infra")
    wt = tmp_path / "wt"
    wt.mkdir()
    gd = os.path.join(main, ".git", "worktrees", "wt")
    os.makedirs(gd)
    open(os.path.join(gd, "commondir"), "w").write("../..\n")
    (wt / ".git").write_text(f"gitdir: {gd}\n")
    assert G.which(str(wt)) == "acme/infra"


def test_gate_which_never_records_home_root_or_identifiers(tmp_path, monkeypatch):
    home = tmp_path / "home" / "asha"
    home.mkdir(parents=True)
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    assert G.which(str(home)) is None
    assert G.which(os.path.abspath(os.sep)) is None
    bad = tmp_path / "someone@example.com"
    bad.mkdir()
    assert G.which(str(bad)) is None
    assert G.which(str(tmp_path / "does-not-exist")) is None


def test_gate_event_carries_which_from_hook_cwd(tmp_path, monkeypatch):
    log = tmp_path / "log" / "events.jsonl"
    monkeypatch.setenv("NIYANTRAK_GATE_LOG", str(log))
    monkeypatch.setenv("NIYANTRAK_GATE_MODE_FILE", str(tmp_path / "gate-mode"))
    monkeypatch.setenv("NIYANTRAK_ROOT", str(tmp_path / "root"))
    root = _repo(str(tmp_path / "pay"), "git@github.com:acme/payments-api.git")
    adapters.handle("claude", json.dumps({"tool_name": "Bash", "tool_input": {"command": "ls"}, "cwd": root}))
    other = tmp_path / "plain-dir"
    other.mkdir()
    monkeypatch.chdir(other)
    adapters.handle("codex", json.dumps({"tool_name": "Bash", "tool_input": {"command": "ls"}}))
    lines = [json.loads(x) for x in log.read_text().splitlines()]
    assert lines[0]["which"] == "acme/payments-api" and lines[1]["which"] == "plain-dir"


# ── telemetry ask: project questions ──────────────────────────────────────────────────────────────────────────
from niyantrak.telemetry import query as Q  # noqa: E402


def test_project_questions(st):
    st.append([ev(21, which="acme/payments-api", outcome="blocked", rule_ids=["git.force_push"], entity_counts={}),
               ev(22, which="acme/payments-api", outcome="blocked", rule_ids=["secret.path"], entity_counts={}),
               ev(22, which="acme/infra", outcome="blocked", rule_ids=["git.reset_hard"], entity_counts={}),
               ev(22, which="acme/clinic-bot", entity_counts={"ABHA_NUMBER": 3, "EMAIL": 1}),
               ev(23, which="acme/infra", entity_counts={"EMAIL": 1}),
               ev(23, outcome="blocked", entity_counts={})])
    con = Q.connect(st)
    run = lambda q: Q.run(con, Q.sql_for(Q.match(q), as_of="2026-10-23"))
    assert Q.match("which repos had blocked actions this week")["id"] == "blocked-by-project"
    cols, rows = run("which repos had blocked actions this week")
    assert cols[:2] == ["which", "blocked"] and rows[0][:2] == ("acme/payments-api", 2) and rows[1][:2] == ("acme/infra", 1)
    assert all(r[0] is not None for r in rows)
    assert Q.match("top projects by masked personal data")["id"] == "personal-data-by-project"
    cols, rows = run("top projects by masked personal data")
    assert rows[0][:2] == ("acme/clinic-bot", 4) and rows[1][:2] == ("acme/infra", 1)
    assert Q.match("which agents worked in each project")["id"] == "agents-per-project"
    cols, rows = run("which agents worked in each project")
    assert ("acme/infra", "Claude Code") in {r[:2] for r in rows}


def test_existing_questions_still_match_their_templates():
    for t in Q.QUESTIONS:
        assert Q.match(t["question"])["id"] == t["id"], t["id"]


# ── docs ──────────────────────────────────────────────────────────────────────────────────────────────────────
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))


@pytest.mark.parametrize("old,new", [("5W.md", "6W.md"), ("QUERYING_5W.md", "QUERYING_6W.md")])
def test_renamed_docs_keep_a_stub_at_the_old_name(old, new):
    stub = open(os.path.join(ROOT, "docs", old), encoding="utf-8").read()
    assert new in stub and len(stub.splitlines()) < 12
    assert "which" in open(os.path.join(ROOT, "docs", new), encoding="utf-8").read()


def test_six_w_wording_in_readme_and_panel():
    readme = open(os.path.join(ROOT, "README.md"), encoding="utf-8").read()
    assert "6W" in readme and "who, whom, what, where, why, which" in readme
    html = open(os.path.join(ROOT, "niyantrak", "web", "index.html"), encoding="utf-8").read()
    assert "Activity (6W)" in html and "5W" not in html and 'id="c-which"' in html
