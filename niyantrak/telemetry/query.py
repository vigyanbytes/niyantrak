"""Ask the 5W store (and the decision log) questions in SQL, and get the answer as a table, CSV, JSON, Markdown or Parquet.

    niyantrak telemetry sql "SELECT who, count(*) AS n FROM ev GROUP BY 1 ORDER BY n DESC" [--format md]
    niyantrak telemetry ask "who ran destructive commands this week" [--as-of 2026-10-23] [--format csv]
    niyantrak telemetry ask --list                       # the questions ask understands, with their SQL

Tables
    ev         one row per 5W event (see docs/5W.md); rule_ids is a LIST, entity_counts a MAP(type -> count)
    decisions  one row per decision or work item derived from the decision log (id, kind, status, ts, title, user,
               agent, product); empty when there is no decision log

Read-only by construction: the rows are copied into an in-memory DuckDB, then file and network access is switched
off and the configuration locked, so a query cannot read other files, write files or turn access back on. One
SELECT statement per call. `ask` uses no model: a question is matched by keywords to one of the built-in templates
below and the exact SQL is printed with the answer, so the result can be checked and re-run with `sql`.
Needs the optional extra: pip install niyantrak[telemetry]  (pyarrow + duckdb).
"""
import csv
import io
import json
import re
from datetime import date, datetime, timedelta, timezone

FORMATS = ("table", "csv", "json", "md", "parquet")
MAX_ROWS = 10_000
DECISION_COLUMNS = ("id", "kind", "status", "ts", "title", "user", "agent", "product")
DESTRUCTIVE = r"^(fs|disk|docker|git)\."


class QueryError(ValueError):
    """The SQL was refused or failed; nothing was changed."""


