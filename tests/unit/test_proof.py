"""Proof: test evidence kept in the repository — parsing, summary, history, dashboard, panel API, demo embed."""
import http.client
import importlib.util
import json
import os
import re
import threading
from http.server import ThreadingHTTPServer

import pytest

from niyantrak import proof
from niyantrak.panel import Handler

FIX = os.path.join(os.path.dirname(__file__), "fixtures")
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
GIT = {"commit": "abc1234", "branch": "main", "tree_clean": True}


def sample_summary(**kw):
    j = proof.parse_junit(os.path.join(FIX, "junit-sample.xml"))
    c = proof.parse_coverage(os.path.join(FIX, "coverage-sample.json"))
    args = dict(junit=j, coverage=c, leak_findings=0, git=GIT, timings={"unit_tests": 1.5, "leak_scan": 0.2},
                date="2026-10-23T10:00:00+05:30")
    args.update(kw)
    return proof.build_summary(**args)


# ── parsing ────────────────────────────────────────────────────────────────────────────────────────────
def test_parse_junit_counts_pass_fail_skip_error():
    j = proof.parse_junit(os.path.join(FIX, "junit-sample.xml"))
    assert j["tests"] == {"passed": 2, "failed": 2, "skipped": 1, "errors": 1, "total": 5}
    assert j["time"] == pytest.approx(1.25)


def test_parse_junit_groups_by_file_with_outcome():
    j = proof.parse_junit(os.path.join(FIX, "junit-sample.xml"))
    files = {f["file"]: f for f in j["files"]}
    assert list(files) == ["tests/unit/test_alpha.py", "tests/unit/test_beta.py"]
    a, b = files["tests/unit/test_alpha.py"], files["tests/unit/test_beta.py"]
    assert (a["passed"], a["failed"], a["skipped"]) == (1, 1, 0)
    assert (b["passed"], b["failed"], b["skipped"], b["errors"]) == (1, 1, 1, 1)
    assert {t["name"]: t["outcome"] for t in b["tests"]} == {
        "TestGroup::test_ok_two": "passed", "TestGroup::test_skipped": "skipped", "test_setup_error": "error"}
    assert {t["name"]: t["outcome"] for t in a["tests"]}["test_broken"] == "failed"
    assert a["time"] == pytest.approx(0.3)


def test_parse_junit_missing_or_broken_file_is_empty(tmp_path):
    bad = tmp_path / "bad.xml"
    bad.write_text("<not-closed")
    for p in (str(bad), str(tmp_path / "missing.xml")):
        j = proof.parse_junit(p)
        assert j["tests"]["total"] == 0 and j["files"] == []


def test_parse_coverage_total_and_per_file():
    c = proof.parse_coverage(os.path.join(FIX, "coverage-sample.json"))
    assert c == {"total": 87.2, "files": {"niyantrak/cli.py": 90.0, "niyantrak/panel.py": 83.8}}


def test_parse_coverage_missing_is_none(tmp_path):
    assert proof.parse_coverage(str(tmp_path / "nope.json")) == {"total": None, "files": {}}


def test_leak_findings_from_scanner_output():
    assert proof.leak_findings("x\nleak-scan: clean (0 finding(s))\n") == 0
    assert proof.leak_findings("LEAK a:1: api key\nleak-scan: FAIL (3 finding(s))") == 3
    assert proof.leak_findings("") is None


def test_scrub_removes_hostname_and_absolute_root():
    text = '<testsuite hostname="my-laptop" tests="1"><failure>/srv/work/repo/niyantrak/x.py:3</failure></testsuite>'
    out = proof.scrub(text, "/srv/work/repo")
    assert "my-laptop" not in out and "hostname=" not in out and "/srv/work" not in out
    assert "niyantrak/x.py:3" in out


# ── summary and history ────────────────────────────────────────────────────────────────────────────────
def test_build_summary_shape():
    s = sample_summary()
    assert s["date"] == "2026-10-23T10:00:00+05:30" and s["commit"] == "abc1234" and s["branch"] == "main"
    assert s["tree_clean"] is True
    assert s["tests"] == {"passed": 2, "failed": 2, "skipped": 1, "errors": 1, "total": 5}
    assert s["coverage_pct"] == 87.2 and s["leak_scan"] == "clean"
    assert s["timings"] == {"unit_tests": 1.5, "leak_scan": 0.2}
    assert [f["file"] for f in s["files"]] == ["tests/unit/test_alpha.py", "tests/unit/test_beta.py"]
    assert s["coverage_files"]["niyantrak/cli.py"] == 90.0
    assert s["result"] == "fail"
    json.dumps(s)


