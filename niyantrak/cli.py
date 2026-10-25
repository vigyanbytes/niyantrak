"""niyantrak — free command-line tools (Apache-2.0). Standard library only.

    niyantrak scan "My Aadhaar is 2345 6789 0124, UPI ramesh@okhdfc"     # what a governed gateway would mask
    niyantrak scan --file chat.txt --packs india,global --json
    niyantrak node                                                         # this node's bootstrap + governance status
    niyantrak decisions open                                               # decision log: open items (see --help)
    niyantrak docs generate [--out DIR]                                    # as-built docs from node cards + join store
    niyantrak gate install --cli all --home ~                              # hard-stop gate for AI coding agents
    niyantrak gate check --cli claude < payload.json                       # what a CLI hook runs
    niyantrak gate status
    niyantrak telemetry ask "who ran destructive commands this week"     # question -> SQL -> answer (6W store)

`scan` shows detection only (checksum-validated: an invalid Aadhaar or card number is left alone). Reversible
masking with reclaim, routing and evidence are in the commercial gateway.
"""
import argparse
import json
import os
import sys

from .paths import state_root
from .recognizers import PACKS, PRIORITY

PREFIX = os.environ.get("NIYANTRAK_ROOT", "")


def detect(text, packs):
    spans = []
    for p in packs:
        for entity, rx, ok in PACKS[p]:
            for m in rx.finditer(text):
                if ok is None or ok(m.group(0)):
                    spans.append((m.start(), m.end(), entity, m.group(0)))
    spans.sort(key=lambda s: (s[0], -(s[1] - s[0]), PRIORITY.get(s[2], 0)))
    out, end = [], -1
    for s in spans:
        if s[0] >= end:
            out.append(s)
            end = s[1]
    return out


def preview(text, spans):
    parts, pos, n = [], 0, {}
    for start, stop, entity, _ in spans:
        n[entity] = n.get(entity, 0) + 1
        parts += [text[pos:start], f"<{entity}_{n[entity]}>"]
        pos = stop
    return "".join(parts + [text[pos:]]), n


def cmd_scan(a):
    text = open(a.file, encoding="utf-8").read() if a.file else " ".join(a.text) if a.text else sys.stdin.read()
    packs = [p.strip() for p in a.packs.split(",") if p.strip()]
    unknown = [p for p in packs if p not in PACKS]
    if unknown:
        sys.exit(f"unknown pack(s) {unknown}; available: {', '.join(PACKS)}")
    spans = detect(text, packs)
    masked, counts = preview(text, spans)
    if a.json:
        print(json.dumps({"found": [{"entity": e, "start": s, "end": t} for s, t, e, _ in spans],
                          "counts": counts, "masked": masked}, indent=2))
        return 0
    if not spans:
        print("No personal identifiers found (checked packs: %s)." % ", ".join(packs))
        return 0
    print("A model would receive:\n  " + masked.replace("\n", "\n  "))
    print("\nFound: " + ", ".join(f"{k} {v}" for k, v in counts.items()))
    print("Values are never printed by this tool. Reclaim, routing and evidence: commercial gateway.")
    return 0


def cmd_node(a):
    root = f"{PREFIX}/var/lib/niyantrak/bootstrap"
    report = f"{root}/report.json"
    if not os.path.isfile(report):
        print("This machine has not been bootstrapped. Run: sudo bash bootstrap/niyantrak-bootstrap.sh --dry-run")
        return 1
    r = json.load(open(report))
    done = open(f"{root}/state").read().split() if os.path.isfile(f"{root}/state") else []
    print(f"node      {r.get('node_id')}   role {r.get('role')}   admin {r.get('admin')}")
    print(f"bootstrap v{r.get('version')} finished {r.get('finished')}   steps done {len(done)}")
    checks = [("audit rules", os.path.isfile(f"{PREFIX}/etc/audit/rules.d/50-niyantrak.rules")),
              ("ssh hardened", os.path.isfile(f"{PREFIX}/etc/ssh/sshd_config.d/10-niyantrak.conf")),
              ("secrets folder private", os.path.isdir(f"{PREFIX}/etc/niyantrak/secret.d")
               and oct(os.stat(f"{PREFIX}/etc/niyantrak/secret.d").st_mode)[-3:] == "700"),
              ("login status page", os.path.isfile(f"{PREFIX}/etc/update-motd.d/10-niyantrak"))]
    for name, ok in checks:
        print(f"  {'ok  ' if ok else 'FAIL'} {name}")
    return 0 if all(ok for _, ok in checks) else 1


