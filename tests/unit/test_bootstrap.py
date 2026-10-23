"""niyantrak-bootstrap.sh in test mode (NIYANTRAK_ROOT=<tmp>): OS detection, guards, files written, idempotence, resume."""
import getpass
import os
import pathlib
import subprocess

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[2]
BOOT = ROOT / "bootstrap" / "niyantrak-bootstrap.sh"
HOME = pathlib.Path(os.path.expanduser("~"))


def os_release(tmp_path, id_="ubuntu", ver="24.04"):
    f = tmp_path / "os-release"
    f.write_text(f'ID={id_}\nVERSION_ID="{ver}"\n')
    return f


def run(tmp_path, *args, id_="ubuntu", ver="24.04", euid="0", arch="x86_64", peers="10.77.0.1", key=True, extra=None):
    root = tmp_path / "root"
    root.mkdir(exist_ok=True)
    keys = root / str(HOME).lstrip("/") / ".ssh" / "authorized_keys"
    if key:
        keys.parent.mkdir(parents=True, exist_ok=True)
        keys.write_text("ssh-ed25519 AAAAC3Nza test\n")
    uuid = tmp_path / "uuid"
    uuid.write_text("4C4C4544-0000-1111-2222-333344445555\n")
    env = dict(os.environ, NIYANTRAK_ROOT=str(root), NIYANTRAK_OS_RELEASE=str(os_release(tmp_path, id_, ver)),
               NIYANTRAK_FAKE_EUID=euid, NIYANTRAK_FAKE_ARCH=arch, NIYANTRAK_FAKE_SSH_PEERS=peers, SUDO_USER=getpass.getuser(),
               NIYANTRAK_PRODUCT_UUID_FILE=str(uuid))
    env.update(extra or {})
    r = subprocess.run(["bash", str(BOOT), *args], capture_output=True, text=True, env=env)
    return r, root


def test_full_run_writes_expected_files(tmp_path):
    r, root = run(tmp_path)
    assert r.returncode == 0, r.stdout + r.stderr
    sshd = (root / "etc/ssh/sshd_config.d/10-niyantrak.conf").read_text()
    assert "PermitRootLogin no" in sshd and "PasswordAuthentication no" in sshd
    rules = (root / "etc/audit/rules.d/50-niyantrak.rules").read_text()
    for k in ("nyk-identity", "nyk-sudo-exec", "nyk-ssh", "nyk-units", "nyk-firewall", "nyk-secrets", "nyk-gate"):
        assert f"-k {k}" in rules
    assert (root / "etc/niyantrak/node-id").read_text().startswith("nyk-")
    assert oct((root / "etc/niyantrak/secret.d").stat().st_mode)[-3:] == "700"
    assert (root / "etc/update-motd.d/10-niyantrak").stat().st_mode & 0o111
    assert '"role": "control"' in (root / "var/lib/niyantrak/bootstrap/report.json").read_text()


def test_node_id_is_stable_and_case_insensitive(tmp_path):
    _, root = run(tmp_path)
    a = (root / "etc/niyantrak/node-id").read_text()
    (tmp_path / "uuid").write_text("4c4c4544-0000-1111-2222-333344445555\n")
    (root / "var/lib/niyantrak/bootstrap/state").unlink()
    _, root = run(tmp_path)
    assert (root / "etc/niyantrak/node-id").read_text() == a


def test_setup_code_only_hash_stored(tmp_path):
    r, root = run(tmp_path)
    shown = [line for line in r.stdout.splitlines() if "vPanel setup code:" in line][0].split(":")[1].split()[0]
    stored = (root / "var/lib/niyantrak/bootstrap/setup-code.sha256").read_text().strip()
    assert shown not in stored and len(stored) == 64
    assert oct((root / "var/lib/niyantrak/bootstrap/setup-code.sha256").stat().st_mode)[-3:] == "600"


def test_rerun_is_idempotent(tmp_path):
    run(tmp_path)
    r, _ = run(tmp_path)
    assert r.returncode == 0
    assert r.stdout.count("already done") == 9           # every step except preflight


def test_resume_after_failure(tmp_path):
    r, root = run(tmp_path, key=False)                    # stops at the ssh guard
    assert r.returncode == 3
    state = (root / "var/lib/niyantrak/bootstrap/state").read_text().split()
    assert state == ["packages", "scaffold", "auditd"]
    r, _ = run(tmp_path)                                  # key added -> resumes at ssh
    assert r.returncode == 0
    assert "step 5 ssh" in r.stdout and "step 2 packages: already done" in r.stdout


@pytest.mark.parametrize("id_,ver,arch,msg", [
    ("debian", "12", "x86_64", "unsupported OS 'debian'"),
    ("fedora", "40", "x86_64", "unsupported OS 'fedora'"),
    ("ubuntu", "22.04", "x86_64", "not a supported LTS"),
    ("ubuntu", "24.04", "riscv64", "architecture riscv64"),
])
def test_os_detection_refuses(tmp_path, id_, ver, arch, msg):
    r, _ = run(tmp_path, id_=id_, ver=ver, arch=arch)
    assert r.returncode == 2 and msg in r.stdout


def test_ubuntu_2604_accepted(tmp_path):
    r, _ = run(tmp_path, ver="26.04", extra={"NIYANTRAK_FAKE_SSH_PEERS": ""})
    assert r.returncode == 0


def test_not_root_refused(tmp_path):
    r, _ = run(tmp_path, euid="1000")
    assert r.returncode == 2 and "run with sudo" in r.stdout


def test_root_login_without_sudo_refused(tmp_path):
    r, _ = run(tmp_path, extra={"SUDO_USER": ""})
    assert r.returncode == 2 and "admin account" in r.stdout


def test_ssh_guard_without_key(tmp_path):
    r, root = run(tmp_path, key=False)
    assert r.returncode == 3 and "lock you out" in r.stdout
    assert not (root / "etc/ssh/sshd_config.d/10-niyantrak.conf").exists()


def test_firewall_guard_public_ssh_session(tmp_path):
    r, _ = run(tmp_path, peers="203.0.113.7")
    assert r.returncode == 3 and "203.0.113.7" in r.stdout


def test_firewall_allows_tailnet_session(tmp_path):
    r, _ = run(tmp_path, peers="100.101.102.103,192.168.0.20")
    assert r.returncode == 0


def test_dry_run_writes_nothing(tmp_path):
    r, root = run(tmp_path, "--dry-run")
    assert r.returncode == 0, r.stdout
    written = [p for p in root.rglob("*") if p.is_file() and "authorized_keys" not in p.name]
    assert written == []
    assert "would write: /etc/ssh/sshd_config.d/10-niyantrak.conf" in r.stdout


def test_node_role_has_no_setup_code(tmp_path):
    r, root = run(tmp_path, "--role", "node")
    assert r.returncode == 0
    assert not (root / "var/lib/niyantrak/bootstrap/setup-code.sha256").exists()


def test_bad_option(tmp_path):
    r, _ = run(tmp_path, "--bogus")
    assert r.returncode == 2
