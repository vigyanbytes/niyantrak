"""Lab test fixtures: run only with NIYANTRAK_LAB=1 on the lab host; SSH into lab VMs with the lab-only key."""
import os
import pathlib
import subprocess

import pytest

_DEFAULT = (pathlib.Path("/var/lib/niyantrak-lab") if pathlib.Path("/var/lib/niyantrak-lab").is_dir()
            else pathlib.Path.home() / ".local/share/niyantrak-lab")
STATE = pathlib.Path(os.environ.get("NIYANTRAK_LAB_STATE", _DEFAULT))
KEY = STATE / "keys" / "lab_admin_ed25519"
PREFIX = "nyklab-"
BUILT = set(filter(None, os.environ.get("NIYANTRAK_LAB_NEEDS", "").split(",")))


def pytest_collection_modifyitems(config, items):
    if os.environ.get("NIYANTRAK_LAB") != "1":
        skip = pytest.mark.skip(reason="lab tests need NIYANTRAK_LAB=1 on the lab host")
        here = pathlib.Path(__file__).parent
        for it in items:
            if here in pathlib.Path(str(it.fspath)).parents:   # this hook sees every item; touch only lab tests
                it.add_marker(skip)


def needs(*parts):
    """xfail (strict) until every named part is built and listed in NIYANTRAK_LAB_NEEDS."""
    missing = [p for p in parts if p not in BUILT]
    return pytest.mark.xfail(bool(missing), reason=f"not built yet: {', '.join(missing)}", strict=False, run=not missing)


def virsh(*args):
    return subprocess.run(["virsh", "-c", "qemu:///system", *args], capture_output=True, text=True)


def vm_ip(vm):
    out = virsh("domifaddr", PREFIX + vm).stdout
    for line in out.splitlines():
        if "ipv4" in line:
            return line.split()[-1].split("/")[0]
    return None


class VM:
    def __init__(self, name):
        self.name = name
        self.ip = vm_ip(name)

    def ssh(self, cmd, user="labadmin", timeout=60):
        return subprocess.run(["ssh", "-i", str(KEY), "-o", "BatchMode=yes", "-o", "ConnectTimeout=10",
                               "-o", "StrictHostKeyChecking=accept-new",
                               "-o", f"UserKnownHostsFile={STATE / 'known_hosts'}", f"{user}@{self.ip}", cmd],
                              capture_output=True, text=True, timeout=timeout)


@pytest.fixture(scope="session")
def ctl():
    vm = VM("ctl")
    if not vm.ip:
        pytest.fail("nyklab-ctl has no address: run `lab/lab.sh up --apply` and wait for the install to finish")
    return vm
