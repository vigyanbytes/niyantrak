"""Read side: derive the current graph from all events. Pure Python; DuckDB views are an optional extra.

Rules (status is derived, never stored):
- links: the latest event per (kind, src, dst) wins — add after retract makes a link live again.
- a decision is *superseded* when it has a live SUPERSEDED_BY link; *retired* when its latest RETIRED event is an
  add or its latest status is "dropped"; *pending* when its latest status is "proposed" or "to do"; otherwise
  *in force* (a "done" status closes a pending decision).
- work items take the bucket of their latest STATUS event, "to do" when none.
- "Latest" means the greatest (ts, write order); equal timestamps fall back to the order events were written.
"""
import json
import os

STATUS_BUCKETS = {
    "proposed": "proposed", "idea": "proposed", "hypothesis-unproven": "proposed",
    "agreed": "to do", "pending": "to do", "open": "to do", "todo": "to do", "to do": "to do",
    "in-progress": "in progress", "in_progress": "in progress", "in progress": "in progress", "active": "in progress",
    "built": "in progress", "built-awaiting-install": "in progress",
    "blocked": "blocked", "on-hold": "blocked", "on hold": "blocked", "parked": "blocked",
    "done": "done", "completed": "done", "resolved": "done", "closed": "done",
    "deferred": "dropped", "dropped": "dropped", "superseded": "dropped",
}
DECISION_STATUSES = ("in force", "pending", "superseded", "retired")
WORK_STATUSES = ("proposed", "to do", "in progress", "blocked", "done", "dropped")
OPEN_GROUPS = (("d:pending", "Decisions waiting for sign-off"), ("w:blocked", "Blocked / on hold"),
               ("w:in progress", "In progress"), ("w:proposed", "Proposed — waiting for a yes"),
               ("w:to do", "Agreed, not started"))
KIND_ORDER = {"DECISION": 0, "WORK": 1, "THING": 2, "SESSION": 3}
EMPTY_MESSAGE = ("No decisions recorded yet. Agents and people add them with `niyantrak decisions write events.jsonl`; "
                 "they appear here as a graph.")


def bucket(raw, archived=False):
    """Raw ledger word → one of the six work buckets."""
    r = str(raw or "").strip().lower()
    b = STATUS_BUCKETS.get(r) or next((v for k, v in STATUS_BUCKETS.items() if r.startswith(k)), None)
    return b or ("done" if archived else "to do")


def _latest(index, key, order, e):
    cur = index.get(key)
    if cur is None or order >= cur[0]:
        index[key] = (order, e)


