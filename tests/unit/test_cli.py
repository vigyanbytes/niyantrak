"""niyantrak CLI: scan masks valid identifiers only and never prints values; node reads a bootstrap report."""
import json
import os
import pathlib
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parents[2]


def run(*args, env=None):
    return subprocess.run([sys.executable, "-m", "niyantrak.cli", *args], capture_output=True, text=True,
                          cwd=ROOT, env={**os.environ, **(env or {})})


def test_scan_masks_and_hides_values():
    r = run("scan", "Aadhaar 2345 6789 0124, PAN ABCPE1234F, pay ramesh@okhdfc")
    assert r.returncode == 0
    assert "<AADHAAR_1>" in r.stdout and "<PAN_1>" in r.stdout and "<UPI_ID_1>" in r.stdout
    for raw in ("2345 6789 0124", "ABCPE1234F", "ramesh@okhdfc"):
        assert raw not in r.stdout


def test_scan_ignores_invalid_checksum():
    r = run("scan", "order 2345 6789 0123")
    assert "No personal identifiers" in r.stdout


def test_scan_json():
    out = json.loads(run("scan", "--json", "card 4111 1111 1111 1111").stdout)
    assert out["counts"] == {"CARD": 1}


def test_node_after_bootstrap(tmp_path):
    root = tmp_path
    (root / "var/lib/niyantrak/bootstrap").mkdir(parents=True)
    (root / "var/lib/niyantrak/bootstrap/report.json").write_text(json.dumps(
        {"version": "0.1.0", "role": "control", "node_id": "nyk-abc", "admin": "ops", "finished": "now"}))
    r = run("node", env={"NIYANTRAK_ROOT": str(root)})
    assert "nyk-abc" in r.stdout and r.returncode == 1          # checks fail: nothing else was set up
    r2 = run("node", env={"NIYANTRAK_ROOT": str(tmp_path / "none")})
    assert "not been bootstrapped" in r2.stdout
