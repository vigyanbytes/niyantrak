"""Who is acting: derived from the operating system, never typed in.

The login user comes from the kernel's login record (survives sudo), the name from NSS (so local accounts, SSSD/AD,
authd/Entra and Kanidm all resolve the same way), and a stable id from the directory that answered.
All fixtures are synthetic files in tmp_path; no real accounts are read.
"""
import pytest

from niyantrak import identity as I

UNSET = "4294967295"


def files(tmp_path, loginuid=None, passwd="root:x:0:0::/root:/bin/bash\nasha:x:1000:1000::/home/asha:/bin/bash\n",
          nsswitch="passwd:         files systemd\n", machine_id="0123456789abcdef0123456789abcdef\n"):
    p = {}
    for name, body in (("loginuid", loginuid), ("passwd", passwd), ("nsswitch.conf", nsswitch),
                       ("machine-id", machine_id)):
        if body is not None:
            (tmp_path / name).write_text(body)
        p[name] = str(tmp_path / name)
    return dict(proc_loginuid=p["loginuid"], passwd_path=p["passwd"], nsswitch_path=p["nsswitch.conf"],
                machine_id_path=p["machine-id"])


class FakePw:
    def __init__(self, name, uid):
        self.pw_name, self.pw_uid = name, uid


def names(mapping):
    def getpwuid(uid):
        if uid not in mapping:
            raise KeyError(uid)
        return FakePw(mapping[uid], uid)
    return getpwuid


# --- who is logged in -------------------------------------------------------------------------------------------

def test_login_uid_comes_from_the_kernel_login_record(tmp_path):
    f = files(tmp_path, loginuid="1000")
    assert I.login_uid(f["proc_loginuid"], env={}, getuid=lambda: 0) == 1000      # sudo -> euid 0, still asha


def test_unset_login_record_falls_back_to_sudo_then_process_uid(tmp_path):
    f = files(tmp_path, loginuid=UNSET)
    assert I.login_uid(f["proc_loginuid"], env={"SUDO_UID": "1001"}, getuid=lambda: 0) == 1001
    assert I.login_uid(f["proc_loginuid"], env={}, getuid=lambda: 1002) == 1002
    assert I.login_uid(str(tmp_path / "missing"), env={}, getuid=lambda: 1003) == 1003


# --- which directory answered -------------------------------------------------------------------------------------

def test_account_in_passwd_file_is_local(tmp_path):
    f = files(tmp_path, nsswitch="passwd: files sss\n")
    assert I.directory_for("asha", f["passwd_path"], f["nsswitch_path"]) == "local"


@pytest.mark.parametrize("line,expected", [
    ("passwd:         files systemd sss", "sssd"),
    ("passwd: files authd systemd", "authd"),
    ("passwd: compat kanidm", "kanidm"),
    ("passwd: files ldap", "ldap"),
    ("passwd: files winbind", "winbind"),
])
def test_directory_account_named_after_the_nss_module(tmp_path, line, expected):
    f = files(tmp_path, nsswitch=line + "\n")
    assert I.directory_for("ravi", f["passwd_path"], f["nsswitch_path"]) == expected


def test_unknown_when_no_directory_module(tmp_path):
    f = files(tmp_path, nsswitch="passwd: files systemd\n")
    assert I.directory_for("ravi", f["passwd_path"], f["nsswitch_path"]) == "unknown"


# --- stable id ----------------------------------------------------------------------------------------------------

def test_local_id_is_scoped_to_this_machine(tmp_path):
    f = files(tmp_path)
    who = I.current(getpwuid=names({1000: "asha"}), env={}, getuid=lambda: 1000, **files(tmp_path, loginuid="1000"))
    assert who.name == "asha" and who.directory == "local"
    assert who.stable_id == "local:uid:1000@0123456789ab"
    assert f["passwd_path"]


def test_sssd_prefers_the_directory_sid(tmp_path):
    f = files(tmp_path, loginuid="1500000001", nsswitch="passwd: files sss\n")
    who = I.current(getpwuid=names({1500000001: "ravi"}), env={}, getuid=lambda: 0,
                    sid_lookup=lambda name: "S-1-5-21-3623811015-3361044348-30300820-1013", **f)
    assert who.directory == "sssd" and who.stable_id == "sid:S-1-5-21-3623811015-3361044348-30300820-1013"


def test_directory_without_sid_uses_directory_uid(tmp_path):
    f = files(tmp_path, loginuid="70001", nsswitch="passwd: files kanidm\n")
    who = I.current(getpwuid=names({70001: "meera"}), env={}, getuid=lambda: 0, sid_lookup=lambda n: None, **f)
    assert who.directory == "kanidm" and who.stable_id == "kanidm:uid:70001"


def test_unresolvable_uid_still_identifies_without_a_name(tmp_path):
    f = files(tmp_path, loginuid="4242")
    who = I.current(getpwuid=names({}), env={}, getuid=lambda: 0, **f)
    assert who.name == "uid-4242" and who.stable_id.startswith("unknown:uid:4242")


# --- agents act on someone's behalf -------------------------------------------------------------------------------

def test_agent_from_explicit_setting_or_known_cli():
    assert I.agent({"NIYANTRAK_AGENT": "codex"}) == "codex"
    assert I.agent({"CLAUDECODE": "1"}) == "claude"
    assert I.agent({"NIYANTRAK_AGENT": "gemini", "CLAUDECODE": "1"}) == "gemini"
    assert I.agent({}) is None


def test_stable_id_format_check():
    for good in ("local:uid:1000@0123456789ab", "sid:S-1-5-21-3623811015-3361044348-30300820-1013",
                 "kanidm:uid:70001", "authd:uid:1919217643", "unknown:uid:4242@0123456789ab"):
        assert I.valid_stable_id(good), good
    for bad in ("+919999999999", "asha@example.com", "sid:not-a-sid", "local:uid:abc", "", "x" * 300):
        assert not I.valid_stable_id(bad), bad