def derive(events):
    links, status, retired, nodes, closed = {}, {}, {}, {}, {}
    for i, e in enumerate(events):
        order = (str(e.get("ts") or ""), i)
        k, src = e.get("kind"), e.get("src")
        if e.get("dst"):
            _latest(links, (k, src, e["dst"]), order, e)
        elif k == "STATUS" and e.get("op") == "add":
            _latest(status, src, order, e)
            if e.get("title") in ("done", "dropped") and e.get("written_by") == "reconcile":
                _latest(closed, src, order, e)
        elif k == "RETIRED":
            _latest(retired, src, order, e)
        elif k in ("DECISION", "WORK", "THING") and e.get("op") == "add":
            nodes.setdefault((k, src), []).append((order, e))
    live = sorted(key for key, (_, e) in links.items() if e.get("op") == "add")

    def facts(evs):
        evs = sorted(evs, key=lambda x: x[0])
        last = evs[-1][1]
        pick = lambda f: next((e[f] for _, e in reversed(evs) if e.get(f)), None)
        return {"title": pick("title"), "text": pick("text"), "ts": max(o[0] for o, _ in evs) or None,
                "user": last.get("user_id"), "agent": last.get("agent_id"), "product": last.get("product"),
                "session": last.get("session_id")}

    st = lambda s: bucket(status[s][1].get("title")) if s in status else None
    sup = {}
    for k, s, d in live:
        if k == "SUPERSEDED_BY":
            sup.setdefault(s, []).append(d)
    decisions, work, things, sessions = {}, {}, {}, {}
    for (k, s), evs in sorted(nodes.items(), key=lambda x: (x[0][1], x[0][0])):
        if k != "DECISION":
            continue
        latest = st(s)
        if s in sup:
            v = "superseded"
        elif (s in retired and retired[s][1].get("op") == "add") or latest == "dropped":
            v = "retired"
        elif latest in ("proposed", "to do"):
            v = "pending"
        else:
            v = "in force"
        decisions[s] = {"id": s, "kind": "DECISION", "status": v, "superseded_by": sorted(sup.get(s, [])), **facts(evs),
                        "auto_closed": closed[s][1].get("text") if s in closed else None}
    for (k, s), evs in sorted(nodes.items(), key=lambda x: (x[0][1], x[0][0])):
        if k == "WORK" and s not in decisions:
            work[s] = {"id": s, "kind": "WORK", "status": st(s) or "to do", **facts(evs),
                       "auto_closed": closed[s][1].get("text") if s in closed else None}
    for (k, s), evs in sorted(nodes.items(), key=lambda x: (x[0][1], x[0][0])):
        if k == "THING" and s not in decisions and s not in work:
            f = facts(evs)
            things[s] = {"id": s, "kind": "THING", "status": None, "title": f["title"] or s, "text": f["text"], "ts": None,
                         "user": None, "agent": None, "product": None, "session": None, "auto_closed": None}
    for k, s, d in live:
        if k == "DECIDED_IN" and d not in decisions and d not in work and d not in things:
            sessions[d] = {"id": d, "kind": "SESSION", "status": None, "title": d, "text": None, "ts": None,
                           "user": None, "agent": None, "product": None, "session": d, "auto_closed": None}
    ids = set(decisions) | set(work) | set(things) | set(sessions)
    edges = [{"source": s, "target": d, "kind": k} for k, s, d in live if s in ids and d in ids]
    edges.sort(key=lambda x: (x["source"], x["target"], x["kind"]))
    return {"decisions": decisions, "work": work, "things": things, "sessions": sessions, "edges": edges}


def category(n):
    if n["kind"] == "DECISION":
        return "d:" + n["status"]
    if n["kind"] == "WORK":
        return "w:" + n["status"]
    return n["kind"]


def all_nodes(g):
    ns = list(g["decisions"].values()) + list(g["work"].values()) + list(g["things"].values()) + list(g["sessions"].values())
    return sorted(ns, key=lambda n: (KIND_ORDER[n["kind"]], n["id"]))


def open_items(g):
    """Exact lists of what needs attention, newest first; only non-empty groups."""
    out = []
    ns = all_nodes(g)
    for key, label in OPEN_GROUPS:
        items = sorted((n for n in ns if category(n) == key), key=lambda n: n["id"])
        items.sort(key=lambda n: str(n["ts"] or ""), reverse=True)
        if items:
            out.append({"key": key, "label": label, "kind": "decision" if key.startswith("d:") else "work",
                        "status": key[2:], "items": [{"id": n["id"], "ts": n["ts"], "title": n["title"]} for n in items]})
    return out


def export_graph(g):
    """The panel's graph JSON: nodes, links, counts per status chip, open items. Deterministic for the same events."""
    ns = all_nodes(g)
    counts = {}
    for n in ns:
        counts[category(n)] = counts.get(category(n), 0) + 1
    keep = ("id", "kind", "status", "title", "text", "ts", "user", "agent", "product", "session", "auto_closed")
    out = {"nodes": [{k: n.get(k) for k in keep} for n in ns], "links": list(g["edges"]),
           "counts": dict(sorted(counts.items())), "open": open_items(g), "empty": not ns}
    if not ns:
        out["message"] = EMPTY_MESSAGE
    return out


def _atomic(path, data):
    tmp = path + ".tmp"
    with open(tmp, "wb") as f:
        f.write(data)
    os.replace(tmp, path)


