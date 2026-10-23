"""lab.sh safety: dry run by default, only nyklab-* objects, shellcheck-clean when shellcheck is present."""
import pathlib
import re
import shutil
import subprocess

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[2]
LAB = ROOT / "lab" / "lab.sh"
SCRIPTS = [LAB, ROOT / "lab" / "seed" / "render-seed.sh", ROOT / "bootstrap" / "verify-and-run.sh"]


def test_scripts_parse():
    for s in SCRIPTS:
        r = subprocess.run(["bash", "-n", str(s)], capture_output=True, text=True)
        assert r.returncode == 0, f"{s.name}: {r.stderr}"


@pytest.mark.skipif(not shutil.which("shellcheck"), reason="shellcheck not installed")
def test_shellcheck():
    r = subprocess.run(["shellcheck", "-S", "warning", *map(str, SCRIPTS)], capture_output=True, text=True)
    assert r.returncode == 0, r.stdout


def test_changing_virsh_calls_go_through_run():
    """Every virsh/virt-install call that changes something must be wrapped in run() (dry-run guard)."""
    changing = re.compile(r"\b(virsh\s+(net-define|net-start|net-autostart|net-destroy|net-undefine|destroy|undefine|"
                          r"shutdown|snapshot-create-as|snapshot-revert)|virt-install\s+--)")
    for n, line in enumerate(LAB.read_text().splitlines(), 1):
        code = line.split("#", 1)[0]
        if changing.search(code):
            assert re.search(r"\brun\s+(virsh|virt-install)", code), f"lab.sh:{n} changes state without run(): {line.strip()}"


def test_destroy_limited_to_lab_prefix():
    text = LAB.read_text()
    assert 'grep "^$PREFIX"' in text, "lab_doms must filter by the nyklab- prefix"


def test_help_runs_without_libvirt():
    r = subprocess.run(["bash", str(LAB), "help"], capture_output=True, text=True)
    assert r.returncode == 0 and "check" in r.stdout
