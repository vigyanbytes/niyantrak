"""Proof — test evidence kept in the repository. Pure helpers used by tools/prove.py and the panel. Standard library only.

    proof/latest/   junit.xml · coverage/ (HTML) · coverage.json · leak-scan.txt · summary.json · screens/ · index.html
    proof/history.jsonl   one line per run: date, commit, counts, coverage

Nothing here reads secrets. Host names and absolute paths are scrubbed from what is kept (see scrub()).
"""
import html
import json
import os
import re
import xml.etree.ElementTree as ET

HISTORY_KEYS = ("date", "commit", "passed", "failed", "skipped", "total", "coverage_pct", "leak_scan")


def _empty_counts():
    return {"passed": 0, "failed": 0, "skipped": 0, "errors": 0, "total": 0}


def _outcome(case):
    if case.find("failure") is not None:
        return "failed"
    if case.find("error") is not None:
        return "error"
    if case.find("skipped") is not None:
        return "skipped"
    return "passed"


def _split_classname(classname):
    """tests.unit.test_beta.TestGroup -> ("tests/unit/test_beta.py", "TestGroup")."""
    parts = classname.split(".")
    for i, p in enumerate(parts):
        if p.startswith("test_") or p == "test":
            return "/".join(parts[:i + 1]) + ".py", "::".join(parts[i + 1:])
    return classname or "(unknown)", ""


def _count(counts, outcome):
    counts["total"] += 1
    if outcome == "error":
        counts["errors"] += 1
        counts["failed"] += 1
    else:
        counts[outcome] += 1


def parse_junit(path):
    """pytest JUnit XML -> {"tests": counts, "time": seconds, "files": [per-file counts + tests by name]}.
    Errors count as failed (and are also reported under "errors")."""
    out = {"tests": _empty_counts(), "time": 0.0, "files": []}
    try:
        root = ET.parse(path).getroot()
    except (OSError, ET.ParseError):
        return out
    suites = [root] if root.tag == "testsuite" else root.findall("testsuite")
    files = {}
    for s in suites:
        out["time"] += float(s.get("time") or 0)
        for case in s.iter("testcase"):
            fname, prefix = _split_classname(case.get("classname", ""))
            name = f"{prefix}::{case.get('name', '')}" if prefix else case.get("name", "")
            oc, t = _outcome(case), float(case.get("time") or 0)
            f = files.setdefault(fname, {"file": fname, **_empty_counts(), "time": 0.0, "tests": []})
            _count(f, oc)
            _count(out["tests"], oc)
            f["time"] = round(f["time"] + t, 3)
            f["tests"].append({"name": name, "outcome": oc, "time": round(t, 3)})
    out["time"] = round(out["time"], 3)
    out["files"] = sorted(files.values(), key=lambda f: f["file"])
    return out


def parse_coverage(path):
    """coverage.py JSON report -> {"total": pct, "files": {path: pct}} (one decimal)."""
    try:
        d = json.load(open(path, encoding="utf-8"))
        return {"total": round(d["totals"]["percent_covered"], 1),
                "files": {k: round(v["summary"]["percent_covered"], 1) for k, v in sorted(d.get("files", {}).items())}}
    except (OSError, ValueError, KeyError, TypeError):
        return {"total": None, "files": {}}


def leak_findings(output):
    """Number of findings from tools/leak-scan.py output, or None when it did not report."""
    m = re.search(r"leak-scan: \w+ \((\d+) finding", output or "")
    return int(m.group(1)) if m else None


def scrub(text, root):
    """Drop the machine's host name (JUnit hostname=) and the absolute checkout path from kept evidence."""
    text = re.sub(r'\s+hostname="[^"]*"', "", text)
    if root:
        text = text.replace(root.rstrip("/") + "/", "").replace(root.rstrip("/"), ".")
    return text


