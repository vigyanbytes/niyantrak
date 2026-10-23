"""Hook installers write into a GIVEN home only: merge, never clobber, idempotent, clean uninstall.

Every test uses a temp HOME seeded with realistic existing configs. The machine's real CLI configs are never touched.
"""
import json
import os
import pathlib
import shutil
import subprocess
import sys

import pytest

from niyantrak.gate import installers

ROOT = pathlib.Path(__file__).resolve().parents[2]

CLAUDE = {
    "model": "opus",
    "permissions": {"allow": ["Bash(npm test)"], "deny": ["Read(./secrets/**)"]},
    "statusLine": {"type": "command", "command": "~/.claude/statusline.sh"},
    "hooks": {
        "PreToolUse": [{"matcher": "Bash", "hooks": [{"type": "command", "command": "~/bin/lint-bash-hook"}]}],
        "PostToolUse": [{"matcher": "Edit", "hooks": [{"type": "command", "command": "prettier --write"}]}],
    },
}
CODEX = {"hooks": {"PreToolUse": [{"matcher": ".*", "hooks": [{"type": "command", "command": "audit-hook"}]}]}}
CODEX_TOML = 'model = "gpt-5"\n[features]\ncodex_hooks = true\n'
GEMINI = {"theme": "Dracula", "mcpServers": {"docs": {"command": "docs-mcp"}},
          "hooks": {"AfterTool": [{"matcher": ".*", "hooks": [{"type": "command", "command": "after"}]}]}}
AGY = {"team": {"enabled": True, "PreToolUse": [{"matcher": ".*", "hooks": [{"type": "command", "command": "t"}]}]}}
OPENCODE_JSON = {"$schema": "https://opencode.ai/config.json", "theme": "system"}


@pytest.fixture
def home(tmp_path, monkeypatch):
    h = tmp_path / "home"
    (h / ".claude").mkdir(parents=True)
    (h / ".claude/settings.json").write_text(json.dumps(CLAUDE, indent=2))
    (h / ".codex").mkdir()
    (h / ".codex/hooks.json").write_text(json.dumps(CODEX))
    (h / ".codex/config.toml").write_text(CODEX_TOML)
    (h / ".gemini/antigravity-cli").mkdir(parents=True)
    (h / ".gemini/settings.json").write_text(json.dumps(GEMINI))
    (h / ".gemini/antigravity-cli/hooks.json").write_text(json.dumps(AGY))
    (h / ".config/opencode/plugin").mkdir(parents=True)
    (h / ".config/opencode/opencode.json").write_text(json.dumps(OPENCODE_JSON))
    (h / ".config/opencode/plugin/other.js").write_text("export const Other = async () => ({});\n")
    # env pointers must NOT redirect an explicit --home install anywhere else
    for var in ("CLAUDE_CONFIG_DIR", "CODEX_HOME", "XDG_CONFIG_HOME", "GEMINI_CLI_HOME"):
        monkeypatch.setenv(var, str(tmp_path / "elsewhere" / var))
    monkeypatch.setenv("HOME", str(tmp_path / "not-this-home"))
    return h


def snapshot(root):
    return {str(p.relative_to(root)): p.read_bytes() for p in sorted(root.rglob("*")) if p.is_file()}


def load(p):
    return json.loads(pathlib.Path(p).read_text())


def test_install_all_merges_and_preserves_existing(home, tmp_path):
    res = installers.install_many(installers.CLIS, home)
    assert all(r.ok for r in res), res
    c = load(home / ".claude/settings.json")
    assert c["model"] == "opus" and c["permissions"] == CLAUDE["permissions"] and c["statusLine"] == CLAUDE["statusLine"]
    assert c["hooks"]["PostToolUse"] == CLAUDE["hooks"]["PostToolUse"]
    pre = c["hooks"]["PreToolUse"]
    assert pre[0] == CLAUDE["hooks"]["PreToolUse"][0] and len(pre) == 2
    assert "gate check --cli claude" in pre[1]["hooks"][0]["command"]
    cx = load(home / ".codex/hooks.json")["hooks"]["PreToolUse"]
    assert cx[0] == CODEX["hooks"]["PreToolUse"][0] and "--cli codex" in cx[1]["hooks"][0]["command"]
    assert (home / ".codex/config.toml").read_text() == CODEX_TOML
    g = load(home / ".gemini/settings.json")
    assert g["theme"] == "Dracula" and g["mcpServers"] == GEMINI["mcpServers"] and g["hooks"]["AfterTool"]
    assert "--cli gemini" in g["hooks"]["BeforeTool"][0]["hooks"][0]["command"]
    a = load(home / ".gemini/antigravity-cli/hooks.json")
    assert a["team"] == AGY["team"] and a["niyantrak"]["enabled"] is True
    assert "--cli antigravity" in a["niyantrak"]["PreToolUse"][0]["hooks"][0]["command"]
    plugin = (home / ".config/opencode/plugin/niyantrak-gate.js").read_text()
    assert "tool.execute.before" in plugin and "--cli" in plugin and "opencode" in plugin
    assert load(home / ".config/opencode/opencode.json") == OPENCODE_JSON
    assert not (tmp_path / "elsewhere").exists() and not (tmp_path / "not-this-home").exists()
    # backups of the files that existed before
    assert load(str(home / ".claude/settings.json") + ".niyantrak-backup") == CLAUDE


