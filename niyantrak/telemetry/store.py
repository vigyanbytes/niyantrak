"""6W store: append-only Parquet segments per writer, a hash-chained manifest per writer, a materialized view.

    <root>/segments/<writer>/<YYYY-MM>/seg-<ns>-<rand>.parquet      never edited; one month per segment
    <root>/manifest/<writer>.jsonl                                  one line per add / compact, each line carries
                                                                    sha256 of the file, rows, and `prev` = sha256 of
                                                                    the previous manifest line (edits break the chain)
    <root>/view/events.parquet + view/state.json                    materialize(): every live segment, by time
    <root>/salt                                                     per-store pseudonym salt (0600), made on first use
    <root>/settings.json                                            store settings (settings() / set_setting()):
                                                                    pseudonymise_which (default off) — `which` is
                                                                    stored as p-<12 hex> (HMAC with the salt) from
                                                                    then on, for teams that keep project names out

Each writer (a sink process, an importer) appends only to its own manifest, so writers never contend.
verify() reports: broken manifest chain, missing segment, sha256 or row-count mismatch, parquet files the manifest
does not list. materialize() (so every query) and compact() refuse to run on a store that fails verify()
(IntegrityError) — checked on every call, also when a cached view could be reused.
compact() merges one writer's segments per month (by default every month before the current one) into a single
segment, records it with the files it replaces, then deletes those files.
Queries run in DuckDB over the view; activity() returns exactly what the panel's Activity (6W) screen draws.
Segments written before 6W (schema niyantrak.5w/1) have no `which` column; they are read with which = null.
Needs the optional extra: pip install niyantrak[telemetry]  (pyarrow + duckdb).
"""
import hashlib
import json
import os
import re
import secrets
import time
from datetime import datetime, timedelta, timezone

from . import schema as S
from .schema import EventError  # noqa: F401  (re-exported for callers)

WRITER_RX = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
MONTH_RX = re.compile(r"^\d{4}-\d{2}$")
GENESIS = "0" * 64
DIMENSIONS = ("who", "agent", "what", "where", "why", "which")
FLOW = ("who", "agent", "which", "what", "where")                 # a null `which` is skipped: agent -> what
FILTER_KEYS = frozenset(("who", "whom", "agent", "what", "where", "why", "which", "outcome", "machine", "route"))
SETTINGS = {"pseudonymise_which": False}
VIEW_VERSION = "6w/1"                                              # part of the view digest: a 5W view is rebuilt
MAX_DAYS = 90
TOP = 20


class IntegrityError(RuntimeError):
    def __init__(self, problems):
        self.problems = problems
        super().__init__(f"6W store failed its integrity check ({len(problems)} problem(s))")


def available():
    try:
        import duckdb  # noqa: F401
        import pyarrow  # noqa: F401
        import pyarrow.parquet  # noqa: F401
    except ImportError:
        return False
    return True


