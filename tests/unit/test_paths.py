"""State folder: system path for root/writable, user folder otherwise, env override wins."""
import importlib
import os

import niyantrak.paths as P


def test_env_override(monkeypatch, tmp_path):
    monkeypatch.setenv("NIYANTRAK_STATE_ROOT", str(tmp_path / "x"))
    assert P.state_root() == str(tmp_path / "x")


def test_user_folder_when_system_path_not_writable(monkeypatch, tmp_path):
    monkeypatch.delenv("NIYANTRAK_STATE_ROOT", raising=False)
    monkeypatch.setattr(P, "SYSTEM_ROOT", str(tmp_path / "ro" / "niyantrak"))
    os.makedirs(tmp_path / "ro")
    os.chmod(tmp_path / "ro", 0o500)
    monkeypatch.setattr(P.os, "geteuid", lambda: 1000)
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    try:
        assert P.state_root() == str(tmp_path / "home" / ".local" / "share" / "niyantrak")
    finally:
        os.chmod(tmp_path / "ro", 0o700)


def test_system_folder_for_root(monkeypatch):
    monkeypatch.delenv("NIYANTRAK_STATE_ROOT", raising=False)
    monkeypatch.setattr(P.os, "geteuid", lambda: 0)
    assert P.state_root() == P.SYSTEM_ROOT


def test_modules_use_it(monkeypatch, tmp_path):
    monkeypatch.setenv("NIYANTRAK_STATE_ROOT", str(tmp_path))
    for m in ("niyantrak.join", "niyantrak.discovery", "niyantrak.panel"):
        importlib.reload(importlib.import_module(m))
    import niyantrak.join as J, niyantrak.discovery as D, niyantrak.panel as PN
    assert J.STORE.startswith(str(tmp_path)) and D.PEERS_FILE.startswith(str(tmp_path)) and PN.STATE_DIR.startswith(str(tmp_path))


def test_windows_uses_localappdata_without_geteuid(monkeypatch, tmp_path):
    """Windows has no os.geteuid; the panel imports state_root at start-up, so this must not raise."""
    monkeypatch.delenv("NIYANTRAK_STATE_ROOT", raising=False)
    monkeypatch.delattr(P.os, "geteuid", raising=False)
    monkeypatch.setattr(P.os, "name", "nt")
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "AppData" / "Local"))
    assert P.state_root() == os.path.join(str(tmp_path / "AppData" / "Local"), "Niyantrak")


def test_windows_without_localappdata_falls_back_to_home(monkeypatch, tmp_path):
    monkeypatch.delenv("NIYANTRAK_STATE_ROOT", raising=False)
    monkeypatch.delenv("LOCALAPPDATA", raising=False)
    monkeypatch.delattr(P.os, "geteuid", raising=False)
    monkeypatch.setattr(P.os, "name", "nt")
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setenv("USERPROFILE", str(tmp_path / "home"))
    assert P.state_root() == os.path.join(str(tmp_path / "home"), ".local", "share", "niyantrak")