def materialize(store):
    """Current state from ALL events, saved under <root>/state/. Never the source of truth: delete it and rerun for
    byte-identical files. graph.json always; decisions.parquet + edges.parquet when pyarrow is installed."""
    from .store import _pyarrow
    g = derive(store.events())
    d = os.path.join(store.root, "state")
    os.makedirs(d, exist_ok=True)
    paths = [os.path.join(d, "graph.json")]
    _atomic(paths[0], (json.dumps(export_graph(g), sort_keys=True, indent=1, ensure_ascii=False) + "\n").encode())
    pa = _pyarrow()
    if pa:
        rows = [{**n, "superseded_by": ",".join(n["superseded_by"]) or None} for n in g["decisions"].values()]
        cols = ("id", "status", "ts", "title", "text", "superseded_by", "user", "agent", "product", "session")
        for name, data, fields in (("decisions", rows, cols), ("edges", g["edges"], ("source", "target", "kind"))):
            table = pa.Table.from_pylist([{k: r.get(k) for k in fields} for r in data],
                                         schema=pa.schema([(k, pa.string()) for k in fields]))
            p = os.path.join(d, f"{name}.parquet")
            pa.parquet.write_table(table, p + ".tmp")
            os.replace(p + ".tmp", p)
            paths.append(p)
    return paths


def duckdb_views(store):
    """Optional: a DuckDB connection with tables/views ev, live_edges, latest_status, decisions, work, edges that
    follow the same rules as derive(). Needs the duckdb package."""
    import duckdb
    from .schema import FIELDS
    c = duckdb.connect()
    c.execute("CREATE TABLE ev (seq BIGINT, " + ", ".join(f"{f} TEXT" for f in FIELDS) + ")")
    rows = [(i, *[e.get(f) for f in FIELDS]) for i, e in enumerate(store.events())]
    if rows:
        c.executemany(f"INSERT INTO ev VALUES ({', '.join('?' * (len(FIELDS) + 1))})", rows)
    c.execute("""
      CREATE VIEW live_edges AS SELECT src, dst, kind FROM (
        SELECT *, row_number() OVER (PARTITION BY kind, src, dst ORDER BY coalesce(ts, '') DESC, seq DESC) AS rn
        FROM ev WHERE dst IS NOT NULL) WHERE rn = 1 AND op = 'add';
      CREATE VIEW latest_status AS SELECT src, title AS status FROM (
        SELECT *, row_number() OVER (PARTITION BY src ORDER BY coalesce(ts, '') DESC, seq DESC) AS rn
        FROM ev WHERE kind = 'STATUS' AND op = 'add') WHERE rn = 1;
      CREATE VIEW latest_retired AS SELECT src, op FROM (
        SELECT *, row_number() OVER (PARTITION BY src ORDER BY coalesce(ts, '') DESC, seq DESC) AS rn
        FROM ev WHERE kind = 'RETIRED') WHERE rn = 1;
      CREATE VIEW decisions AS
        SELECT d.src AS id, max(d.ts) AS ts,
          CASE WHEN EXISTS (SELECT 1 FROM live_edges s WHERE s.kind = 'SUPERSEDED_BY' AND s.src = d.src) THEN 'superseded'
               WHEN EXISTS (SELECT 1 FROM latest_retired r WHERE r.src = d.src AND r.op = 'add') THEN 'retired'
               WHEN (SELECT status FROM latest_status l WHERE l.src = d.src) = 'dropped' THEN 'retired'
               WHEN (SELECT status FROM latest_status l WHERE l.src = d.src) IN ('proposed', 'to do') THEN 'pending'
               ELSE 'in force' END AS status
        FROM ev d WHERE d.kind = 'DECISION' AND d.op = 'add' GROUP BY d.src;
      CREATE VIEW work AS
        SELECT w.src AS id, max(w.ts) AS ts, coalesce(any_value(l.status), 'to do') AS status
        FROM ev w LEFT JOIN latest_status l ON l.src = w.src
        WHERE w.kind = 'WORK' AND w.op = 'add' AND w.src NOT IN (SELECT id FROM decisions) GROUP BY w.src;
      CREATE VIEW edges AS SELECT src, dst, kind FROM live_edges;
    """)
    return c
