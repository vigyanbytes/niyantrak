"""Lab acceptance tests for governed installation (plan §4g S-1..S-11; test plan I-1..I-10, D2, M1).

Phase 1 (works now, stock ISO): isolation, root locked, no passwords, Secure Boot, TPM, clock.
Later phases are xfail until the part is built and named in NIYANTRAK_LAB_NEEDS
(bootstrap, panel, join-endpoint, pxe-service, windows-join).
"""
import subprocess

import pytest

from conftest import STATE, needs, virsh, VM


# ── Phase 1: the lab itself + stock install ──────────────────────────────────────────────────────────────
def test_L0_lab_network_is_nat_bridge_only():
    xml = virsh("net-dumpxml", "nyklab").stdout
    assert "<forward mode='nat'" in xml or '<forward mode="nat"' in xml
    assert "virbr-nyklab" in xml


def test_D2_root_ssh_refused(ctl):
    r = ctl.ssh("true", user="root")
    assert r.returncode != 0


def test_D2_password_auth_off(ctl):
    r = ctl.ssh("sudo -n sshd -T | grep -E '^(passwordauthentication|permitrootlogin|kbdinteractiveauthentication) '")
    cfg = dict(line.split(None, 1) for line in r.stdout.strip().splitlines())
    assert cfg.get("passwordauthentication") == "no"
    assert cfg.get("permitrootlogin") == "no"
    assert cfg.get("kbdinteractiveauthentication") == "no"


def test_D2_root_password_locked(ctl):
    r = ctl.ssh("sudo -n passwd -S root")
    assert r.stdout.split()[1] == "L", r.stdout


def test_admin_has_no_password(ctl):
    r = ctl.ssh("sudo -n passwd -S labadmin")
    assert r.stdout.split()[1] in ("L", "NP"), r.stdout


def test_secure_boot_enabled(ctl):
    r = ctl.ssh("mokutil --sb-state 2>&1 || cat /sys/firmware/efi/efivars/SecureBoot-* 2>/dev/null | od -An -tu1")
    assert "SecureBoot enabled" in r.stdout, r.stdout


def test_tpm_present(ctl):
    assert ctl.ssh("test -e /dev/tpmrm0").returncode == 0


def test_I8_clock_synced(ctl):
    r = ctl.ssh("timedatectl show -p NTPSynchronized --value")
    assert r.stdout.strip() == "yes"


# ── Phase 2: first-node bootstrap (run `lab/lab.sh serve` on the lab host first) ─────────────────────────
ONE_LINER = ("curl -fsSLo /tmp/niyantrak-bootstrap.sh http://10.77.0.1:8088/bootstrap/niyantrak-bootstrap.sh && "
             "echo \"{sha}  /tmp/niyantrak-bootstrap.sh\" | sha256sum -c && sudo bash /tmp/niyantrak-bootstrap.sh")


def bootstrap_sha():
    import hashlib, pathlib
    return hashlib.sha256((pathlib.Path(__file__).parents[2] / "bootstrap" / "niyantrak-bootstrap.sh").read_bytes()).hexdigest()


@pytest.fixture(scope="module")
def booted(ctl):
    r = ctl.ssh(ONE_LINER.format(sha=bootstrap_sha()), timeout=1200)
    assert r.returncode == 0, r.stdout[-3000:] + r.stderr[-2000:]
    return r


@needs("bootstrap")
def test_I1_tampered_bootstrap_refused(ctl):
    r = ctl.ssh(ONE_LINER.format(sha="0" * 64))
    assert r.returncode != 0 and "FAILED" in (r.stdout + r.stderr)


@needs("bootstrap")
def test_bootstrap_one_liner_succeeds(booted):
    assert "bootstrap finished" in booted.stdout


@needs("bootstrap")
def test_setup_code_shown_once(booted):
    assert "vPanel setup code:" in booted.stdout


@needs("bootstrap")
def test_auditd_rules_present(ctl, booted):
    n = ctl.ssh("sudo -n auditctl -l | grep -c -- '-k nyk-'").stdout.strip()
    assert n.isdigit() and int(n) >= 15


