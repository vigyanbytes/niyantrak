"""Machine switch file (per-OS path, env override for tests) and the 5W event log (no command text, only a hash)."""
import hashlib
import json

import pytest

from niyantrak.gate import events, mode
from niyantrak.gate.engine import ToolCall, decide


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    mf = tmp_path / "gate-mode"
    monkeypatch.setenv("NIYANTRAK_GATE_MODE_FILE", str(mf))
    log = tmp_path / "log" / "events.jsonl"
    monkeypatch.setenv("NIYANTRAK_GATE_LOG", str(log))
    monkeypatch.delenv("NIYANTRAK_HOST_ROLE", raising=False)
    monkeypatch.setenv("NIYANTRAK_ROOT", str(tmp_path / "root"))     # no bootstrap report here
    return mf, log


def test_mode_file_path_per_os(monkeypatch):
    monkeypatch.delenv("NIYANTRAK_GATE_MODE_FILE", raising=False)
    assert mode.mode_file_path(os_name="posix", environ={}) == "/etc/niyantrak/gate-mode"
    assert mode.mode_file_path(os_name="nt", environ={"ProgramData": "D:\\PD"}) == "D:\\PD\\niyantrak\\gate-mode"
    assert mode.mode_file_path(os_name="nt", environ={}) == "C:\\ProgramData\\niyantrak\\gate-mode"
    assert mode.mode_file_path(os_name="posix", environ={"NIYANTRAK_GATE_MODE_FILE": "/t/m"}) == "/t/m"


@pytest.mark.parametrize("content,want", [
    (None, "enforce"), ("on\n", "enforce"), ("enforce", "enforce"), ("OFF\n", "off"),
    ("audit", "audit"), ("garbage", "enforce"), ("", "enforce"),
])
def test_mode_values_fail_closed(env, content, want):
    mf, _ = env
    if content is not None:
        mf.write_text(content)
    assert mode.current_mode() == want


def test_off_allows_everything(env):
    mf, _ = env
    mf.write_text("off")
    d = decide(ToolCall(tool="Bash", command="rm -rf /"))
    assert (d.outcome, d.rule_id) == ("allow", "gate.off")


def test_audit_logs_would_deny_but_allows(env):
    mf, _ = env
    mf.write_text("audit")
    d = decide(ToolCall(tool="Bash", command="git push --force"))
    assert d.outcome == "audit" and d.rule_id == "git.force_push" and not d.blocks


def test_enforce_blocks(env):
    d = decide(ToolCall(tool="Bash", command="git push --force"))
    assert d.outcome == "deny" and d.blocks


def test_event_is_5w_and_never_contains_the_command(env):
    _, log = env
    cmd = "cat .env && echo s3cr3t-token-value"
    call = ToolCall(tool="Bash", command=cmd)
    d = decide(call)
    events.record(call, d, agent="claude")
    events.record(ToolCall(tool="Bash", command="ls"), decide(ToolCall(tool="Bash", command="ls")), agent="codex")
    lines = log.read_text().splitlines()
    assert len(lines) == 2
    raw = log.read_text()
    assert "s3cr3t" not in raw and ".env" not in raw and "cat" not in raw
    ev = json.loads(lines[0])
    assert ev["who"]
    assert ev["agent"] == "claude"
    assert ev["what"] == {"class": "secret", "tool": "Bash"}
    assert ev["where"]["host_role"] == "unknown"
    assert ev["why"] == {"rule_id": "secret.path", "outcome": "deny", "mode": "enforce"}
    assert ev["command_sha256"] == hashlib.sha256(cmd.encode()).hexdigest()
    assert ev["when"].endswith("Z")
    assert json.loads(lines[1])["why"]["outcome"] == "allow"


def test_host_role_from_env(env, monkeypatch):
    _, log = env
    monkeypatch.setenv("NIYANTRAK_HOST_ROLE", "control")
    call = ToolCall(tool="Read", paths=("/repo/a.py",))
    events.record(call, decide(call), agent="gemini")
    ev = json.loads(log.read_text())
    assert ev["where"]["host_role"] == "control"
    assert ev["what"]["class"] == "file"
    assert "/repo" not in log.read_text()


def test_log_failure_never_raises(env, monkeypatch, tmp_path):
    blocker = tmp_path / "file"
    blocker.write_text("x")
    monkeypatch.setenv("NIYANTRAK_GATE_LOG", str(blocker / "sub" / "events.jsonl"))
    call = ToolCall(tool="Bash", command="ls")
    assert events.record(call, decide(call), agent="claude") is False
