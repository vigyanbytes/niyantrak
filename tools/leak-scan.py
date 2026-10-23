#!/usr/bin/env python3
"""leak-scan -- refuse commits/releases that contain secrets or private infrastructure details.

    python3 tools/leak-scan.py [paths...]          # default: all tracked files (the working tree)
    python3 tools/leak-scan.py --history           # every blob in every commit on every ref (git rev-list --all)
    NIYANTRAK_PRIVATE_TERMS=/path/terms.txt ...    # extra terms (hostnames, usernames, internal domains), one per line,
                                                   # kept OUTSIDE this repo (CI: from a repository secret)
Exit 1 on any finding. Findings name the rule, path, line (and commit with --history) -- never the matched value.
Generic test fixtures (RFC 5737/1918 example ranges in tests) are allowed only under tests/ and proof/.
--history reports each offending blob once, at the first commit (oldest first) that contains it, and marks it
"history-only" when that content is no longer in HEAD: deleting a file does not remove it from history.
"""
import os
import re
import subprocess
import sys

PATTERNS = {
    "private key": re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    "api key": re.compile(r"\b(sk-[A-Za-z0-9_-]{20,}|ghp_[A-Za-z0-9]{30,}|AKIA[0-9A-Z]{16}|xox[baprs]-[A-Za-z0-9-]{10,}|AIza[0-9A-Za-z_-]{35})"),
    "age secret": re.compile(r"AGE-SECRET-KEY-1[0-9A-Z]{50,}"),
    "ssh public key": re.compile(r"ssh-(ed25519|rsa) AAAA[0-9A-Za-z+/]{40,}"),
    "tailnet name": re.compile(r"\b[a-z0-9-]+\.ts\.net\b"),
    "personal email": re.compile(r"\b[A-Za-z0-9._%+-]+@(gmail|yahoo|outlook|hotmail)\.com\b"),
    # an address, not a network range written as CIDR (192.168.0.0/16 is a generic range, not someone's home)
    "home LAN address": re.compile(r"\b192\.168\.\d{1,3}\.\d{1,3}\b(?!/\d)"),
    "tailnet address": re.compile(r"\b100\.(6[4-9]|[7-9]\d|1[01]\d|12[0-7])\.\d{1,3}\.\d{1,3}\b(?!/\d)"),
}
ALLOWED_IN_TESTS = {"home LAN address", "tailnet address"}
SKIP = {"LICENSE"}


def load_terms(path):
    if not path or not os.path.isfile(path):
        return []
    with open(path, encoding="utf-8") as fh:
        return [t.strip() for t in fh if t.strip() and not t.strip().startswith("#")]


def skipped(path):
    return os.path.basename(path) in SKIP or path.endswith("leak-scan.py")


def scan_text(path, text, terms=()):
    """[(line or None, rule)] for one file's text. Never returns the matched value."""
    out = []
    in_tests = path.startswith(("tests/", "proof/")) or "/tests/" in path     # proof/ holds test output
    for name, rx in PATTERNS.items():
        if in_tests and name in ALLOWED_IN_TESTS:
            continue
        for m in rx.finditer(text):
            out.append((text.count("\n", 0, m.start()) + 1, name))
    for t in terms:
        m = re.search(rf"(?<![\w-]){re.escape(t)}(?![\w-])", text, re.I)
        if m:
            out.append((text.count("\n", 0, m.start()) + 1, "private term"))
    return out


def files(args):
    if args:
        return args
    out = subprocess.run(["git", "ls-files"], capture_output=True, text=True).stdout.split()
    return [f for f in out if os.path.isfile(f)]


def _git(repo, *args, data=None):
    return subprocess.run(["git", "-C", repo, *args], capture_output=True, check=True, input=data).stdout


def _tree(repo, commit):
    """{blob sha: [paths]} for one commit (regular files only; submodules/symlinks skipped)."""
    blobs = {}
    for rec in _git(repo, "ls-tree", "-r", "-z", commit).split(b"\0"):
        if not rec:
            continue
        meta, path = rec.split(b"\t", 1)
        mode, kind, sha = meta.split()
        if kind == b"blob" and mode in (b"100644", b"100755"):
            blobs.setdefault(sha.decode(), []).append(path.decode("utf-8", "replace"))
    return blobs


