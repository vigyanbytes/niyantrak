"""The files `niyantrak gate install` writes, checked against the real agent CLIs that read them.

Three layers, so a format drift is caught even on a machine without the CLIs:

  1. golden files   -- the exact bytes written for every CLI are pinned under fixtures/cli_formats/
  2. structure      -- each file is checked against the format the CLI documents (and that the CLI's own code was
                       seen to accept: event names, handler types, timeout units, plugin discovery glob, hook name)
  3. the real CLI   -- when the CLI is installed, it is asked to read the file in an isolated, throwaway HOME, and
                       a deliberately broken file proves the same check really rejects bad input:
                         claude    `claude doctor`                (lists "Invalid settings" per file and key)
                         gemini    `gemini --list-extensions`     (loads settings; "Invalid configuration" on errors)
                                   `gemini hooks migrate --from-claude` (Gemini's own Claude->Gemini translation)
                         codex     `codex app-server` hooks/list  (Codex's own parse of hooks.json: errors, warnings)
                         opencode  `opencode debug config`        (resolved config: discovered plugin files)

No login, no prompt, no model call: every CLI runs with HOME/XDG/CLAUDE_CONFIG_DIR/CODEX_HOME pointed at tmp_path
and API keys removed from the environment. Set NIYANTRAK_SKIP_REAL_CLIS=1 to skip layer 3.
"""
import json
import os
import pathlib
import re
import select
import shutil
import subprocess
import time

import pytest

from niyantrak.gate import installers

FIX = pathlib.Path(__file__).parent / "fixtures" / "cli_formats"
CMD = ["niyantrak"]                                          # stable command so the golden files are portable
GOLDEN = {
    "claude": "claude-settings.json",
    "codex": "codex-hooks.json",
    "gemini": "gemini-settings.json",
    "antigravity": "antigravity-hooks.json",
    "opencode": "opencode-niyantrak-gate.js",
}
SKIP_REAL = os.environ.get("NIYANTRAK_SKIP_REAL_CLIS") == "1"


def installed(tmp_path, cli, command=CMD):
    home = tmp_path / "home"
    home.mkdir(parents=True, exist_ok=True)
    r = installers.install(cli, home, command=command)
    assert r.ok, r.message
    return home, pathlib.Path(r.path)


def cli_env(home):
    env = dict(os.environ, HOME=str(home), XDG_CONFIG_HOME=str(home / ".config"),
               XDG_DATA_HOME=str(home / ".local/share"), XDG_CACHE_HOME=str(home / ".cache"),
               XDG_STATE_HOME=str(home / ".local/state"), CLAUDE_CONFIG_DIR=str(home / ".claude"),
               CODEX_HOME=str(home / ".codex"), NO_COLOR="1", DISABLE_AUTOUPDATER="1",
               OPENCODE_DISABLE_AUTOUPDATE="1", GEMINI_CLI_NO_RELAUNCH="1")
    for k in ("ANTHROPIC_API_KEY", "CLAUDE_CODE_OAUTH_TOKEN", "OPENAI_API_KEY", "CODEX_API_KEY", "GEMINI_API_KEY",
              "GOOGLE_API_KEY", "GOOGLE_GENAI_USE_VERTEXAI", "GOOGLE_GENAI_USE_GCA", "OPENCODE_CONFIG",
              "OPENCODE_CONFIG_DIR"):
        env.pop(k, None)
    return env


def run_cli(home, argv, cwd=None, timeout=90):
    return subprocess.run(argv, env=cli_env(home), cwd=str(cwd or home), capture_output=True, text=True,
                          timeout=timeout, stdin=subprocess.DEVNULL)


def real(cli):
    return pytest.mark.skipif(SKIP_REAL or not shutil.which(cli), reason=f"{cli} not installed (or real CLIs skipped)")


# ---------------------------------------------------------------- 1. golden files

@pytest.mark.parametrize("cli", installers.CLIS)
def test_golden_file(tmp_path, cli):
    _home, path = installed(tmp_path, cli)
    assert path.read_text(encoding="utf-8") == (FIX / GOLDEN[cli]).read_text(encoding="utf-8")