def test_build_summary_leak_findings_and_pass():
    assert sample_summary(leak_findings=2)["leak_scan"] == "2 findings"
    assert sample_summary(leak_findings=None)["leak_scan"] == "not run"
    clean = {"tests": {"passed": 3, "failed": 0, "skipped": 0, "errors": 0, "total": 3}, "time": 0.1, "files": []}
    assert sample_summary(junit=clean)["result"] == "pass"
    assert sample_summary(junit=clean, leak_findings=1)["result"] == "fail"


def test_history_append_and_read_last_n(tmp_path):
    h = str(tmp_path / "sub" / "history.jsonl")
    assert proof.read_history(h) == []
    for i in range(35):
        proof.append_history(h, sample_summary(git={**GIT, "commit": f"c{i:03d}"}))
    lines = open(h).read().splitlines()
    assert len(lines) == 35
    first = json.loads(lines[0])
    assert first == {"date": "2026-10-23T10:00:00+05:30", "commit": "c000", "passed": 2, "failed": 2, "skipped": 1,
                     "total": 5, "coverage_pct": 87.2, "leak_scan": "clean"}
    last30 = proof.read_history(h, 30)
    assert len(last30) == 30 and last30[0]["commit"] == "c005" and last30[-1]["commit"] == "c034"


def test_read_history_skips_corrupt_lines(tmp_path):
    h = tmp_path / "history.jsonl"
    h.write_text('{"commit": "a"}\nnot json\n\n{"commit": "b"}\n')
    assert [x["commit"] for x in proof.read_history(str(h))] == ["a", "b"]


# ── dashboard ──────────────────────────────────────────────────────────────────────────────────────────
def test_dashboard_renders_key_numbers():
    s = sample_summary()
    hist = [{"date": "2026-10-22", "commit": "old", "passed": 1, "total": 2, "coverage_pct": 50.0},
            {"date": s["date"], "commit": "abc1234", "passed": 2, "total": 5, "coverage_pct": 87.2}]
    page = proof.render_dashboard(s, hist, screens=["screens/overview.png"])
    assert page.startswith("<!doctype html>")
    for want in ("2 / 5", "87.2%", "abc1234", "clean", "tests/unit/test_alpha.py", "test_broken",
                 'href="coverage/index.html"', 'href="junit.xml"', 'src="screens/overview.png"', "<svg"):
        assert want in page, want
    assert "prefers-color-scheme: dark" in page and "@media (max-width" in page
    for src in re.findall(r'<script[^>]+src="([^"]+)"', page):
        assert src.startswith("https://cdn.jsdelivr.net/npm/echarts@5.")


def test_dashboard_escapes_test_names():
    s = sample_summary()
    s["files"][0]["tests"][0]["name"] = "<script>alert(1)</script>"
    page = proof.render_dashboard(s, [])
    assert "<script>alert(1)" not in page and "&lt;script&gt;" in page


# ── loading and safe paths (panel side) ───────────────────────────────────────────────────────────────
def make_proof_dir(tmp_path, n_history=35):
    latest = tmp_path / "proof" / "latest"
    (latest / "coverage").mkdir(parents=True)
    (latest / "summary.json").write_text(json.dumps(sample_summary()))
    (latest / "junit.xml").write_text(open(os.path.join(FIX, "junit-sample.xml")).read())
    (latest / "coverage" / "index.html").write_text("<html>coverage report</html>")
    with open(tmp_path / "proof" / "history.jsonl", "w") as f:
        for i in range(n_history):
            f.write(json.dumps({"commit": f"c{i}", "passed": i, "total": 99, "coverage_pct": 80.0}) + "\n")
    (tmp_path / "secret.txt").write_text("TOP-SECRET-VALUE")
    return str(tmp_path / "proof")


def test_load_proof(tmp_path):
    assert proof.load_proof(str(tmp_path / "none")) is None
    d = proof.load_proof(make_proof_dir(tmp_path))
    assert d["summary"]["commit"] == "abc1234" and len(d["history"]) == 30 and d["history"][-1]["commit"] == "c34"


def test_safe_path_refuses_traversal(tmp_path):
    base = make_proof_dir(tmp_path) + "/latest"
    assert proof.safe_path(base, "junit.xml") == os.path.realpath(os.path.join(base, "junit.xml"))
    assert proof.safe_path(base, "coverage/index.html")
    for bad in ("../../secret.txt", "../history.jsonl", "/etc/passwd", "coverage/../../../secret.txt", "", "coverage",
                "nope.html", "junit.xml\x00.png"):
        assert proof.safe_path(base, bad) is None, bad
    os.symlink(str(tmp_path / "secret.txt"), os.path.join(base, "link.txt"))
    assert proof.safe_path(base, "link.txt") is None