def cmd_telemetry(a):
    """niyantrak telemetry [--dir D] [--writer W] sink|ingest|verify|materialize|compact|settings|activity|sql|ask"""
    from .telemetry import sink as telsink
    from .telemetry import store as telstore
    if not telstore.available():
        print("The 6W store needs the optional extra: pip install niyantrak[telemetry] (pyarrow + duckdb)", file=sys.stderr)
        return 2
    st = telstore.Store(a.dir or os.environ.get("NIYANTRAK_TELEMETRY") or os.path.join(state_root(), "telemetry"), a.writer)
    try:
        if a.tcmd == "sink":
            return telsink.serve(st, a.bind, a.port) or 0
        if a.tcmd == "ingest":
            from . import identity
            r = telsink.from_json(json.load(open(a.file) if a.file != "-" else sys.stdin),
                                  actor=identity.current(), agent=identity.agent())
            if r.events:
                st.append(r.events)
            print(json.dumps({"accepted": len(r.events), "rejected": r.errors}))
            return 1 if r.rejected else 0
        if a.tcmd == "verify":
            problems = st.verify()
            print(json.dumps({"ok": not problems, "segments": len(st.segments()), "problems": problems}, indent=2))
            return 1 if problems else 0
        if a.tcmd == "materialize":
            print(st.materialize() or "store is empty")
            return 0
        if a.tcmd == "compact":
            print(json.dumps({"compacted": st.compact(month=a.month)}))
            return 0
        if a.tcmd == "settings":
            if a.pseudonymise_which is not None:
                st.set_setting("pseudonymise_which", a.pseudonymise_which == "on")
            print(json.dumps(st.settings(), indent=1, sort_keys=True))
            return 0
        if a.tcmd == "activity":
            print(json.dumps(st.activity(days=a.days), indent=2, default=str))
            return 0
        if a.tcmd in ("sql", "ask"):
            return _telemetry_query(a, st)
    except telstore.IntegrityError as e:
        print(json.dumps({"ok": False, "problems": e.problems}, indent=2))
        return 1
    return 2

def _telemetry_query(a, st):
    """niyantrak telemetry sql|ask — read-only SQL over the 6W store and the decision log (niyantrak.telemetry.query)."""
    from .decisions.store import Store as DecisionStore
    from .telemetry import query as Q
    if a.tcmd == "ask" and (a.list or not a.question):
        print("Questions ask understands (their SQL runs over tables ev and decisions):")
        for t in Q.QUESTIONS:
            print(f"\n  {t['id']}: {t['question']}\n    " + Q.sql_for(t, a.as_of, a.days).replace("\n", "\n    "))
        return 0 if a.list else 2
    if a.format == "parquet" and not a.out:
        print("--format parquet needs --out FILE", file=sys.stderr)
        return 2
    if a.tcmd == "ask":
        t = Q.match(a.question)
        if t is None:
            print("Questions ask understands:\n" + "\n".join(f"  {q['question']}" for q in Q.QUESTIONS)
                  + "\nOr write the SQL yourself: niyantrak telemetry sql \"SELECT …\"")
            return 2
        sql = Q.sql_for(t, a.as_of, a.days)
        print(f"-- {t['question']}  [{t['id']}]\n{sql};\n", file=sys.stderr if a.out or a.format in ("csv", "json") else sys.stdout)
    else:
        sql = a.query
    dec = DecisionStore(a.decisions)
    try:
        con = Q.connect(st, dec.events() if dec.exists() else [])
        cols, rows = Q.run(con, sql)
        if a.format == "parquet":
            print(f"wrote {Q.write_parquet(con, sql, a.out)} row(s) to {a.out}")
            return 0
    except Q.QueryError as e:
        print(f"telemetry {a.tcmd}: {e}", file=sys.stderr)
        return 1
    text = Q.render(cols, rows, a.format)
    if a.out:
        with open(a.out, "w", encoding="utf-8", newline="") as f:
            f.write(text)
        print(f"wrote {len(rows)} row(s) to {a.out}")
    else:
        sys.stdout.write(text)
    return 0


