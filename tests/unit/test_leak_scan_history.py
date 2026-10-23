"""leak-scan --history: every blob in every commit is scanned, so a secret added and then deleted is still found."""
import importlib.util
import os
import subprocess

import pytest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
spec = importlib.util.spec_from_file_location("leak_scan", os.path.join(ROOT, "tools", "leak-scan.py"))
leak_scan = importlib.util.module_from_spec(spec)
spec.loader.exec_module(leak_scan)

# built at runtime so this test file itself never contains a matching token
FAKE_KEY = "gh" + "p_" + "A" * 36
FAKE_PEM = "-----BEGIN " + "OPENSSH PRIVATE KEY-----"


def git(repo, *args):
    env = dict(os.environ, GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@example.org",
               GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@example.org")
    return subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True, text=True, env=env).stdout


def commit(repo, files, msg, delete=()):
    for name, body in files.items():
        p = repo / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(body)
        git(repo, "add", name)
    for name in delete:
        git(repo, "rm", "-q", name)
    git(repo, "commit", "-q", "-m", msg)
    return git(repo, "rev-parse", "HEAD").strip()


@pytest.fixture
def repo(tmp_path):
    r = tmp_path / "r"
    r.mkdir()
    git(r, "init", "-q", "-b", "main")
    return r


def test_secret_added_then_deleted_is_found(repo):
    commit(repo, {"README.md": "hello\n"}, "init")
    bad = commit(repo, {"config.py": f"TOKEN = '{FAKE_KEY}'\n"}, "oops")
    commit(repo, {}, "remove", delete=["config.py"])
    assert leak_scan.history_findings(str(repo)) == [
        {"commit": bad, "path": "config.py", "line": 1, "rule": "api key", "in_head": False}]


def test_head_only_scan_misses_it_history_does_not(repo):
    commit(repo, {"a.txt": FAKE_PEM + "\n"}, "add key")
    commit(repo, {"a.txt": "clean now\n"}, "scrub")
    assert leak_scan.history_findings(str(repo))[0]["rule"] == "private key"
    out = subprocess.run(["python3", os.path.join(ROOT, "tools", "leak-scan.py")], cwd=repo,
                         capture_output=True, text=True)
    assert out.returncode == 0 and "clean" in out.stdout


def test_same_blob_reported_once_at_first_commit(repo):
    first = commit(repo, {"k.txt": FAKE_KEY + "\n"}, "one")
    commit(repo, {"other.txt": "x\n"}, "two")
    f = leak_scan.history_findings(str(repo))
    assert len(f) == 1 and f[0]["commit"] == first and f[0]["in_head"] is True


def test_other_branches_are_scanned(repo):
    commit(repo, {"README.md": "hi\n"}, "init")
    git(repo, "checkout", "-q", "-b", "side")
    side = commit(repo, {"s.txt": FAKE_KEY + "\n"}, "side secret")
    git(repo, "checkout", "-q", "main")
    assert [x["commit"] for x in leak_scan.history_findings(str(repo))] == [side]


def test_private_terms_in_history(repo, tmp_path):
    terms = tmp_path / "terms.txt"
    terms.write_text("# comment\nsecret-host-zeta\n")
    bad = commit(repo, {"notes.md": "deploy to Secret-Host-Zeta tonight\n"}, "notes")
    commit(repo, {"notes.md": "deploy tonight\n"}, "scrub")
    f = leak_scan.history_findings(str(repo), terms=leak_scan.load_terms(str(terms)))
    assert f == [{"commit": bad, "path": "notes.md", "line": 1, "rule": "private term", "in_head": False}]


def test_test_paths_keep_their_allowances(repo):
    commit(repo, {"tests/t.py": "ADDR = '192.168.1.10'\n", "src.py": "ADDR = '192.168.1.10'\n"}, "addrs")
    assert [x["path"] for x in leak_scan.history_findings(str(repo))] == ["src.py"]


def test_cli_history_never_prints_the_value(repo, tmp_path):
    bad = commit(repo, {"config.py": f"TOKEN = '{FAKE_KEY}'\n"}, "oops")
    commit(repo, {}, "remove", delete=["config.py"])
    out = subprocess.run(["python3", os.path.join(ROOT, "tools", "leak-scan.py"), "--history"], cwd=repo,
                         capture_output=True, text=True)
    assert out.returncode == 1
    assert FAKE_KEY not in out.stdout and bad[:12] in out.stdout and "config.py:1: api key" in out.stdout
    assert "history-only" in out.stdout


def test_cli_history_clean_repo(repo):
    commit(repo, {"README.md": "nothing to see\n"}, "init")
    out = subprocess.run(["python3", os.path.join(ROOT, "tools", "leak-scan.py"), "--history"], cwd=repo,
                         capture_output=True, text=True)
    assert out.returncode == 0 and "clean" in out.stdout


def test_commit_metadata_author_email_and_message(repo):
    commit(repo, {"README.md": "hi\n"}, "init")
    env = dict(os.environ, GIT_AUTHOR_NAME="p", GIT_AUTHOR_EMAIL="someone" + "@gmail.com",
               GIT_COMMITTER_NAME="p", GIT_COMMITTER_EMAIL="someone" + "@gmail.com")
    (repo / "x.txt").write_text("x\n")
    git(repo, "add", "x.txt")
    subprocess.run(["git", "-C", str(repo), "commit", "-q", "-m", "fix\n\ntoken " + FAKE_KEY], check=True, env=env)
    bad = git(repo, "rev-parse", "HEAD").strip()
    f = leak_scan.history_findings(str(repo))
    assert {(x["commit"], x["path"], x["rule"]) for x in f} == {
        (bad, "(commit author/committer)", "personal email"), (bad, "(commit message)", "api key")}