# ── questions ask understands: every keyword group must have a word in the question ────────────────────────────
# {start} / {end} are DATE literals for the window ending on --as-of (inclusive): "this week" = the last 7 days.
QUESTIONS = [
    {"id": "destructive-this-week", "question": "Who ran destructive commands this week?",
     "keywords": [("destructive", "delete", "rm ", "force-push", "force push", "dangerous")],
     "sql": """SELECT who, agent, machine, count(*) AS attempts,
       count(*) FILTER (WHERE outcome = 'blocked') AS blocked,
       string_agg(DISTINCT r, ', ' ORDER BY r) AS rules
FROM ev, unnest(rule_ids) AS t(r)
WHERE regexp_matches(r, '{destructive}') AND ts >= {start} AND ts < {end}
GROUP BY ALL ORDER BY attempts DESC, who, agent, machine"""},
    {"id": "credential-files", "question": "Which agent touched credential files?",
     "keywords": [("credential", "secret", "password", "key file", ".env", "token")],
     "sql": """SELECT agent, who, machine, "where" AS path, outcome, count(*) AS events
FROM ev
WHERE list_contains(rule_ids, 'secret.path') AND ts >= {start} AND ts < {end}
GROUP BY ALL ORDER BY events DESC, agent, who, machine, path"""},
    {"id": "blocked-per-machine", "question": "What was blocked on each machine?",
     "keywords": [("blocked", "stopped", "denied"), ("machine", "host", "server", "laptop", "where")],
     "sql": """SELECT machine, count(*) AS blocked,
       count(DISTINCT who) AS people, count(DISTINCT agent) AS agents,
       arg_max(r, n) AS top_rule
FROM (SELECT machine, who, agent, r, count(*) OVER (PARTITION BY machine, r) AS n
      FROM ev, unnest(rule_ids) AS t(r)
      WHERE outcome = 'blocked' AND ts >= {start} AND ts < {end})
GROUP BY machine ORDER BY blocked DESC, machine"""},
    {"id": "top-whom", "question": "Whose data was handled most (top whom)?",
     "keywords": [("whom", "whose", "on behalf")],
     "sql": """SELECT whom, count(*) AS events, sum(entity_total) AS identifiers_found,
       count(*) FILTER (WHERE outcome IN ('masked', 'local')) AS protected
FROM ev
WHERE whom IS NOT NULL AND ts >= {start} AND ts < {end}
GROUP BY whom ORDER BY events DESC, whom LIMIT 10"""},
    {"id": "top-what", "question": "What did agents do most (top what)?",
     "keywords": [("top what", "most common", "what did", "actions", "activities")],
     "sql": """SELECT what, count(*) AS events,
       count(*) FILTER (WHERE outcome = 'allowed') AS allowed,
       count(*) FILTER (WHERE outcome = 'blocked') AS blocked,
       count(*) FILTER (WHERE outcome IN ('masked', 'local')) AS protected
FROM ev
WHERE ts >= {start} AND ts < {end}
GROUP BY what ORDER BY events DESC, what LIMIT 10"""},
    {"id": "personal-data-by-agent", "question": "Which personal data types reached each agent?",
     "keywords": [("personal data", "identifiers", "pii", "entity", "aadhaar", "pan ")],
     "sql": """SELECT agent, e.key AS identifier_type, sum(e.value) AS found,
       count(*) AS events
FROM (SELECT agent, unnest(map_entries(entity_counts)) AS e FROM ev WHERE ts >= {start} AND ts < {end})
GROUP BY ALL ORDER BY found DESC, agent, identifier_type"""},
    {"id": "routes", "question": "Where did data go — cloud or local?",
     "keywords": [("cloud", "local", "route", "where did data", "where data")],
     "sql": """SELECT "where", outcome, count(*) AS events, sum(entity_total) AS identifiers_found
FROM ev
WHERE what = 'Ask a model' AND ts >= {start} AND ts < {end}
GROUP BY ALL ORDER BY events DESC, "where", outcome"""},
    {"id": "blocked-per-day", "question": "How many actions were blocked each day, per agent?",
     "keywords": [("blocked", "stopped", "denied"), ("day", "daily", "trend", "per day")],
     "sql": """SELECT CAST(ts AS DATE) AS day,
       count(*) FILTER (WHERE agent = 'Claude Code') AS claude_code,
       count(*) FILTER (WHERE agent = 'Codex') AS codex,
       count(*) FILTER (WHERE agent = 'Antigravity') AS antigravity,
       count(*) AS total
FROM ev
WHERE outcome = 'blocked' AND ts >= {start} AND ts < {end}
GROUP BY day ORDER BY day"""},
    {"id": "approvals", "question": "Which production changes needed approval, and who decided?",
     "keywords": [("approval", "approve", "approved", "production")],
     "sql": """SELECT CAST(ts AS DATE) AS day, who, agent, machine, what, outcome, r AS rule
FROM ev, unnest(rule_ids) AS t(r)
WHERE outcome IN ('needs_approval', 'approved', 'rejected') AND ts >= {start} AND ts < {end}
ORDER BY ts, who"""},
    {"id": "decisions-by-status", "question": "How many decisions and work items are in each status?",
     "keywords": [("decision", "decisions", "work items", "status")],
     "sql": """SELECT kind, status, count(*) AS items, left(max(ts), 10) AS latest
FROM decisions
WHERE kind IN ('DECISION', 'WORK')
GROUP BY ALL ORDER BY kind, items DESC, status"""},
]


def match(question):
    """The template for a question, or None: of the templates whose every keyword group appears in the question, the
    most specific one (most groups); ties go to the first listed."""
    q = " " + re.sub(r"\s+", " ", str(question or "").lower()) + " "
    hits = [t for t in QUESTIONS if all(any(w in q for w in group) for group in t["keywords"])]
    return max(hits, key=lambda t: len(t["keywords"]), default=None)


def window(as_of=None, days=7):
    """(start, end) DATE literals: the `days` days ending on as_of (default today, UTC), end exclusive."""
    d = as_of if isinstance(as_of, date) else (date.fromisoformat(as_of) if as_of else datetime.now(timezone.utc).date())
    return f"DATE '{d - timedelta(days=days - 1)}'", f"DATE '{d + timedelta(days=1)}'"


def sql_for(template, as_of=None, days=7):
    start, end = window(as_of, days)
    return template["sql"].format(start=start, end=end, destructive=DESTRUCTIVE)