def cmd_docs(a):
    from . import docs, join
    local = None
    if not a.no_local:
        from . import card
        from .panel import node_status
        local = {"card": card.collect(), "checks": node_status().get("checks") or []}
    out = a.out or docs.default_dir()
    changed = docs.generate(out, a.join_store or join.STORE, local=local)
    print(f"wrote {len(changed)} file(s) to {out}" if changed else f"unchanged: {out}")
    return 0


GATE_CLIS = ("claude", "codex", "gemini", "antigravity", "opencode")


def _gate_clis(spec):
    names = list(GATE_CLIS) if spec.strip() == "all" else [x.strip() for x in spec.split(",") if x.strip()]
    bad = [n for n in names if n not in GATE_CLIS]
    if bad or not names:
        sys.exit(f"unknown CLI(s) {bad}; use all or: {', '.join(GATE_CLIS)}")
    return names


def cmd_gate_check(a):
    from .gate import adapters
    out, err, code = adapters.handle(a.cli, sys.stdin.read())
    if out:
        print(out)
    if err:
        print(err, file=sys.stderr)
    return code


def _report(results):
    for r in results:
        print(f"{r.cli:12} {'ok  ' if r.ok else 'FAIL'} {r.message}  ({r.path})")
    return 0 if all(r.ok for r in results) else 1


def cmd_gate_install(a):
    from .gate import installers
    return _report(installers.install_many(_gate_clis(a.cli), a.home))


def cmd_gate_uninstall(a):
    from .gate import installers
    return _report(installers.uninstall_many(_gate_clis(a.cli), a.home))


def cmd_gate_status(a):
    from .gate import events, installers, mode
    st = {"mode": mode.current_mode(), "mode_file": mode.mode_file_path(), "log": events.log_path(),
          "home": a.home, "installed": installers.status(a.home)}
    if a.json:
        print(json.dumps(st, indent=2))
        return 0
    print(f"mode      {st['mode']}   (switch file {st['mode_file']})")
    print(f"log       {st['log']}")
    print(f"home      {st['home']}")
    for cli, ok in st["installed"].items():
        print(f"  {'hook' if ok else '--  '} {cli}")
    return 0


