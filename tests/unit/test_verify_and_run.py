"""S-1 / I-1 (unit level): verify-and-run.sh runs a script only when its sha256 matches."""
import hashlib
import os
import pathlib
import subprocess

ROOT = pathlib.Path(__file__).resolve().parents[2]
VERIFY = ROOT / "bootstrap" / "verify-and-run.sh"


def run(url, sha, *args, allow_file=True):
    env = dict(os.environ, NIYANTRAK_VERIFY_ALLOW_FILE="1" if allow_file else "0")
    return subprocess.run(["bash", str(VERIFY), url, sha, *args], capture_output=True, text=True, env=env)


def make_script(tmp_path):
    marker = tmp_path / "ran"
    s = tmp_path / "boot.sh"
    s.write_text(f'echo "args:$*"; touch "{marker}"\n')
    return s, marker, hashlib.sha256(s.read_bytes()).hexdigest()


def test_good_hash_runs_with_args(tmp_path):
    s, marker, sha = make_script(tmp_path)
    r = run(f"file://{s}", sha, "--node", "ctl")
    assert r.returncode == 0, r.stderr
    assert "args:--node ctl" in r.stdout
    assert marker.exists()


def test_uppercase_hash_accepted(tmp_path):
    s, marker, sha = make_script(tmp_path)
    assert run(f"file://{s}", sha.upper()).returncode == 0


def test_tampered_script_refused_and_not_run(tmp_path):
    s, marker, sha = make_script(tmp_path)
    s.write_text(s.read_text() + "echo injected\n")
    r = run(f"file://{s}", sha)
    assert r.returncode == 3
    assert "mismatch" in r.stderr
    assert not marker.exists()


def test_malformed_hash_refused(tmp_path):
    s, marker, _ = make_script(tmp_path)
    assert run(f"file://{s}", "abc123").returncode == 2
    assert not marker.exists()


def test_http_refused(tmp_path):
    assert run("http://example.invalid/boot.sh", "0" * 64).returncode == 2


def test_file_url_refused_outside_tests(tmp_path):
    s, marker, sha = make_script(tmp_path)
    assert run(f"file://{s}", sha, allow_file=False).returncode == 2
    assert not marker.exists()


def test_missing_file_is_download_failure(tmp_path):
    assert run(f"file://{tmp_path}/nope.sh", "0" * 64).returncode == 4
