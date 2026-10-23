"""Unit tests for lab/policy.py: lab isolation, installer-seed policy, VM budget (no VMs needed)."""
import json
import pathlib
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "lab"))
import policy  # noqa: E402

NET = (ROOT / "lab" / "network.xml").read_text()


def test_shipped_network_is_isolated():
    assert policy.check_network_xml(NET) == []


def test_bridged_network_rejected():
    bad = NET.replace('<forward mode="nat"/>', '<forward mode="bridge"/>')
    assert any("joins the lab to a real network" in p for p in policy.check_network_xml(bad))


def test_physical_device_rejected():
    bad = NET.replace('<forward mode="nat"/>', '<forward mode="nat" dev="enp5s0"/>')
    assert any("physical device" in p for p in policy.check_network_xml(bad))


def test_home_subnet_rejected():
    bad = NET.replace("10.77.0.1", "192.168.0.1")
    assert any("not 10.77" in p for p in policy.check_network_xml(bad))


def rendered_seed():
    t = (ROOT / "lab" / "seed" / "user-data.tmpl").read_text()
    return t.replace("@HOSTNAME@", "nyklab-ctl").replace("@PUBKEY@", "ssh-ed25519 AAAAC3Nza test-key")


def test_template_passes_after_render():
    assert policy.check_seed(rendered_seed()) == []


def test_unrendered_template_fails():
    assert any("placeholder" in p for p in policy.check_seed((ROOT / "lab" / "seed" / "user-data.tmpl").read_text()))


def test_root_unlocked_fails():
    assert any("root must stay locked" in p for p in policy.check_seed(rendered_seed().replace("disable_root: true", "disable_root: false")))


def test_password_login_fails():
    assert any("allow-pw" in p for p in policy.check_seed(rendered_seed().replace("allow-pw: false", "allow-pw: true")))


def test_password_hash_fails():
    s = rendered_seed().replace('password: "!"', 'password: "$6$saltsalt$abcdefghijklmnop"')
    assert any("password hash" in p for p in policy.check_seed(s))


def test_private_key_fails():
    marker = "-----BEGIN " + "OPENSSH PRIVATE KEY-----"     # built at runtime so secret scanners stay quiet
    assert any("private key" in p for p in policy.check_seed(rendered_seed() + "\n# " + marker))


def test_existing_recovery_seed_would_fail_policy():
    """Niyantrak's recovery seeds set disable_root: false; the lab policy must catch that (finding 2026-10-22)."""
    s = rendered_seed().replace("disable_root: true", "disable_root: false")
    assert policy.check_seed(s)


def test_shipped_vms_budget_fits_ai_pc():
    """ai-pc 2026-10-22: ~34 GB RAM available, /var/lib/niyantrak-lab (ZFS) 306 GB free; root disk (94 GB) is too small."""
    doc = json.loads((ROOT / "lab" / "vms.json").read_text())
    assert policy.check_budget(doc, free_ram_gb=34, free_disk_gb=306) == []
    assert policy.check_budget(doc, free_disk_gb=94)


def test_budget_over_ram_fails():
    doc = json.loads((ROOT / "lab" / "vms.json").read_text())
    assert any("GB RAM" in p for p in policy.check_budget(doc, free_ram_gb=8))


def test_exactly_one_control_vm():
    doc = json.loads((ROOT / "lab" / "vms.json").read_text())
    doc["vms"] = [v for v in doc["vms"] if v["role"] != "control"]
    assert any("control VM" in p for p in policy.check_budget(doc))


def test_cli_exit_codes(tmp_path):
    good = tmp_path / "ud"
    good.write_text(rendered_seed())
    assert subprocess.run([sys.executable, ROOT / "lab" / "policy.py", "seed", good], capture_output=True).returncode == 0
    good.write_text(rendered_seed().replace("disable_root: true", "disable_root: false"))
    assert subprocess.run([sys.executable, ROOT / "lab" / "policy.py", "seed", good], capture_output=True).returncode == 1


def test_nopasswd_sudo_only_in_lab_seeds():
    lab = rendered_seed()
    assert "NOPASSWD:ALL" in lab and policy.check_seed(lab) == []
    real = lab.replace("# niyantrak-lab-only", "# real install")
    assert any("lab seeds" in p for p in policy.check_seed(real))


def test_cloud_seed_passes_after_render():
    t = (ROOT / "lab" / "seed" / "cloud-config.tmpl").read_text()
    t = t.replace("@HOSTNAME@", "nyklab-ctl").replace("@PUBKEY@", "ssh-ed25519 AAAAC3Nza test-key")
    assert policy.check_seed(t) == []
    assert any("root must stay locked" in p for p in policy.check_seed(t.replace("disable_root: true", "disable_root: false")))