# ── panel ──────────────────────────────────────────────────────────────────────────────────────────────
def start(proof_dir):
    srv = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    srv.proof_dir = proof_dir
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


def get(srv, path):
    c = http.client.HTTPConnection("127.0.0.1", srv.server_address[1], timeout=5)
    c.putrequest("GET", path, skip_accept_encoding=True)        # raw path: no client-side normalisation
    c.endheaders()
    r = c.getresponse()
    body = r.read()
    c.close()
    return r.status, r.getheader("Content-Type"), body


def test_api_proof_empty(tmp_path):
    srv = start(str(tmp_path / "proof"))
    try:
        code, ctype, body = get(srv, "/api/proof")
        assert code == 404 and ctype.startswith("application/json")
        d = json.loads(body)
        assert d["empty"] is True and "No proof run yet" in d["error"] and "tools/prove.py" in d["error"]
        assert get(srv, "/proof/junit.xml")[0] == 404
    finally:
        srv.shutdown()


def test_api_proof_populated(tmp_path):
    srv = start(make_proof_dir(tmp_path))
    try:
        code, _, body = get(srv, "/api/proof")
        d = json.loads(body)
        assert code == 200 and d["summary"]["tests"]["total"] == 5 and d["summary"]["coverage_pct"] == 87.2
        assert len(d["history"]) == 30 and d["history"][0]["commit"] == "c5"
    finally:
        srv.shutdown()


def test_proof_static_serves_read_only_and_refuses_traversal(tmp_path):
    srv = start(make_proof_dir(tmp_path))
    try:
        code, ctype, body = get(srv, "/proof/junit.xml")
        assert code == 200 and "xml" in ctype and b"test_broken" in body
        code, ctype, body = get(srv, "/proof/coverage/index.html")
        assert code == 200 and ctype.startswith("text/html") and b"coverage report" in body
        for bad in ("/proof/../../secret.txt", "/proof/%2e%2e/%2e%2e/secret.txt", "/proof/..%2f..%2fsecret.txt",
                    "/proof/coverage/../../../secret.txt", "/proof//etc/passwd", "/proof/%2fetc%2fpasswd",
                    "/proof/../history.jsonl", "/proof/"):
            code, _, body = get(srv, bad)
            assert code == 404 and b"TOP-SECRET" not in body and b"root:" not in body, bad
    finally:
        srv.shutdown()


def test_panel_has_proof_screen():
    page = open(os.path.join(ROOT, "niyantrak", "web", "index.html")).read()
    assert 'data-p="proof"' in page and 'id="proof"' in page
    nav = page.split('<div class="navgroup">Operate</div>', 1)[1].split('<div class="navgroup">', 1)[0]
    assert 'data-p="proof">Proof' in nav
    js = open(os.path.join(ROOT, "niyantrak", "web", "app.js")).read()
    assert 'api("proof")' in js and "No proof run yet" in js


# ── demo build ─────────────────────────────────────────────────────────────────────────────────────────
def load_build_demo():
    spec = importlib.util.spec_from_file_location("build_demo", os.path.join(ROOT, "tools", "build-demo.py"))
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def test_demo_build_embeds_proof(tmp_path):
    out = tmp_path / "demo.html"
    load_build_demo().build(str(out), proof_dir=make_proof_dir(tmp_path))
    html = out.read_text()
    assert "window.NIYANTRAK_PROOF" in html and "abc1234" in html
    assert "from the repository's latest proof run" in html
    m = re.search(r"window\.NIYANTRAK_PROOF = (.*?);\n", html)
    d = json.loads(m.group(1))
    assert d["summary"]["tests"]["passed"] == 2 and len(d["history"]) == 30


def test_demo_build_without_proof(tmp_path):
    out = tmp_path / "demo.html"
    load_build_demo().build(str(out), proof_dir=str(tmp_path / "none"))
    assert "window.NIYANTRAK_PROOF = null;" in out.read_text()


def test_tree_clean_ignores_proof_outputs():
    assert proof.tree_clean("") is True
    assert proof.tree_clean(" M proof/latest/summary.json\n?? proof/latest/screens/\n M proof/history.jsonl\n") is True
    assert proof.tree_clean(" M niyantrak/panel.py\n M proof/history.jsonl\n") is False
    assert proof.tree_clean("?? notes-proof/x\n") is False


def test_tree_clean_survives_stripped_first_line():
    from niyantrak import proof as P
    # git output with its leading space stripped (first line " D proof/..." becomes "D proof/...")
    assert P.tree_clean("D proof/latest/junit.xml\n?? proof/latest/index.html")
    assert not P.tree_clean("D proof/latest/junit.xml\n M niyantrak/panel.py")
    assert not P.tree_clean(" M README.md")
