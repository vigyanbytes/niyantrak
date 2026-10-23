"""Hook adapters: each CLI's PreToolUse-style payload in, that CLI's allow/deny format out."""
import json

import pytest

from niyantrak.gate import adapters


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setenv("NIYANTRAK_GATE_MODE_FILE", str(tmp_path / "gate-mode"))
    monkeypatch.setenv("NIYANTRAK_GATE_LOG", str(tmp_path / "events.jsonl"))


def run(cli, payload):
    return adapters.handle(cli, json.dumps(payload) if not isinstance(payload, str) else payload)


def claude_payload(tool, inp):
    return {"session_id": "s1", "transcript_path": "/tmp/t.jsonl", "cwd": "/repo", "permission_mode": "default",
            "hook_event_name": "PreToolUse", "tool_name": tool, "tool_input": inp}


def test_claude_deny_uses_permission_decision():
    out, err, code = run("claude", claude_payload("Bash", {"command": "git push --force", "description": "x"}))
    assert code == 0
    hso = json.loads(out)["hookSpecificOutput"]
    assert hso["hookEventName"] == "PreToolUse"
    assert hso["permissionDecision"] == "deny"
    assert "git.force_push" in hso["permissionDecisionReason"]


def test_claude_allow_defers_to_normal_permissions():
    # an explicit "allow" would skip the user's own permission prompts; the gate only ever narrows
    out, err, code = run("claude", claude_payload("Bash", {"command": 'git commit -m "rm -rf /"'}))
    assert (out, code) == ("", 0)


def test_claude_file_tool():
    out, _, _ = run("claude", claude_payload("Read", {"file_path": "/home/u/.aws/credentials"}))
    assert json.loads(out)["hookSpecificOutput"]["permissionDecision"] == "deny"


def test_codex_deny_is_exit_2_with_reason_on_stderr():
    payload = {"session_id": "s", "hook_event_name": "PreToolUse", "tool_name": "Bash",
               "tool_input": {"command": ["bash", "-lc", "rm -rf /etc"]}}
    out, err, code = run("codex", payload)
    assert code == 2 and "fs.rm_protected" in err and out == ""
    out, err, code = run("codex", {**payload, "tool_input": {"command": ["bash", "-lc", "echo 'rm -rf /etc'"]}})
    assert (out, err, code) == ("", "", 0)


def test_gemini_cli_before_tool():
    payload = {"session_id": "s", "hook_event_name": "BeforeTool", "tool_name": "run_shell_command",
               "tool_input": {"command": "sudo systemctl stop nginx", "description": "stop"}}
    out, _, code = run("gemini", payload)
    assert code == 0 and json.loads(out)["decision"] == "deny"
    assert "prod.service" in json.loads(out)["reason"]
    out, _, _ = run("gemini", {**payload, "tool_input": {"command": "systemctl status nginx"}})
    assert json.loads(out) == {"decision": "allow"}


def test_antigravity_tool_call_shape():
    out, _, code = run("antigravity", {"toolCall": {"name": "run_command", "args": {"CommandLine": "git reset --hard"}}})
    assert code == 0 and json.loads(out)["decision"] == "deny"
    out, _, _ = run("gemini", {"toolCall": {"name": "view_file", "args": {"AbsolutePath": "/repo/README.md"}}})
    assert json.loads(out)["decision"] == "allow"


def test_opencode_shape():
    out, _, code = run("opencode", {"tool": "bash", "args": {"command": "kubectl delete ns prod"}})
    assert code == 0 and json.loads(out)["decision"] == "deny"
    out, _, _ = run("opencode", {"tool": "read", "args": {"filePath": "/repo/.env"}})
    assert json.loads(out)["decision"] == "deny"
    out, _, _ = run("opencode", {"tool": "write", "args": {"filePath": "/repo/a.md", "content": "rm -rf /"}})
    assert json.loads(out)["decision"] == "allow"


@pytest.mark.parametrize("cli", adapters.CLIS)
def test_malformed_payload_fails_closed(cli):
    out, err, code = run(cli, "{not json")
    blocked = code == 2 or '"deny"' in out
    assert blocked, (cli, out, err, code)


@pytest.mark.parametrize("cli", adapters.CLIS)
def test_every_decision_is_logged(cli, tmp_path):
    run(cli, {"tool_name": "Bash", "tool_input": {"command": "ls"}, "tool": "bash", "args": {"command": "ls"}})
    ev = json.loads((tmp_path / "events.jsonl").read_text().splitlines()[-1])
    assert ev["agent"] == cli


def test_unknown_cli_rejected():
    with pytest.raises(ValueError):
        adapters.handle("vim", "{}")