@pytest.mark.parametrize("cli,rel", [("claude", ".claude/settings.json"), ("codex", ".codex/hooks.json"),
                                     ("gemini", ".gemini/settings.json"),
                                     ("antigravity", ".gemini/antigravity-cli/hooks.json"),
                                     ("opencode", ".config/opencode/plugin/niyantrak-gate.js")])
def test_documented_locations(tmp_path, cli, rel):
    home, path = installed(tmp_path, cli)
    assert path == home / rel


# ---------------------------------------------------------------- 2. structure, per documented format

CLAUDE_EVENTS = {"PreToolUse", "PostToolUse", "Notification", "UserPromptSubmit", "SessionStart", "SessionEnd",
                 "Stop", "SubagentStop", "PreCompact", "PermissionRequest"}
CODEX_EVENTS = {"PreToolUse", "PermissionRequest", "PostToolUse", "PreCompact", "PostCompact", "SessionStart",
                "SessionEnd", "UserPromptSubmit", "SubagentStart", "SubagentStop", "Stop"}
GEMINI_EVENTS = {"BeforeTool", "AfterTool", "BeforeAgent", "AfterAgent", "Notification", "SessionStart", "SessionEnd",
                 "PreCompress", "BeforeModel", "AfterModel", "BeforeToolSelection"}


def _only_entry(doc, event, events):
    assert set(doc) == {"hooks"} and set(doc["hooks"]) <= events and list(doc["hooks"]) == [event]
    (entry,) = doc["hooks"][event]
    assert set(entry) == {"matcher", "hooks"}
    (hook,) = entry["hooks"]
    assert set(hook) == {"type", "command", "timeout"} and hook["type"] == "command"
    assert isinstance(hook["command"], str) and isinstance(hook["timeout"], int)
    return entry, hook


def test_claude_structure(tmp_path):
    _h, p = installed(tmp_path, "claude")
    entry, hook = _only_entry(json.loads(p.read_text()), "PreToolUse", CLAUDE_EVENTS)
    assert entry["matcher"] == "*"                            # Claude: "*" (or "") matches every tool
    assert 1 <= hook["timeout"] <= 600                        # seconds
    assert hook["command"].endswith("gate check --cli claude")


def test_codex_structure(tmp_path):
    _h, p = installed(tmp_path, "codex")
    entry, hook = _only_entry(json.loads(p.read_text()), "PreToolUse", CODEX_EVENTS)
    re.compile(entry["matcher"])                              # Codex: matcher is a regex over the tool name
    assert re.fullmatch(entry["matcher"], "shell") and re.fullmatch(entry["matcher"], "apply_patch")
    assert 1 <= hook["timeout"] <= 600                        # seconds (Codex reports it back as timeoutSec)


def test_gemini_structure(tmp_path):
    _h, p = installed(tmp_path, "gemini")
    entry, hook = _only_entry(json.loads(p.read_text()), "BeforeTool", GEMINI_EVENTS)
    assert re.search(entry["matcher"], "run_shell_command")   # Gemini: regex (new RegExp(matcher).test(toolName))
    assert 1000 <= hook["timeout"] <= 600_000                 # MILLISECONDS (Gemini's default is 60000)


def test_timeouts_mean_the_same_wall_time_everywhere(tmp_path):
    secs = {}
    for cli, unit in (("claude", 1), ("codex", 1), ("gemini", 1000)):
        _h, p = installed(tmp_path / cli, cli)
        ev = installers.JSON_HOOKS[cli][1]
        secs[cli] = json.loads(p.read_text())["hooks"][ev][0]["hooks"][0]["timeout"] / unit
    assert len(set(secs.values())) == 1, secs


def test_antigravity_structure(tmp_path):
    _h, p = installed(tmp_path, "antigravity")
    doc = json.loads(p.read_text())
    assert set(doc) == {"niyantrak"} and doc["niyantrak"]["enabled"] is True
    assert set(doc["niyantrak"]) == {"enabled", "PreToolUse"}
    (entry,) = doc["niyantrak"]["PreToolUse"]
    assert entry["hooks"][0]["type"] == "command" and entry["hooks"][0]["timeout"] == 10