@needs("bootstrap")
def test_firewall_active_and_scoped(ctl, booted):
    out = ctl.ssh("sudo -n ufw status").stdout
    assert "Status: active" in out
    assert "Anywhere" not in out.replace("Anywhere on", ""), out   # nothing open to the whole internet


@needs("bootstrap")
def test_root_locked_after_bootstrap(ctl, booted):
    assert ctl.ssh("sudo -n passwd -S root").stdout.split()[1] == "L"
    assert ctl.ssh("true", user="root").returncode != 0


@needs("bootstrap")
def test_secret_folder_private(ctl, booted):
    assert ctl.ssh("sudo -n stat -c %a /etc/niyantrak/secret.d").stdout.strip() == "700"


@needs("bootstrap")
def test_motd_shows_status(ctl, booted):
    out = ctl.ssh("run-parts /etc/update-motd.d 2>/dev/null | grep -A3 'governed node'").stdout
    assert "bootstrap: done" in out


@needs("bootstrap")
def test_rerun_changes_nothing(ctl, booted):
    r = ctl.ssh("sudo bash /tmp/niyantrak-bootstrap.sh", timeout=600)
    assert r.returncode == 0 and r.stdout.count("already done") == 9


@needs("bootstrap")
def test_I9_power_cut_mid_bootstrap_resumes(ctl):
    pytest.fail("procedure: revert ctl to snapshot 'clean', start the one-liner, `lab/lab.sh powercut ctl --apply` "
                "during step 2, `virsh start`, re-run; expect resume at the unfinished step, same end state")


@needs("bootstrap", "panel")
def test_I3_claim_needs_console_code(ctl):
    pytest.fail("procedure: POST /setup/claim without code -> 403; with expired code (>30 min) -> 403; console code -> 200 once")


# ── Phase 3: join ───────────────────────────────────────────────────────────────────────────────────────
@needs("join-endpoint")
def test_I2_fake_control_node_refused():
    rogue = VM("rogue")
    pytest.fail("procedure: rogue serves /join with its own cert; node2 one-liner pinned to ctl -> refuses, nothing installed")


@needs("join-endpoint")
def test_I5_token_not_leaked_and_single_use():
    pytest.fail("procedure: join node2; grep token in ~/.bash_history, /proc/*/cmdline snapshot, journal -> absent; reuse -> refused")


@needs("join-endpoint")
def test_I10_os_detection():
    pytest.fail("procedure: GET /join with curl UA -> join.sh; PowerShell UA -> join.ps1; script on Debian -> refuses with reason")


@needs("join-endpoint")
def test_join_installs_keys_and_records_host_key(ctl):
    pytest.fail("procedure: after node2 joins, ctl ssh as nyk-provision works without host-key prompt; card green in vPanel")


# ── Phase 4: network boot ───────────────────────────────────────────────────────────────────────────────
@needs("pxe-service")
def test_I4_unknown_pxe_client_gets_no_token():
    pytest.fail("procedure: node1 (MAC not registered) network-boots -> installs, appears 'waiting for approval', no token on disk")


@needs("pxe-service")
def test_pxe_registered_mac_auto_approved():
    pytest.fail("procedure: register node1 MAC in vPanel, network-boot -> joins and card turns green without a click")


# ── Phase 5: Windows ────────────────────────────────────────────────────────────────────────────────────
@needs("join-endpoint", "windows-join")
def test_M1_windows_join_hardened():
    pytest.fail("procedure: win11 runs the PowerShell one-liner -> OpenSSH on, PasswordAuthentication no, "
                "administrators_authorized_keys ACL SYSTEM+Administrators only, firewall rule only from ctl, IPv4 preferred")


# ── Phase 6: rebuild ────────────────────────────────────────────────────────────────────────────────────
@needs("bootstrap", "join-endpoint")
def test_I1_rebuild_three_times_identical():
    pytest.fail("procedure: destroy + up 3x; compare desired-state fingerprints and node cards; zero hand edits")