# ── connection ─────────────────────────────────────────────────────────────────────────────────────────────────
def connect(store, decision_events=None):
    """In-memory DuckDB with tables ev and decisions, external access off and configuration locked."""
    import duckdb
    import pyarrow as pa
    from . import store as telstore
    from ..decisions import graph
    con = duckdb.connect()
    view = store.materialize() if store is not None else None
    if view:
        con.execute("CREATE TABLE ev AS SELECT * FROM read_parquet(?)", [view])
    else:
        con.register("ev_empty", telstore._arrow_schema().empty_table())
        con.execute("CREATE TABLE ev AS SELECT * FROM ev_empty")
        con.unregister("ev_empty")
    nodes = graph.export_graph(graph.derive(decision_events))["nodes"] if decision_events else []
    rows = [{k: n.get(k) for k in DECISION_COLUMNS} for n in nodes if n.get("kind") in ("DECISION", "WORK", "THING")]
    con.register("dec_rows", pa.Table.from_pylist(rows, schema=pa.schema([(k, pa.string()) for k in DECISION_COLUMNS])))
    con.execute("CREATE TABLE decisions AS SELECT * FROM dec_rows")
    con.unregister("dec_rows")
    con.execute("SET enable_external_access = false")
    con.execute("SET lock_configuration = true")
    return con


def run(con, sql, limit=MAX_ROWS):
    """(columns, rows) for one SELECT. Raises QueryError for anything else or when DuckDB refuses it."""
    import duckdb
    try:
        stmts = con.extract_statements(sql)
    except duckdb.Error as e:
        raise QueryError(f"not valid SQL: {str(e).splitlines()[0]}") from None
    if len(stmts) != 1:
        raise QueryError("one statement per query")
    if stmts[0].type != duckdb.StatementType.SELECT:
        raise QueryError("read-only: only SELECT (or WITH … SELECT) queries are allowed")
    try:
        cur = con.execute(sql)
        cols = [d[0] for d in cur.description]
        rows = cur.fetchmany(limit + 1)
    except duckdb.Error as e:
        raise QueryError(str(e).splitlines()[0]) from None
    if len(rows) > limit:
        raise QueryError(f"more than {limit} rows: add a LIMIT or GROUP BY")
    return cols, rows


# ── output formats ─────────────────────────────────────────────────────────────────────────────────────────────
def _text(v):
    if v is None:
        return ""
    if isinstance(v, datetime):
        return v.isoformat(sep=" ", timespec="seconds")
    if isinstance(v, (list, dict)):
        return json.dumps(v, default=str, sort_keys=True)
    return str(v)


def _json_value(v):
    if isinstance(v, (datetime, date)):
        return v.isoformat()
    if isinstance(v, list):
        return [_json_value(x) for x in v]
    if isinstance(v, dict):
        return {str(k): _json_value(x) for k, x in v.items()}
    return v


def render(cols, rows, fmt="table"):
    """Text output for table, csv, json or md (Parquet is written by write_parquet)."""
    if fmt == "csv":
        buf = io.StringIO()
        w = csv.writer(buf, lineterminator="\n")
        w.writerow(cols)
        w.writerows([[_text(v) for v in r] for r in rows])
        return buf.getvalue()
    if fmt == "json":
        return json.dumps([{c: _json_value(v) for c, v in zip(cols, r)} for r in rows], indent=2, ensure_ascii=False) + "\n"
    cells = [[_text(v) for v in r] for r in rows]
    if fmt == "md":
        esc = lambda s: s.replace("|", "\\|")
        out = ["| " + " | ".join(cols) + " |", "|" + "|".join("---" for _ in cols) + "|"]
        out += ["| " + " | ".join(esc(c) for c in r) + " |" for r in cells]
        return "\n".join(out) + "\n"
    if fmt == "table":
        widths = [max([len(c)] + [len(r[i]) for r in cells]) for i, c in enumerate(cols)]
        line = lambda r: "  ".join(v.ljust(w) for v, w in zip(r, widths)).rstrip()
        out = [line(cols), line(["-" * w for w in widths])] + [line(r) for r in cells]
        return "\n".join(out) + f"\n({len(rows)} row{'s' if len(rows) != 1 else ''})\n"
    raise ValueError(f"format: one of {', '.join(FORMATS)}")


def write_parquet(con, sql, path):
    """Run the (already checked) query again and write the result with pyarrow — DuckDB itself cannot write files."""
    import pyarrow.parquet as pq
    rel = con.sql(sql)
    table = rel.to_arrow_table() if hasattr(rel, "to_arrow_table") else rel.arrow()    # duckdb 2 / 1
    pq.write_table(table, path, compression="zstd")
    return table.num_rows