def test_install_is_idempotent(home):
    installers.install_many(installers.CLIS, home)
    before = snapshot(home)
    res = installers.install_many(installers.CLIS, home)
    assert all(r.ok and not r.changed for r in res)
    assert snapshot(home) == before


def test_reinstall_replaces_stale_entry_in_place(home):
    installers.install("claude", home, command=["/old/python", "-m", "niyantrak.cli"])
    installers.install("claude", home)
    pre = load(home / ".claude/settings.json")["hooks"]["PreToolUse"]
    ours = [e for e in pre if installers.MARK in json.dumps(e)]
    assert len(ours) == 1 and "/old/python" not in json.dumps(ours)


def test_uninstall_restores_original_documents(home):
    original = snapshot(home)
    installers.install_many(installers.CLIS, home)
    res = installers.uninstall_many(installers.CLIS, home)
    assert all(r.ok for r in res)
    assert load(home / ".claude/settings.json") == CLAUDE
    assert load(home / ".codex/hooks.json") == CODEX
    assert load(home / ".gemini/settings.json") == GEMINI
    assert load(home / ".gemini/antigravity-cli/hooks.json") == AGY
    assert not (home / ".config/opencode/plugin/niyantrak-gate.js").exists()
    assert (home / ".config/opencode/plugin/other.js").read_bytes() == original[".config/opencode/plugin/other.js"]
    # uninstall twice is a no-op
    assert all(r.ok and not r.changed for r in installers.uninstall_many(installers.CLIS, home))


def test_fresh_home_install_then_uninstall_leaves_nothing(tmp_path):
    h = tmp_path / "fresh"
    h.mkdir()
    installers.install_many(installers.CLIS, h)
    assert (h / ".claude/settings.json").exists() and (h / ".codex/hooks.json").exists()
    installers.uninstall_many(installers.CLIS, h)
    assert [p for p in h.rglob("*") if p.is_file()] == []


def test_invalid_json_is_left_untouched(home):
    bad = home / ".claude/settings.json"
    bad.write_text("{ this is not json")
    r = installers.install("claude", home)
    assert not r.ok and "not valid JSON" in r.message
    assert bad.read_text() == "{ this is not json"
    assert not installers.is_installed("claude", home)


def test_status_reports_per_cli(home):
    assert installers.status(home) == {c: False for c in installers.CLIS}
    installers.install("codex", home)
    st = installers.status(home)
    assert st["codex"] is True and st["claude"] is False


@pytest.mark.skipif(not shutil.which("node"), reason="node not installed")
def test_opencode_plugin_blocks_and_allows_through_node(tmp_path):
    h = tmp_path / "h"
    h.mkdir()
    installers.install("opencode", h, command=[sys.executable, "-m", "niyantrak.cli"])
    plugin = h / ".config/opencode/plugin/niyantrak-gate.js"
    driver = tmp_path / "drive.mjs"
    driver.write_text(
        "const m = await import(process.argv[2]);\n"
        "const hooks = await m.NiyantrakGate({});\n"
        "const res = [];\n"
        "for (const [tool, args] of [['bash', {command: 'rm -rf /etc'}], ['bash', {command: \"echo 'rm -rf /etc'\"}]]) {\n"
        "  try { await hooks['tool.execute.before']({tool}, {args}); res.push('allow'); }\n"
        "  catch (e) { res.push('deny:' + e.message); }\n"
        "}\n"
        "console.log(JSON.stringify(res));\n")
    env = {**os.environ, "PYTHONPATH": str(ROOT), "HOME": str(h),
           "NIYANTRAK_GATE_MODE_FILE": str(tmp_path / "m"), "NIYANTRAK_GATE_LOG": str(tmp_path / "e.jsonl")}
    r = subprocess.run(["node", str(driver), plugin.as_uri()], capture_output=True, text=True, env=env, timeout=60)
    assert r.returncode == 0, r.stderr
    res = json.loads(r.stdout)
    assert res[0].startswith("deny:") and "fs.rm_protected" in res[0]
    assert res[1] == "allow"
    assert load_events(tmp_path / "e.jsonl")[-1]["agent"] == "opencode"


def load_events(p):
    return [json.loads(x) for x in pathlib.Path(p).read_text().splitlines()]