def build_summary(junit, coverage, leak_findings, git, timings, date):
    t = dict(junit["tests"])
    leak = "not run" if leak_findings is None else "clean" if leak_findings == 0 else f"{leak_findings} findings"
    ok = t["failed"] == 0 and t["total"] > 0 and leak == "clean"
    return {"date": date, "commit": git.get("commit"), "branch": git.get("branch"), "tree_clean": bool(git.get("tree_clean")),
            "result": "pass" if ok else "fail", "tests": t, "coverage_pct": coverage.get("total"), "leak_scan": leak,
            "timings": dict(timings), "files": junit["files"], "coverage_files": coverage.get("files", {}), "screens": []}


def history_entry(summary):
    t = summary["tests"]
    return {"date": summary["date"], "commit": summary["commit"], "passed": t["passed"], "failed": t["failed"],
            "skipped": t["skipped"], "total": t["total"], "coverage_pct": summary["coverage_pct"],
            "leak_scan": summary["leak_scan"]}


def append_history(path, summary):
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    e = history_entry(summary)
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(e, sort_keys=False) + "\n")
    return e


def read_history(path, limit=None):
    out = []
    try:
        lines = open(path, encoding="utf-8").read().splitlines()
    except OSError:
        return out
    for line in lines:
        try:
            v = json.loads(line)
        except ValueError:
            continue
        if isinstance(v, dict):
            out.append(v)
    return out[-limit:] if limit else out