def main(argv=None):
    argv = sys.argv[1:] if argv is None else list(argv)
    if argv[:1] == ["decisions"]:                       # its own parser (options may come before the action)
        from .decisions.__main__ import main as decisions_main
        return decisions_main(argv[1:])
    ap = argparse.ArgumentParser(prog="niyantrak", description="Niyantrak free tools: identifier scan, node status, agent gate.")
    from . import __version__
    ap.add_argument("--version", action="version", version=f"niyantrak {__version__}")
    sp = ap.add_subparsers(dest="cmd", required=True)
    s = sp.add_parser("scan", help="show what a governed gateway would mask")
    s.add_argument("text", nargs="*")
    s.add_argument("--file")
    s.add_argument("--packs", default="india,eu,uk,us,health,global")
    s.add_argument("--json", action="store_true")
    s.set_defaults(f=cmd_scan)
    n = sp.add_parser("node", help="this node's bootstrap and governance status")
    n.set_defaults(f=cmd_node)
    w = sp.add_parser("panel", help="start the web panel (for people who never open a terminal)")
    w.add_argument("--bind", default="127.0.0.1")
    w.add_argument("--port", type=int, default=8770)
    w.add_argument("--join-bind", help="LAN or tailnet address (or ::) for the TLS join-only listener; off by default")
    w.add_argument("--join-port", type=int, default=8771)
    w.set_defaults(f=lambda a: __import__("niyantrak.panel", fromlist=["serve"]).serve(a.bind, a.port, a.join_bind, a.join_port))
    t = sp.add_parser("telemetry", help="6W activity store: sink, ingest, verify, materialize, compact, settings, activity, sql, ask")
    t.add_argument("--dir", help="store folder (default: $NIYANTRAK_TELEMETRY or <state>/telemetry)")
    t.add_argument("--writer", default="local", help="this writer's name (one manifest per writer)")
    t.add_argument("--decisions", help="decision log folder for the decisions table (default: $NIYANTRAK_DECISIONS or <state>/decisions)")
    tsp = t.add_subparsers(dest="tcmd", required=True)
    ts = tsp.add_parser("sink", help="OTLP/HTTP JSON (POST /v1/logs) and 6W JSON (POST /v1/events) receiver")
    ts.add_argument("--bind", default="127.0.0.1")
    ts.add_argument("--port", type=int, default=4318)
    ti = tsp.add_parser("ingest", help="append 6W (or 5W) events from a JSON file (- for stdin)")
    ti.add_argument("file")
    tsp.add_parser("verify", help="check every segment against the manifest")
    tsp.add_parser("materialize", help="rebuild the query view")
    tc = tsp.add_parser("compact", help="merge this writer's segments per month (default: months before this one)")
    tc.add_argument("--month", help="YYYY-MM")
    tset = tsp.add_parser("settings", help="show or change store settings (pseudonymise project names)")
    tset.add_argument("--pseudonymise-which", choices=["on", "off"],
                      help="on: store `which` (project / repo) as a salted pseudonym from now on; off: as given")
    tq = tsp.add_parser("activity", help="print what the panel's Activity (6W) screen shows")
    tq.add_argument("--days", type=int, default=7)
    for name, hlp in (("sql", "run one read-only SELECT over tables ev (6W events) and decisions"),
                      ("ask", "a question in plain words -> the SQL it becomes -> the answer (no model; see --list)")):
        tq = tsp.add_parser(name, help=hlp)
        if name == "sql":
            tq.add_argument("query", help="one SELECT statement")
        else:
            tq.add_argument("question", nargs="?")
            tq.add_argument("--list", action="store_true", help="print every question ask understands, with its SQL")
            tq.add_argument("--as-of", help="last day of the window, YYYY-MM-DD (default: today, UTC)")
            tq.add_argument("--days", type=int, default=7, help="window length in days (default 7: \"this week\")")
        tq.add_argument("--format", choices=["table", "csv", "json", "md", "parquet"], default="table")
        tq.add_argument("--out", help="write the result to this file (required for parquet)")
    t.set_defaults(f=cmd_telemetry)
    d = sp.add_parser("decisions", help="decision log: write, open, materialize, export, verify, ask (local model only)")
    d.add_argument("action", help="run `niyantrak decisions --help`")
    g = sp.add_parser("docs", help="as-built documents (Markdown + HTML + SVG) from node cards and the join store")
    g.add_argument("action", choices=["generate"])
    g.add_argument("--out", help="output folder (default $NIYANTRAK_DOCS, else <state root>/docs)")
    g.add_argument("--join-store", help="join store file (default: the panel's)")
    g.add_argument("--no-local", action="store_true", help="leave out this machine's own card and checks")
    g.set_defaults(f=cmd_docs)
    g = sp.add_parser("gate", help="hard-stop gate for AI coding agents (Claude Code, Codex, Gemini, Antigravity, OpenCode)")
    gs = g.add_subparsers(dest="gate_cmd", required=True)
    c = gs.add_parser("check", help="hook entry point: read a tool-call payload on stdin, answer allow/deny")
    c.add_argument("--cli", required=True, choices=GATE_CLIS)
    c.set_defaults(f=cmd_gate_check)
    for verb, fn in (("install", cmd_gate_install), ("uninstall", cmd_gate_uninstall)):
        i = gs.add_parser(verb, help=f"{verb} the gate hook in a home directory's CLI configs (merge, never clobber)")
        i.add_argument("--cli", default="all", help="all, or a comma list of: " + ", ".join(GATE_CLIS))
        i.add_argument("--home", default=os.path.expanduser("~"), help="home directory to write into")
        i.set_defaults(f=fn)
    st = gs.add_parser("status", help="machine mode, log location and where the hook is installed")
    st.add_argument("--home", default=os.path.expanduser("~"))
    st.add_argument("--json", action="store_true")
    st.set_defaults(f=cmd_gate_status)
    a = ap.parse_args(argv)
    return a.f(a)


if __name__ == "__main__":
    sys.exit(main())
