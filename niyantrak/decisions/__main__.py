"""niyantrak decisions — the decision log from the command line.

    niyantrak decisions write events.jsonl        append one segment (validated, secret/personal-data checked)
    niyantrak decisions open [--limit N]          exact lists: pending decisions, blocked / in progress / proposed / to do work
    niyantrak decisions materialize               rebuild <root>/state/ (graph.json; Parquet when pyarrow is installed)
    niyantrak decisions export OUT.json           the graph JSON the panel's Decisions screen shows
    niyantrak decisions verify                    every segment against manifest.jsonl
    niyantrak decisions ask "question" [--endpoint URL] [--allow-host H] [--list-only]   local model only
    [--root DIR]  default $NIYANTRAK_DECISIONS, else <state root>/decisions
Actor fields come from $NIYANTRAK_USER, $NIYANTRAK_AGENT, $NIYANTRAK_PRODUCT, $NIYANTRAK_SESSION_ID when not in the event.
"""
import argparse
import json
import os
import sys

from . import ask as askmod
from . import graph, schema
from .store import Store


def _write(a, s):
    with open(a.file, encoding="utf-8") as f:
        rows = [json.loads(l) for l in f if l.strip()]
    try:
        from .. import identity
        p = s.append(rows, writer=os.environ.get("NIYANTRAK_SESSION_ID") or "cli", actor=identity.current(),
                     agent=identity.agent())
    except (schema.EventError, schema.PrivacyError) as e:
        print(f"decisions: {e}", file=sys.stderr)
        return 1
    print(f"wrote {len(rows)} event(s) -> {p}")
    return 0


def _open(a, s):
    groups = {g["key"]: g for g in graph.open_items(graph.derive(s.events()))}
    for key, label in graph.OPEN_GROUPS:
        items = groups.get(key, {}).get("items", [])
        print(f"\n{label} ({len(items)})")
        for i in items[: a.limit]:
            print(f"  {str(i['ts'] or '')[:10]:10}  {i['id']}  — {schema.short(i['title'], 90)}")
        if len(items) > a.limit:
            print(f"  … {len(items) - a.limit} more")
    return 0


def _materialize(a, s):
    for p in graph.materialize(s):
        print(p)
    return 0


def _export(a, s):
    with open(a.out, "w", encoding="utf-8") as f:
        json.dump(graph.export_graph(graph.derive(s.events())), f, sort_keys=True, indent=1, ensure_ascii=False)
        f.write("\n")
    print(f"wrote {a.out}")
    return 0


def _verify(a, s):
    ok, bad = s.verify()
    for b in bad:
        print(f"BAD {b}")
    print(f"{len(s.segments())} segment(s): {'ok' if ok else 'FAILED'}")
    return 0 if ok else 1


def _ask(a, s):
    try:
        r = askmod.ask(graph.derive(s.events()), a.question, endpoint=a.endpoint, model=a.model,
                       allow_host=a.allow_host, list_only=a.list_only)
    except askmod.RefusedEndpoint as e:
        print(f"decisions ask: {e}", file=sys.stderr)
        return 2
    if not r["rows"]:
        print("No matching rows in the decision log (nothing sent to the model).")
        return 0
    print(f"Exact rows ({len(r['rows'])}):")
    for x in r["rows"]:
        print(f"  [{x['kind']} · {x['status']}] {str(x['ts'] or '')[:10]}  {x['id']} — {schema.short(x['title'], 90)}")
    if r["answer"]:
        print("\nLocal model summary:\n" + r["answer"])
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(prog="niyantrak decisions", description="Decision log: append-only events, derived statuses.")
    ap.add_argument("--root")
    sp = ap.add_subparsers(dest="cmd", required=True)
    p = sp.add_parser("write"); p.add_argument("file"); p.set_defaults(f=_write)
    p = sp.add_parser("open"); p.add_argument("--limit", type=int, default=20); p.set_defaults(f=_open)
    sp.add_parser("materialize").set_defaults(f=_materialize)
    p = sp.add_parser("export"); p.add_argument("out"); p.set_defaults(f=_export)
    sp.add_parser("verify").set_defaults(f=_verify)
    p = sp.add_parser("ask"); p.add_argument("question"); p.add_argument("--endpoint"); p.add_argument("--allow-host")
    p.add_argument("--model"); p.add_argument("--list-only", action="store_true"); p.set_defaults(f=_ask)
    a = ap.parse_args(argv)
    return a.f(a, Store(a.root))


if __name__ == "__main__":
    sys.exit(main())
