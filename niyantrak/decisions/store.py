"""Append-only event store: one immutable segment file per write plus manifest.jsonl (sha256 per segment).

    <root>/events/<YYYY-MM-DD>/seg-<ns>-<session>.parquet   (pyarrow installed)
    <root>/events/<YYYY-MM-DD>/seg-<ns>-<session>.jsonl     (standard library only)
    <root>/manifest.jsonl                                   one line per segment: file, sha256, rows, format

Segments are never edited. Each writer makes its own file (temp file + rename), so concurrent writers never
contend for a lock and a reader never sees half a segment. Both formats can live in one store and are read
together; Parquet needs the optional `pyarrow` package, nothing else does.
"""
import glob
import hashlib
import json
import os
import re
import time

from . import schema


def _pyarrow():
    try:
        import pyarrow
        import pyarrow.parquet  # noqa: F401
        return pyarrow
    except ImportError:
        return None


def default_root():
    from ..paths import state_root
    return os.environ.get("NIYANTRAK_DECISIONS") or os.path.join(state_root(), "decisions")


class Store:
    def __init__(self, root=None):
        self.root = root or default_root()

    def segments(self):
        """Relative paths of every segment, oldest first (the file name starts with the write time in ns)."""
        out = []
        for ext in ("parquet", "jsonl"):
            out += glob.glob(os.path.join(self.root, "events", "*", f"seg-*.{ext}"))
        key = lambda p: (os.path.basename(os.path.dirname(p)), int(re.match(r"seg-(\d+)", os.path.basename(p)).group(1)), p)
        return [os.path.relpath(p, self.root) for p in sorted(out, key=key)]

    def exists(self):
        return bool(self.segments())

    def append(self, rows, writer="manual", env=None, fmt=None, actor=None, agent=None):
        """Validate, privacy-check and write one new segment. Returns its path (None for an empty batch)."""
        if not rows:
            return None
        env = os.environ if env is None else env
        ns = time.time_ns()
        norm = [schema.normalize(r, writer, env, now_ns=ns + i, actor=actor, agent=agent) for i, r in enumerate(rows)]
        schema.check_privacy(norm)
        pa = _pyarrow() if fmt in (None, "parquet") else None
        if fmt == "parquet" and pa is None:
            raise RuntimeError("Parquet segments need the optional pyarrow package")
        ext = "parquet" if pa else "jsonl"
        sess = re.sub(r"[^A-Za-z0-9._-]", "_", norm[0].get("session_id") or "nosession")[:60]
        path = os.path.join(self.root, "events", time.strftime("%Y-%m-%d", time.gmtime(ns // 10**9)),
                            f"seg-{ns}-{sess}.{ext}")
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp = path + ".tmp"
        if pa:
            sch = pa.schema([(k, pa.string()) for k in schema.FIELDS])
            pa.parquet.write_table(pa.Table.from_pylist(norm, schema=sch), tmp)
        else:
            with open(tmp, "w", encoding="utf-8") as f:
                for r in norm:
                    f.write(json.dumps(r, ensure_ascii=False, sort_keys=True) + "\n")
        os.replace(tmp, path)
        with open(path, "rb") as fh:
            sha = hashlib.sha256(fh.read()).hexdigest()
        with open(os.path.join(self.root, "manifest.jsonl"), "a") as m:
            m.write(json.dumps({"file": os.path.relpath(path, self.root), "sha256": sha, "rows": len(norm),
                                "format": ext}) + "\n")
        return path

    def _read(self, rel):
        full = os.path.join(self.root, rel)
        if rel.endswith(".jsonl"):
            with open(full, encoding="utf-8") as f:
                return [json.loads(l) for l in f if l.strip()]
        pa = _pyarrow()
        if pa is None:
            raise RuntimeError(f"{rel} is Parquet; install pyarrow to read it")
        return pa.parquet.read_table(full).to_pylist()

    def events(self):
        """Every event in write order, each with every schema field."""
        out = []
        for rel in self.segments():
            for r in self._read(rel):
                out.append({k: r.get(k) for k in schema.FIELDS})
        return out

    def verify(self):
        """(ok, [segments whose bytes differ from the manifest or that the manifest does not list])."""
        listed = {}
        try:
            with open(os.path.join(self.root, "manifest.jsonl")) as f:
                for l in f:
                    if l.strip():
                        m = json.loads(l)
                        listed[m["file"]] = m["sha256"]
        except OSError:
            pass
        bad = []
        for rel in self.segments():
            with open(os.path.join(self.root, rel), "rb") as fh:
                if listed.get(rel) != hashlib.sha256(fh.read()).hexdigest():
                    bad.append(rel)
        bad += sorted(f for f in listed if not os.path.exists(os.path.join(self.root, f)))
        return (not bad), bad