def _read_blobs(repo, shas):
    """Yield (sha, bytes) via one `git cat-file --batch` process."""
    if not shas:
        return
    raw = _git(repo, "cat-file", "--batch", data="".join(s + "\n" for s in shas).encode())
    pos = 0
    while pos < len(raw):
        nl = raw.index(b"\n", pos)
        sha, _, size = raw[pos:nl].split()
        size = int(size)
        yield sha.decode(), raw[nl + 1:nl + 1 + size]
        pos = nl + 1 + size + 1


def history_findings(repo=".", terms=()):
    """Scan every blob of every commit reachable from any ref. One entry per (blob, path, rule, line)."""
    commits = _git(repo, "rev-list", "--all", "--reverse").decode().split()
    first = {}                     # (sha, path) -> first commit containing it
    for c in commits:
        for sha, paths in _tree(repo, c).items():
            for p in paths:
                first.setdefault((sha, p), c)
    head = set()
    if commits:
        try:
            head = set(_tree(repo, "HEAD"))
        except subprocess.CalledProcessError:
            pass
    wanted = sorted({sha for sha, p in first if not skipped(p)})
    texts = {}
    for sha, data in _read_blobs(repo, wanted):
        try:
            texts[sha] = data.decode("utf-8")
        except UnicodeDecodeError:
            continue               # binary, same as the working-tree scan
    order = {c: i for i, c in enumerate(commits)}
    found = []
    for (sha, path), c in sorted(first.items(), key=lambda kv: (order[kv[1]], kv[0][1])):
        if skipped(path) or sha not in texts:
            continue
        for line, rule in scan_text(path, texts[sha], terms):
            found.append({"commit": c, "path": path, "line": line, "rule": rule, "in_head": sha in head})
    found += metadata_findings(repo, terms)
    found.sort(key=lambda f: order[f["commit"]])          # stable: keeps path order within a commit
    return found


def metadata_findings(repo=".", terms=()):
    """Commit author/committer identities and messages are published with the history too."""
    raw = _git(repo, "log", "--all", "--format=%H%x00%an <%ae>%n%cn <%ce>%x00%B%x00%x01").decode("utf-8", "replace")
    found = []
    for rec in raw.split("\x00\x01"):
        rec = rec.lstrip("\n")
        if not rec:
            continue
        c, ident, msg = rec.split("\x00", 2)
        for path, text in (("(commit author/committer)", ident), ("(commit message)", msg)):
            seen = set()
            for line, rule in scan_text(path, text, terms):
                if rule not in seen:
                    seen.add(rule)
                    found.append({"commit": c, "path": path, "line": line, "rule": rule, "in_head": True})
    return found


def main_history(terms):
    found = history_findings(".", terms)
    for f in found:
        where = "" if f["in_head"] else "  [history-only]"
        print(f"LEAK {f['commit'][:12]} {f['path']}:{f['line']}: {f['rule']}{where}")
    commits = len({f["commit"] for f in found})
    print(f"leak-scan --history: {'FAIL' if found else 'clean'} ({len(found)} finding(s) in {commits} commit(s))")
    return 1 if found else 0


def main(argv):
    terms = load_terms(os.environ.get("NIYANTRAK_PRIVATE_TERMS"))
    args = argv[1:]
    if "--history" in args:
        return main_history(terms)
    bad = 0
    for f in files(args):
        if skipped(f):
            continue
        try:
            text = open(f, encoding="utf-8").read()
        except (UnicodeDecodeError, OSError):
            continue
        for line, name in scan_text(f, text, terms):
            print(f"LEAK {f}: private term" if name == "private term" else f"LEAK {f}:{line}: {name}")
            bad += 1
    print(f"leak-scan: {'FAIL' if bad else 'clean'} ({bad} finding(s))")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
