#!/usr/bin/env python3
"""prove — run the unit suite and the leak scan, and keep the evidence in the repository.

    python3 tools/prove.py               # → proof/latest/ (replaced) + one line appended to proof/history.jsonl
    python3 tools/prove.py --no-screens  # skip the demo screenshots (CI)

proof/latest/: junit.xml (every test by name) · coverage/ (line coverage, HTML) · coverage.json (total + per file) ·
leak-scan.txt · summary.json · screens/*.png (demo pages with the sample team from tools/demo-data.py, when google-chrome is installed) · index.html (dashboard).
Needs pytest and pytest-cov for the interpreter that runs it (a repo .venv is used when present). Exit 1 when a test
fails or the leak scan finds anything. Host names and the checkout path are scrubbed from what is kept.
"""
import argparse
import datetime
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ROOT)
from niyantrak import proof  # noqa: E402

PROOF = os.path.join(ROOT, "proof")
LATEST = os.path.join(PROOF, "latest")
DEMO_PAGES = ["overview", "proof", "try", "fleet", "activity", "decisions", "rules"]


def python():
    v = os.path.join(ROOT, ".venv", "bin", "python")
    return v if os.path.exists(v) else sys.executable


def run(cmd, env=None):
    t = time.monotonic()
    r = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, env={**os.environ, **(env or {})})
    return r, round(time.monotonic() - t, 2)


def git(*args):
    return subprocess.run(["git", "-C", ROOT, *args], capture_output=True, text=True).stdout.strip()


def screenshots(out, tmp):
    chrome = shutil.which("google-chrome") or shutil.which("chromium")
    if not chrome:
        return []
    demo, data = os.path.join(tmp, "niyantrak-demo.html"), os.path.join(tmp, "demo-data")
    run([python(), "tools/demo-data.py", "--out", data])         # the fictional sample team, ending today
    run([python(), "tools/build-demo.py", demo, "--bundle", os.path.join(data, "bundle.json")])
    os.makedirs(os.path.join(out, "screens"), exist_ok=True)
    shots = []
    for p in DEMO_PAGES:
        png = os.path.join(out, "screens", f"{p}.png")
        for attempt in range(2):                  # a fresh profile per shot; headless Chrome occasionally stalls
            run(["timeout", "45", chrome, "--headless=new", "--disable-gpu", "--no-first-run",
                 f"--user-data-dir={tmp}/chrome-{p}-{attempt}", "--hide-scrollbars", "--window-size=1440,1000",
                 "--virtual-time-budget=6000", f"--screenshot={png}", f"file://{demo}#{p}"])
            if os.path.exists(png):
                break
        if os.path.exists(png):
            shots.append(f"screens/{p}.png")
    return shots


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--no-screens", action="store_true", help="skip demo screenshots")
    a = ap.parse_args(argv)
    tmp = tempfile.mkdtemp(prefix="niyantrak-proof-")
    try:
        shutil.rmtree(LATEST, ignore_errors=True)
        os.makedirs(LATEST)
        raw_junit, raw_cov = os.path.join(tmp, "junit.xml"), os.path.join(tmp, "coverage-raw.json")
        tests, t_tests = run([python(), "-m", "pytest", "-q", "-p", "no:cacheprovider", "tests/unit",
                              f"--junitxml={raw_junit}", "--cov=niyantrak", "--cov-report=",
                              f"--cov-report=html:{LATEST}/coverage", f"--cov-report=json:{raw_cov}"],
                             {"COVERAGE_FILE": os.path.join(tmp, ".coverage")})
        try:
            os.remove(os.path.join(LATEST, "coverage", ".gitignore"))   # coverage.py writes one; this is evidence to keep
        except OSError:
            pass
        if os.path.exists(raw_junit):
            open(os.path.join(LATEST, "junit.xml"), "w").write(proof.scrub(open(raw_junit).read(), ROOT))
        junit = proof.parse_junit(os.path.join(LATEST, "junit.xml"))
        cov = proof.parse_coverage(raw_cov)
        json.dump(cov, open(os.path.join(LATEST, "coverage.json"), "w"), indent=1)

        scan, t_scan = run([sys.executable, "tools/leak-scan.py"])
        open(os.path.join(LATEST, "leak-scan.txt"), "w").write(proof.scrub(scan.stdout + scan.stderr, ROOT))

        info = {"commit": git("rev-parse", "--short", "HEAD"), "branch": git("branch", "--show-current") or "detached",
                "tree_clean": proof.tree_clean(git("status", "--porcelain"))}
        date = datetime.datetime.now().astimezone().isoformat(timespec="seconds")
        summary = proof.build_summary(junit, cov, proof.leak_findings(scan.stdout), info,
                                      {"unit_tests": t_tests, "leak_scan": t_scan}, date)
        if tests.returncode not in (0, 1) and summary["tests"]["total"] == 0:   # pytest could not even run
            sys.stderr.write(tests.stdout[-2000:] + tests.stderr[-2000:])
        summary_path = os.path.join(LATEST, "summary.json")
        json.dump(summary, open(summary_path, "w"), indent=1)
        proof.append_history(os.path.join(PROOF, "history.jsonl"), summary)
        if not a.no_screens:
            t = time.monotonic()
            summary["screens"] = screenshots(LATEST, tmp)     # the demo embeds the summary just written
            summary["timings"]["screens"] = round(time.monotonic() - t, 2)
            json.dump(summary, open(summary_path, "w"), indent=1)
        hist = proof.read_history(os.path.join(PROOF, "history.jsonl"), 30)
        open(os.path.join(LATEST, "index.html"), "w").write(proof.render_dashboard(summary, hist, summary["screens"]))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    t = summary["tests"]
    print(f"proof: {summary['result'].upper()} · tests {t['passed']}/{t['total']} passed, {t['failed']} failed, "
          f"{t['skipped']} skipped · coverage {summary['coverage_pct']}% · leak scan {summary['leak_scan']} · "
          f"commit {summary['commit']}{'' if summary['tree_clean'] else ' (uncommitted changes)'}")
    print(f"dashboard: {os.path.relpath(os.path.join(LATEST, 'index.html'), ROOT)}")
    return 0 if summary["result"] == "pass" else 1


if __name__ == "__main__":
    sys.exit(main())
