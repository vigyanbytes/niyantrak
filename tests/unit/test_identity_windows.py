"""Windows: no pwd module and no os.getuid. The person comes from the Windows logon (whoami /user gives the SID)."""
import subprocess
import sys
import types
from pathlib import Path

from niyantrak import identity as I

ROOT = Path(__file__).resolve().parents[2]
SID = "S-1-5-21-1004336348-1177238915-682003330-1001"


def test_imports_without_pwd_and_getuid():
    # what Windows looks like to Python: importing decisions/telemetry/panel used to fail with "No module named 'pwd'"
    code = ("import os, sys; sys.modules['pwd'] = None; del os.getuid; del os.geteuid\n"
            "import niyantrak.identity, niyantrak.decisions, niyantrak.telemetry.schema, niyantrak.cli\n"
            "print('ok')")
    r = subprocess.run([sys.executable, "-c", code], cwd=ROOT, capture_output=True, text=True)
    assert r.returncode == 0 and r.stdout.strip() == "ok", r.stderr


def fake_whoami(out, code=0):
    def run(cmd, **kw):
        assert cmd[:2] == ["whoami", "/user"]
        return types.SimpleNamespace(stdout=out, returncode=code)
    return run


def test_windows_local_account_uses_the_sid():
    env = {"USERNAME": "asha", "USERDOMAIN": "LAPTOP-ASHA", "COMPUTERNAME": "LAPTOP-ASHA"}
    who = I.windows_current(env=env, run=fake_whoami(f'"laptop-asha\\asha","{SID}"\r\n'))
    assert who.name == "asha" and who.directory == "local" and who.stable_id == f"sid:{SID}" and who.uid == 1001
    assert I.valid_stable_id(who.stable_id)


def test_windows_directory_accounts():
    run = fake_whoami(f'"corp\\ravi","{SID}"')
    assert I.windows_current(env={"USERNAME": "ravi", "USERDOMAIN": "CORP", "COMPUTERNAME": "PC1"}, run=run).directory == "ad"
    assert I.windows_current(env={"USERNAME": "ravi", "USERDOMAIN": "AzureAD", "COMPUTERNAME": "PC1"}, run=run).directory == "entra"


def test_windows_without_whoami_has_no_stable_id():
    def broken(cmd, **kw):
        raise OSError("no whoami")
    who = I.windows_current(env={"USERNAME": "meera"}, run=broken)
    assert who.name == "meera" and who.stable_id is None and who.uid == -1
    assert I.windows_current(env={"USERNAME": "meera"}, run=fake_whoami("garbage")).stable_id is None


def test_current_uses_windows_logon_when_there_is_no_pwd(monkeypatch):
    monkeypatch.setattr(I, "pwd", None)
    monkeypatch.setattr(I, "windows_current", lambda env=None: I.Identity("tomas", 7, "local", f"sid:{SID}"))
    assert I.current().name == "tomas"