def test_opencode_structure(tmp_path):
    home, p = installed(tmp_path, "opencode")
    rel = p.relative_to(home / ".config/opencode").as_posix()
    assert re.fullmatch(r"(plugin|plugins)/[^/]+\.(ts|js)", rel)          # OpenCode scans {plugin,plugins}/*.{ts,js}
    src = p.read_text()
    exports = re.findall(r"^export\s+(?:const|async function|function)\s+(\w+)", src, re.M)
    assert exports == ["NiyantrakGate"] and "export default" not in src  # every export must be a plugin function
    assert re.search(r'"tool\.execute\.before":\s*async \(input, output\)', src)
    assert "output && output.args" in src and "input && input.tool" in src  # trigger(name, {tool,...}, {args})
    assert 'throw new Error' in src                                        # throwing is how a plugin blocks
    gate = json.loads(re.search(r"^const GATE = (.+);$", src, re.M).group(1))
    assert gate == CMD + ["gate", "check", "--cli", "opencode"]


# ---------------------------------------------------------------- 3. the real CLIs

@real("claude")
def test_claude_doctor_accepts_our_settings(tmp_path):
    home, p = installed(tmp_path, "claude")
    r = run_cli(home, ["claude", "doctor"])
    out = r.stdout + r.stderr
    assert "Claude Code doctor" in out, out[-2000:]
    assert "Invalid settings" not in out and str(p) not in out, out[-2000:]


@real("claude")
def test_claude_doctor_really_rejects_a_bad_hook(tmp_path):
    home = tmp_path / "bad"
    (home / ".claude").mkdir(parents=True)
    (home / ".claude/settings.json").write_text(json.dumps(
        {"hooks": {"PreToolUse": [{"matcher": "*", "hooks": [{"type": "commandd", "command": "x"}]}]}}))
    out = run_cli(home, ["claude", "doctor"]).stdout
    assert "Invalid settings" in out and "hooks.PreToolUse.0.hooks.0.type" in out


@real("gemini")
def test_gemini_loads_our_settings_without_errors(tmp_path):
    home, _p = installed(tmp_path, "gemini")
    r = run_cli(home, ["gemini", "--list-extensions"])
    assert "Invalid configuration" not in r.stderr + r.stdout, r.stderr[-2000:]


@real("gemini")
def test_gemini_really_rejects_a_bad_hook(tmp_path):
    home = tmp_path / "bad"
    (home / ".gemini").mkdir(parents=True)
    (home / ".gemini/settings.json").write_text(json.dumps(
        {"hooks": {"BeforeTool": [{"matcher": ".*", "hooks": [{"type": "command", "command": 5, "timeout": "x"}]}]}}))
    r = run_cli(home, ["gemini", "--list-extensions"])
    assert "Invalid configuration" in r.stderr and "hooks.BeforeTool[0].hooks[0].timeout" in r.stderr


@real("gemini")
def test_gemini_own_migration_of_our_claude_hook_matches_our_gemini_hook(tmp_path):
    """Gemini's `hooks migrate --from-claude` is Gemini's own statement of how a Claude hook looks in Gemini."""
    home, claude_file = installed(tmp_path, "claude")
    proj = tmp_path / "proj"
    (proj / ".claude").mkdir(parents=True)
    shutil.copy(claude_file, proj / ".claude/settings.json")
    r = run_cli(home, ["gemini", "hooks", "migrate", "--from-claude"], cwd=proj)
    assert r.returncode == 0, r.stderr
    migrated = json.loads((proj / ".gemini/settings.json").read_text())["hooks"]
    assert {k for k, v in migrated.items() if v} == {"BeforeTool"}     # Claude PreToolUse == Gemini BeforeTool
    (m_entry,) = migrated["BeforeTool"]
    _h2, ours = installed(tmp_path / "g", "gemini")
    (o_entry,) = json.loads(ours.read_text())["hooks"]["BeforeTool"]
    assert set(m_entry) == set(o_entry) and set(m_entry["hooks"][0]) == set(o_entry["hooks"][0])
    assert m_entry["hooks"][0]["type"] == o_entry["hooks"][0]["type"] == "command"
    # same command apart from the --cli tag; Gemini copies the timeout number verbatim (its runner reads ms,
    # which is why ours is 10000 = the same 10 s Claude gets)
    assert m_entry["hooks"][0]["command"].replace("--cli claude", "--cli gemini") == o_entry["hooks"][0]["command"]