def load_proof(proof_dir, limit=30):
    """What the panel shows: {"summary", "history"} or None when no proof run exists yet."""
    try:
        summary = json.load(open(os.path.join(proof_dir, "latest", "summary.json"), encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return {"summary": summary, "history": read_history(os.path.join(proof_dir, "history.jsonl"), limit)}


def safe_path(base, rel):
    """Absolute path of an existing regular file strictly inside base, or None. Refuses .., absolute paths, NUL and
    symlinks that lead outside."""
    if not rel or "\x00" in rel or rel.startswith(("/", "\\")) or os.path.isabs(rel):
        return None
    root = os.path.realpath(base)
    full = os.path.realpath(os.path.join(root, rel))
    if not full.startswith(root + os.sep) or not os.path.isfile(full):
        return None
    return full


# ── dashboard ──────────────────────────────────────────────────────────────────────────────────────────
CSS = """
:root{--bg:#faf6ee;--rail:#f3ecdd;--card:#fff;--sunk:#f7f2e7;--ink:#1c1814;--body:#3a332b;--muted:#6b6357;
--line:rgba(28,24,20,.12);--primary:#f59e0b;--link:#9a4f08;--ok:#166534;--okb:#dcfce7;--warn:#92400e;--warnb:#fef3c7;
--crit:#991b1b;--critb:#fee2e2;--c1:#d97706;--c2:#1d4ed8;--grid:rgba(28,24,20,.08);color-scheme:light}
@media (prefers-color-scheme: dark){:root{--bg:#020617;--rail:#0a1122;--card:#0f172a;--sunk:#0b1324;--ink:#f8fafc;--body:#cbd5e1;
--muted:#94a3b8;--line:rgba(255,255,255,.10);--link:#fbbf24;--ok:#4ade80;--okb:#052e16;--warn:#fbbf24;--warnb:#2a1a03;--crit:#f87171;
--critb:#2a0a0a;--c1:#fbbf24;--c2:#93c5fd;--grid:rgba(255,255,255,.08);color-scheme:dark}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--body);font:14px/20px Inter,system-ui,-apple-system,"Segoe UI",sans-serif}
main{max-width:1180px;margin:auto;padding:24px 16px;display:grid;gap:16px}a{color:var(--link)}
code,.mono{font-family:"JetBrains Mono",ui-monospace,monospace;font-size:12.5px}
h1{margin:0;color:var(--ink);font-size:22px}h2{margin:0 0 8px;color:var(--ink);font-size:16.5px}
.head{display:flex;flex-wrap:wrap;gap:10px;align-items:center}.muted{color:var(--muted);font-size:13px}
.card{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:16px 18px;min-width:0}
.tiles{display:grid;gap:16px;grid-template-columns:repeat(auto-fit,minmax(190px,1fr))}
.two{display:grid;gap:16px;grid-template-columns:repeat(auto-fit,minmax(300px,1fr))}
.label{font-size:11.5px;font-weight:600;letter-spacing:.06em;text-transform:uppercase;color:var(--muted)}
.metric{font-size:30px;line-height:38px;font-weight:700;color:var(--ink);font-variant-numeric:tabular-nums}
.pill{display:inline-flex;align-items:center;gap:6px;padding:2px 10px;border-radius:999px;font-size:12.5px;font-weight:600;white-space:nowrap}
.ok{color:var(--ok);background:var(--okb)}.warn{color:var(--warn);background:var(--warnb)}.crit{color:var(--crit);background:var(--critb)}
.wrap{overflow-x:auto}table{width:100%;border-collapse:collapse;font-size:13.5px}
th,td{text-align:left;padding:7px 8px;border-bottom:1px solid var(--line);vertical-align:top}
th{font-size:11.5px;letter-spacing:.06em;text-transform:uppercase;color:var(--muted);font-weight:600}td.n{text-align:right;font-variant-numeric:tabular-nums}
details summary{cursor:pointer}details ul{margin:6px 0 0;padding-left:18px}
.bar{height:8px;border-radius:4px;background:var(--sunk);overflow:hidden;min-width:80px}.bar i{display:block;height:100%;background:var(--c1)}
svg{width:100%;height:140px}svg .g{stroke:var(--grid)}svg text{fill:var(--muted);font-size:10px}
.shots{display:grid;gap:12px;grid-template-columns:repeat(auto-fit,minmax(260px,1fr))}
figure{margin:0}figure img{width:100%;border:1px solid var(--line);border-radius:6px}figcaption{font-size:12.5px;color:var(--muted)}
.links{display:flex;flex-wrap:wrap;gap:8px 16px}
@media (max-width: 640px){.metric{font-size:24px}main{padding:16px}}
"""


def _trend(values, top, color, unit=""):
    vals = [v for v in values if isinstance(v, (int, float))]
    if not vals:
        return '<p class="muted">No runs yet.</p>'
    top = top or max(vals) or 1
    w, h, pad = 300, 120, 8
    n = len(vals)
    xs = [pad + (w - 2 * pad) * (i / (n - 1) if n > 1 else 0.5) for i in range(n)]
    ys = [h - pad - (h - 2 * pad) * min(v, top) / top for v in vals]
    pts = " ".join(f"{x:.1f},{y:.1f}" for x, y in zip(xs, ys))
    dots = "".join(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="2.5" fill="var({color})"/>' for x, y in zip(xs, ys))
    return (f'<svg viewBox="0 0 {w} {h}" role="img" aria-label="trend, latest {vals[-1]}{unit}">'
            f'<line class="g" x1="{pad}" x2="{w - pad}" y1="{pad}" y2="{pad}"/><line class="g" x1="{pad}" x2="{w - pad}" y1="{h - pad}" y2="{h - pad}"/>'
            f'<text x="{pad}" y="{pad + 10}">{top:g}{unit}</text>'
            f'<polyline fill="none" stroke="var({color})" stroke-width="2" points="{pts}"/>{dots}</svg>')


def render_dashboard(summary, history, screens=None):
    e = lambda v: html.escape(str(v if v is not None else "—"))
    s, t = summary, summary["tests"]
    cov = f"{s['coverage_pct']}%" if s.get("coverage_pct") is not None else "n/a"
    res = '<span class="pill ok">PASS</span>' if s.get("result") == "pass" else '<span class="pill crit">FAIL</span>'
    tree = '<span class="pill ok">tree clean</span>' if s.get("tree_clean") else '<span class="pill warn">uncommitted changes</span>'
    leak_cls = "ok" if s.get("leak_scan") == "clean" else "crit"
    pill = {"passed": "ok", "skipped": "warn", "failed": "crit", "error": "crit"}
    rows = []
    for f in s.get("files", []):
        tests = "".join(f'<li><span class="pill {pill.get(x["outcome"], "warn")}">{e(x["outcome"])}</span> <code>{e(x["name"])}</code></li>'
                        for x in f.get("tests", []))
        rows.append(f'<tr><td><details><summary><code>{e(f["file"])}</code></summary><ul>{tests}</ul></details></td>'
                    f'<td class="n">{f["passed"]}</td><td class="n">{f["failed"]}</td><td class="n">{f["skipped"]}</td><td class="n">{f["time"]:.2f}s</td></tr>')
    covrows = "".join(f'<tr><td><code>{e(k)}</code></td><td class="n">{v}%</td><td><div class="bar"><i style="width:{float(v):.1f}%"></i></div></td></tr>'
                      for k, v in s.get("coverage_files", {}).items())
    timings = " · ".join(f"{e(k.replace('_', ' '))} {float(v):.1f}s" for k, v in s.get("timings", {}).items())
    shots = "".join(f'<figure><a href="{e(p)}"><img src="{e(p)}" alt="{e(os.path.basename(p))}" loading="lazy"></a>'
                    f'<figcaption>{e(os.path.basename(p)[:-4])}</figcaption></figure>' for p in (screens or []))
    hist = history or []
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Niyantrak Proof</title><style>{CSS}</style></head><body><main>
<div class="head"><h1>Niyantrak · Proof</h1>{res}{tree}</div>
<p class="muted">Run {e(s.get('date'))} · commit <code>{e(s.get('commit'))}</code> on <code>{e(s.get('branch'))}</code> · {timings}</p>
<div class="tiles">
 <div class="card"><div class="label">Tests passed</div><div class="metric">{t['passed']} / {t['total']}</div><div class="muted">{t['failed']} failed · {t['skipped']} skipped</div></div>
 <div class="card"><div class="label">Line coverage</div><div class="metric">{e(cov)}</div><div class="muted">package niyantrak</div></div>
 <div class="card"><div class="label">Leak scan</div><div class="metric"><span class="pill {leak_cls}">{e(s.get('leak_scan'))}</span></div><div class="muted">keys, tokens, private addresses</div></div>
 <div class="card"><div class="label">Last run</div><div class="metric mono" style="font-size:20px">{e(s.get('commit'))}</div><div class="muted">{e(str(s.get('date'))[:16].replace('T', ' '))}</div></div>
</div>
<div class="two">
 <div class="card"><h2>Tests passing over runs</h2>{_trend([h.get('passed') for h in hist], max([h.get('total') or 0 for h in hist] or [0]), '--c2')}<p class="muted">{len(hist)} run(s) in proof/history.jsonl</p></div>
 <div class="card"><h2>Coverage over runs</h2>{_trend([h.get('coverage_pct') for h in hist], 100, '--c1', '%')}</div>
</div>
<div class="card"><h2>Evidence files</h2><div class="links"><a href="coverage/index.html">Coverage report (HTML)</a><a href="junit.xml">junit.xml</a>
 <a href="coverage.json">coverage.json</a><a href="leak-scan.txt">leak-scan.txt</a><a href="summary.json">summary.json</a><a href="../history.jsonl">history.jsonl</a></div></div>
<div class="card"><h2>Tests by file</h2><div class="wrap"><table><thead><tr><th>File (open for every test)</th><th>Passed</th><th>Failed</th><th>Skipped</th><th>Time</th></tr></thead>
<tbody>{''.join(rows) or '<tr><td colspan="5" class="muted">No tests recorded.</td></tr>'}</tbody></table></div></div>
<div class="card"><h2>Coverage by file</h2><div class="wrap"><table><thead><tr><th>File</th><th>Covered</th><th></th></tr></thead><tbody>{covrows}</tbody></table></div></div>
{f'<div class="card"><h2>The panel at this commit</h2><div class="shots">{shots}</div></div>' if shots else ''}
<div class="card"><h2>Re-run it yourself</h2><p><code>python3 tools/prove.py</code> at commit <code>{e(s.get('commit'))}</code> — or
 <code>python3 -m pytest -q tests/unit</code> and <code>python3 tools/leak-scan.py</code>. The same commit must give the same counts.</p></div>
</main></body></html>
"""


def tree_clean(porcelain):
    """git status --porcelain output -> True when nothing outside proof/ (this run's own output) has changed."""
    paths = [l.strip().split(None, 1)[-1] for l in porcelain.splitlines() if l.strip()]   # robust to a stripped first line
    return not [p for p in paths if not p.strip('"').startswith("proof/")]