def _sha(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _arrow_schema():
    import pyarrow as pa
    s = pa.string()
    return pa.schema([("event_id", s), ("ts", pa.timestamp("us")), ("who", s), ("who_id", s), ("whom", s), ("what", s), ("where", s),
                      ("why", s), ("which", s), ("agent", s), ("route", s), ("machine", s), ("session", s),
                      ("rule_ids", pa.list_(s)), ("outcome", s), ("entity_counts", pa.map_(s, pa.int64())),
                      ("entity_total", pa.int64()), ("source", s), ("schema", s)])


def _row(e):
    r = {c: e.get(c) for c in S.COLUMNS}
    r["ts"] = S.parse_ts(e["ts"])
    r["entity_counts"] = sorted(e["entity_counts"].items())
    r["entity_total"] = sum(e["entity_counts"].values())
    return r


class Store:
    def __init__(self, root, writer="local"):
        if not WRITER_RX.match(str(writer)):
            raise ValueError("writer: letters, digits, dot, dash, underscore (max 64)")
        self.root = os.path.abspath(root)
        self.writer = writer

    # ── paths and manifest ────────────────────────────────────────────────────────────────────────────
    def _p(self, *parts):
        return os.path.join(self.root, *parts)

    def salt(self):
        p = self._p("salt")
        if not os.path.isfile(p):
            os.makedirs(self.root, exist_ok=True)
            try:
                fd = os.open(p, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                with os.fdopen(fd, "w") as f:
                    f.write(secrets.token_hex(32))
            except FileExistsError:
                pass
        return open(p).read().strip()

    def settings(self):
        """The store's settings: SETTINGS with what settings.json overrides (unknown keys are ignored)."""
        out = dict(SETTINGS)
        try:
            with open(self._p("settings.json"), encoding="utf-8") as f:
                saved = json.load(f)
            out.update({k: v for k, v in saved.items() if k in SETTINGS and isinstance(v, type(SETTINGS[k]))})
        except (OSError, ValueError, AttributeError):
            pass
        return out

    def set_setting(self, key, value):
        if key not in SETTINGS:
            raise ValueError(f"setting: one of {', '.join(sorted(SETTINGS))}")
        if not isinstance(value, type(SETTINGS[key])):
            raise ValueError(f"{key}: {type(SETTINGS[key]).__name__}")
        cur = self.settings()
        cur[key] = value
        os.makedirs(self.root, exist_ok=True)
        tmp = self._p("settings.json.tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(cur, f, indent=1, sort_keys=True)
        os.replace(tmp, self._p("settings.json"))
        return cur

    def _manifests(self):
        d = self._p("manifest")
        return sorted(os.path.join(d, f) for f in os.listdir(d) if f.endswith(".jsonl")) if os.path.isdir(d) else []

    def _raw_lines(self, path):
        with open(path) as f:
            return [l.rstrip("\n") for l in f if l.strip()]

    def _record(self, entry):
        d = self._p("manifest")
        os.makedirs(d, exist_ok=True)
        path = os.path.join(d, f"{self.writer}.jsonl")
        lines = self._raw_lines(path) if os.path.isfile(path) else []
        entry["prev"] = hashlib.sha256(lines[-1].encode()).hexdigest() if lines else GENESIS
        with open(path, "a") as f:
            f.write(json.dumps(entry, sort_keys=True, separators=(",", ":")) + "\n")
            f.flush()
            os.fsync(f.fileno())

    def segments(self, writer=None):
        """Live segments (added and not compacted away), across all writers unless one is named."""
        live = {}
        for path in self._manifests():
            if writer and os.path.basename(path) != f"{writer}.jsonl":
                continue
            for raw in self._raw_lines(path):
                e = json.loads(raw)
                for old in e.get("replaces", []):
                    live.pop(old, None)
                live[e["file"]] = e
        return [live[k] for k in sorted(live)]

    # ── writing ──────────────────────────────────────────────────────────────────────────────────────
    def _write(self, rows, month, prefix="seg"):
        import pyarrow as pa
        import pyarrow.parquet as pq
        rel = f"segments/{self.writer}/{month}/{prefix}-{time.time_ns()}-{secrets.token_hex(2)}.parquet"
        full = self._p(rel)
        os.makedirs(os.path.dirname(full), exist_ok=True)
        table = rows if isinstance(rows, pa.Table) else pa.Table.from_pylist(rows, schema=_arrow_schema())
        tmp = full + ".tmp"
        pq.write_table(table.sort_by("ts"), tmp, compression="zstd")
        os.replace(tmp, full)
        ts = table.column("ts")
        return rel, {"file": rel, "sha256": _sha(full), "rows": table.num_rows, "month": month,
                     "writer": self.writer, "min_ts": str(min(ts.to_pylist())), "max_ts": str(max(ts.to_pylist())),
                     "at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")}

    def append(self, events):
        """Validate every event first (nothing is written if one fails), then one new segment per month."""
        valid = [S.validate(e) for e in events]
        if not valid:
            return []
        if self.settings()["pseudonymise_which"]:
            salt = self.salt()
            for e in valid:
                if e.get("which") and not S.PSEUDONYM_RX.match(e["which"]):
                    e["which"] = S.pseudonym(e["which"], salt)
        by_month = {}
        for e in valid:
            by_month.setdefault(e["ts"][:7], []).append(_row(e))
        out = []
        for month in sorted(by_month):
            rel, entry = self._write(by_month[month], month)
            self._record({"op": "add", **entry})
            out.append(rel)
        return out

    # ── integrity ────────────────────────────────────────────────────────────────────────────────────
    def verify(self):
        import pyarrow.parquet as pq
        problems = []
        for path in self._manifests():
            prev = GENESIS
            for i, raw in enumerate(self._raw_lines(path), 1):
                try:
                    e = json.loads(raw)
                except ValueError:
                    e = {}
                if e.get("prev") != prev:
                    problems.append({"file": os.path.relpath(path, self.root), "problem": f"manifest chain broken at line {i}"})
                prev = hashlib.sha256(raw.encode()).hexdigest()
        live = self.segments()
        listed = set()
        for e in live:
            listed.add(e["file"])
            full = self._p(e["file"])
            if not os.path.isfile(full):
                problems.append({"file": e["file"], "problem": "missing"})
            elif _sha(full) != e["sha256"]:
                problems.append({"file": e["file"], "problem": "sha256 does not match the manifest"})
            elif pq.ParquetFile(full).metadata.num_rows != e["rows"]:
                problems.append({"file": e["file"], "problem": "row count does not match the manifest"})
        seg_root = self._p("segments")
        for d, _, files in os.walk(seg_root):
            for f in files:
                rel = os.path.relpath(os.path.join(d, f), self.root).replace(os.sep, "/")
                if f.endswith(".parquet") and rel not in listed:
                    problems.append({"file": rel, "problem": "not in manifest"})
        return problems

    def _check(self):
        problems = self.verify()
        if problems:
            raise IntegrityError(problems)

    # ── view ─────────────────────────────────────────────────────────────────────────────────────────
    def materialize(self):
        """Build (or reuse) view/events.parquet from every live segment. None when the store is empty."""
        import pyarrow as pa
        import pyarrow.parquet as pq
        live = self.segments()
        view, state = self._p("view", "events.parquet"), self._p("view", "state.json")
        digest = hashlib.sha256((VIEW_VERSION + "".join(e["file"] + e["sha256"] for e in live)).encode()).hexdigest()
        self._check()                    # every time, also before reusing the view: a segment edited after the view
        try:                             # was built must not go unnoticed (the digest covers the manifest only)
            st = json.load(open(state))
            if st["digest"] == digest and os.path.isfile(view) and _sha(view) == st["sha256"]:
                return view
        except (OSError, ValueError, KeyError):
            pass
        if not live:
            for p in (view, state):
                if os.path.exists(p):
                    os.remove(p)
            return None
        table = pa.concat_tables([pq.read_table(self._p(e["file"]), schema=_arrow_schema()) for e in live]).sort_by("ts")
        os.makedirs(os.path.dirname(view), exist_ok=True)
        pq.write_table(table, view + ".tmp", compression="zstd")
        os.replace(view + ".tmp", view)
        with open(state + ".tmp", "w") as f:
            json.dump({"digest": digest, "sha256": _sha(view), "rows": table.num_rows, "segments": len(live)}, f)
        os.replace(state + ".tmp", state)
        return view

    def compact(self, month=None, now=None):
        """Merge this writer's segments per month into one. Default: every month before the current one."""
        import pyarrow as pa
        import pyarrow.parquet as pq
        if month is not None and not MONTH_RX.match(month):
            raise ValueError("month: YYYY-MM")
        self._check()
        current = (now or datetime.now(timezone.utc)).strftime("%Y-%m")
        groups = {}
        for e in self.segments(self.writer):
            groups.setdefault(e["month"], []).append(e)
        made = []
        for m in sorted(groups):
            if (month and m != month) or (not month and m >= current) or len(groups[m]) < 2:
                continue
            olds = groups[m]
            table = pa.concat_tables([pq.read_table(self._p(e["file"]), schema=_arrow_schema()) for e in olds])
            if table.num_rows != sum(e["rows"] for e in olds):
                raise IntegrityError([{"file": m, "problem": "row count changed while compacting"}])
            rel, entry = self._write(table, m, prefix="compact")
            self._record({"op": "compact", **entry, "replaces": [e["file"] for e in olds]})
            for e in olds:
                os.remove(self._p(e["file"]))
            made.append(rel)
        return made

    # ── queries ──────────────────────────────────────────────────────────────────────────────────────
    def _con(self):
        import duckdb
        view = self.materialize()
        if view is None:
            return None
        con = duckdb.connect()
        con.execute(f"CREATE VIEW ev AS SELECT * FROM read_parquet('{view.replace(chr(39), chr(39) * 2)}')")
        return con

    def count(self):
        con = self._con()
        return 0 if con is None else con.execute("SELECT count(*) FROM ev").fetchone()[0]

    def activity(self, days=7, now=None, filter=None):
        """The Activity (6W) screen's data: Sankey links, week by outcome, why by rule, infra by machine."""
        if filter is not None and (filter[0] not in FILTER_KEYS or not isinstance(filter[1], str)):
            raise ValueError(f"filter: one of {', '.join(sorted(FILTER_KEYS))}")
        days = max(1, min(int(days), MAX_DAYS))
        now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc).replace(tzinfo=None)
        today = now.replace(hour=0, minute=0, second=0, microsecond=0)
        start, end = today - timedelta(days=days - 1), today + timedelta(days=1)
        day_list = [(start + timedelta(days=i)).strftime("%Y-%m-%d") for i in range(days)]
        con = self._con()
        if con is None:
            return {"empty": True, "days": days, "total": 0,
                    "reason": "No activity recorded yet: send 6W events to the sink (niyantrak telemetry sink)."}
        where, params = 'ts >= ? AND ts < ?', [start, end]
        if filter:
            where += f' AND "{filter[0]}" = ?'
            params.append(filter[1])
        # every query reads the window `w`; values are bound parameters, column names come from FILTER_KEYS
        q = lambda sql: con.execute(f"WITH w AS (SELECT * FROM ev WHERE {where}) {sql}", params).fetchall()
        total = q("SELECT count(*) FROM w")[0][0]

        names, nodes, links = {}, [], {}
        def node(col, val):
            key = (col, val if val is not None else f"(no {col})")
            if key not in names:
                taken = {n["name"] for n in nodes}
                disp = key[1] if key[1] not in taken else f"{key[1]} ({col})"
                names[key] = disp
                nodes.append({"name": disp, "col": col, "value": val})
            return names[key]
        for row in q('SELECT who, agent, which, what, "where", count(*) FROM w GROUP BY ALL ORDER BY 6 DESC, 1, 2, 3, 4, 5'):
            path = [node(c, v) for c, v in zip(FLOW, row[:5]) if not (c == "which" and v is None)]
            n = row[5]
            for a, b in zip(path, path[1:]):
                links[(a, b)] = links.get((a, b), 0) + n

        by_day = {(d.strftime("%Y-%m-%d"), o): n for d, o, n in q("SELECT CAST(ts AS DATE), outcome, count(*) FROM w GROUP BY ALL")}
        present = {o for _, o in by_day}
        outcomes = [o for o in S.OUTCOMES if o in present]

        infra_rows = q("SELECT machine, outcome, count(*) FROM w WHERE machine IS NOT NULL GROUP BY ALL")
        host_tot = {}
        for m, _, n in infra_rows:
            host_tot[m] = host_tot.get(m, 0) + n
        hosts = sorted(host_tot, key=lambda h: (-host_tot[h], h))
        cell = {(m, o): n for m, o, n in infra_rows}
        infra_out = [o for o in S.OUTCOMES if any(k[1] == o for k in cell)]

        top = lambda sql: [{"name": a, "value": b} for a, b in q(sql)]
        return {
            "empty": False, "days": days, "from": day_list[0], "to": day_list[-1], "total": total,
            "filter": {"k": filter[0], "v": filter[1]} if filter else None,
            "sankey": {"nodes": nodes, "links": [{"source": a, "target": b, "value": v} for (a, b), v in links.items()]},
            "week": {"days": day_list, "outcomes": outcomes,
                     "series": [{"name": o, "data": [by_day.get((d, o), 0) for d in day_list]} for o in outcomes]},
            "why": top("SELECT why, count(*) n FROM w GROUP BY 1 ORDER BY n DESC, 1"),
            "rules": top("SELECT r, count(*) n FROM (SELECT unnest(rule_ids) r FROM w) GROUP BY 1 ORDER BY n DESC, 1"),
            "infra": {"hosts": hosts, "series": [{"name": o, "data": [cell.get((h, o), 0) for h in hosts]} for o in infra_out]},
            "by": {d: top(f'SELECT "{d}", count(*) n FROM w WHERE "{d}" IS NOT NULL GROUP BY 1 ORDER BY n DESC, 1 LIMIT {TOP}')
                   for d in DIMENSIONS},
        }