def _codex_hooks_list(home):
    p = subprocess.Popen(["codex", "app-server", "--listen", "stdio://"], env=cli_env(home), cwd=str(home),
                         stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, bufsize=1)

    def send(o):
        p.stdin.write(json.dumps(o) + "\n")
        p.stdin.flush()

    def recv(want, timeout=60):
        end = time.time() + timeout
        while time.time() < end:
            if select.select([p.stdout], [], [], 1)[0]:
                line = p.stdout.readline()
                if not line:
                    return None
                msg = json.loads(line)
                if msg.get("id") == want:
                    return msg
        return None

    try:
        send({"jsonrpc": "2.0", "id": 1, "method": "initialize",
              "params": {"clientInfo": {"name": "niyantrak-format-test", "version": "0"}}})
        assert recv(1) is not None
        send({"jsonrpc": "2.0", "method": "initialized"})
        send({"jsonrpc": "2.0", "id": 2, "method": "hooks/list", "params": {"cwds": [str(home)]}})
        resp = recv(2)
    finally:
        p.terminate()
        try:
            p.wait(timeout=10)
        except subprocess.TimeoutExpired:
            p.kill()
    assert resp and "result" in resp, resp
    (entry,) = resp["result"]["data"]
    return entry


@real("codex")
def test_codex_parses_our_hook(tmp_path):
    home, p = installed(tmp_path, "codex")
    entry = _codex_hooks_list(home)
    assert entry["errors"] == [] and entry["warnings"] == []
    (hook,) = entry["hooks"]
    assert hook["eventName"] == "preToolUse" and hook["handlerType"] == "command"
    assert hook["matcher"] == ".*" and hook["timeoutSec"] == 10 and hook["enabled"] is True
    assert hook["command"] == "niyantrak gate check --cli codex" and hook["sourcePath"] == str(p)
    # Codex runs a user hook only after the operator trusts it (new hooks are listed as untrusted). Niyantrak
    # never writes that trust itself; the installer says so instead.
    assert hook["trustStatus"] in ("untrusted", "trusted")


@real("codex")
def test_codex_really_rejects_a_bad_hook(tmp_path):
    home = tmp_path / "bad"
    (home / ".codex").mkdir(parents=True)
    (home / ".codex/hooks.json").write_text(json.dumps(
        {"hooks": {"PreToolUse": [{"matcher": ".*", "hooks": [{"type": "commandd", "command": "x"}]}]}}))
    entry = _codex_hooks_list(home)
    assert entry["hooks"] == [] and any("commandd" in w for w in entry["warnings"] + [e["message"] for e in entry["errors"]])


@real("opencode")
def test_opencode_discovers_our_plugin(tmp_path):
    home, p = installed(tmp_path, "opencode")
    r = run_cli(home, ["opencode", "debug", "config"])
    assert r.returncode == 0, r.stderr[-2000:]
    cfg = json.loads(r.stdout)
    assert p.as_uri() in cfg.get("plugin", []), cfg


@real("opencode")
def test_opencode_does_not_discover_a_misplaced_plugin(tmp_path):
    home = tmp_path / "bad"
    wrong = home / ".config/opencode/hooks/niyantrak-gate.js"   # not under plugin/ or plugins/
    wrong.parent.mkdir(parents=True)
    wrong.write_text("export const X = async () => ({});\n")
    cfg = json.loads(run_cli(home, ["opencode", "debug", "config"]).stdout)
    assert wrong.as_uri() not in cfg.get("plugin", [])


def test_codex_install_says_the_hook_needs_the_operators_trust(tmp_path):
    home = tmp_path / "h"
    home.mkdir()
    r = installers.install("codex", home, command=CMD)
    assert r.ok and r.changed and "trust" in r.message.lower()
    assert "trust" not in installers.install("claude", home, command=CMD).message.lower()
