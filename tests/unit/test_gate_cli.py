"""`niyantrak gate check | install | uninstall | status` end to end, always against temp HOME dirs."""
import json
import os
import pathlib
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parents[2]


def run(tmp_path, *args, stdin=None, mode=None):
    mf = tmp_path / "gate-mode"
    if mode is not None:
        mf.write_text(mode)
    env = {**os.environ, "HOME": str(tmp_path / "home"), "NIYANTRAK_GATE_MODE_FILE": str(mf),
           "NIYANTRAK_GATE_LOG": str(tmp_path / "events.jsonl"), "NIYANTRAK_STATE_ROOT": str(tmp_path / "state")}
    return subprocess.run([sys.executable, "-m", "niyantrak.cli", "gate", *args], input=stdin, capture_output=True,
                          text=True, cwd=ROOT, env=env)


def claude(cmd):
    return json.dumps({"hook_event_name": "PreToolUse", "tool_name": "Bash", "tool_input": {"command": cmd}})


def test_check_claude_deny_and_allow(tmp_path):
    r = run(tmp_path, "check", "--cli", "claude", stdin=claude("sudo rm -rf /var/lib/mysql"))
    assert r.returncode == 0
    assert json.loads(r.stdout)["hookSpecificOutput"]["permissionDecision"] == "deny"
    r = run(tmp_path, "check", "--cli", "claude", stdin=claude("cat <<'EOF' > n.md\nrm -rf /\nEOF"))
    assert (r.returncode, r.stdout) == (0, "")
    lines = (tmp_path / "events.jsonl").read_text().splitlines()
    assert [json.loads(x)["why"]["outcome"] for x in lines] == ["deny", "allow"]


def test_check_respects_machine_switch(tmp_path):
    r = run(tmp_path, "check", "--cli", "claude", stdin=claude("git push --force"), mode="off")
    assert r.stdout == ""


def test_install_status_uninstall(tmp_path):
    home = tmp_path / "target"
    home.mkdir()
    r = run(tmp_path, "install", "--cli", "all", "--home", str(home))
    assert r.returncode == 0, r.stderr
    assert (home / ".claude/settings.json").exists()
    r = run(tmp_path, "status", "--home", str(home), "--json")
    st = json.loads(r.stdout)
    assert st["mode"] == "enforce" and all(st["installed"].values())
    assert st["mode_file"].endswith("gate-mode") and st["log"].endswith("events.jsonl")
    r = run(tmp_path, "status", "--home", str(home))
    assert "enforce" in r.stdout and "claude" in r.stdout
    r = run(tmp_path, "uninstall", "--cli", "claude,codex", "--home", str(home))
    assert r.returncode == 0
    st = json.loads(run(tmp_path, "status", "--home", str(home), "--json").stdout)
    assert st["installed"]["claude"] is False and st["installed"]["gemini"] is True
    assert not (tmp_path / "home").exists()   # $HOME was never written


def test_install_bad_json_exits_nonzero(tmp_path):
    home = tmp_path / "target"
    (home / ".claude").mkdir(parents=True)
    (home / ".claude/settings.json").write_text("{nope")
    r = run(tmp_path, "install", "--cli", "claude", "--home", str(home))
    assert r.returncode == 1 and "not valid JSON" in r.stdout


def test_unknown_cli_name(tmp_path):
    r = run(tmp_path, "install", "--cli", "vim", "--home", str(tmp_path))
    assert r.returncode != 0
