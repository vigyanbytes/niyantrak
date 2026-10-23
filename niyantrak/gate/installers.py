"""Install / uninstall the gate hook into the CLI configs under a GIVEN home directory.

    claude       <home>/.claude/settings.json                 hooks.PreToolUse   (matcher "*")
    codex        <home>/.codex/hooks.json                     hooks.PreToolUse   (matcher ".*")
    gemini       <home>/.gemini/settings.json                 hooks.BeforeTool   (matcher ".*", timeout in ms)
    antigravity  <home>/.gemini/antigravity-cli/hooks.json    group "niyantrak" {enabled, PreToolUse}
    opencode     <home>/.config/opencode/plugin/niyantrak-gate.js   (tool.execute.before plugin)

Rules: merge, never clobber -- every other key and every other hook is kept in order; our entry is recognised by
MARK and replaced in place, so installing twice changes nothing. A file that is not valid JSON is left untouched and
reported. Before the first change to an existing file a one-time ``<file>.niyantrak-backup`` is written. Uninstall
removes only our entries (and containers that become empty, and a file that becomes ``{}``).

The home is always explicit: CLAUDE_CONFIG_DIR, CODEX_HOME and XDG_CONFIG_HOME are deliberately ignored here so an
install aimed at one home can never land in another.
"""
import json
import os
import shlex
import subprocess
import sys
from dataclasses import dataclass

CLIS = ("claude", "codex", "gemini", "antigravity", "opencode")
MARK = "gate check --cli"
GROUP = "niyantrak"

JSON_HOOKS = {   # cli -> (relative path, event key, matcher, timeout)
    "claude": (".claude/settings.json", "PreToolUse", "*", 10),
    "codex": (".codex/hooks.json", "PreToolUse", ".*", 10),
    "gemini": (".gemini/settings.json", "BeforeTool", ".*", 10000),
}
# Codex runs a user hook only after the operator has reviewed and trusted it ("N hooks need review before they can
# run"; hooks/list reports it as untrusted until then). Niyantrak never writes that trust for the operator.
INSTALL_NOTES = {
    "codex": "; Codex runs it only after you review and trust it in Codex (new hooks need review before they run)",
}
AGY_PATH = ".gemini/antigravity-cli/hooks.json"
OPENCODE_PATH = ".config/opencode/plugin/niyantrak-gate.js"

OPENCODE_PLUGIN = """\
// Niyantrak gate for OpenCode. Managed by `niyantrak gate install --cli opencode`;
// remove with `niyantrak gate uninstall --cli opencode`. Marker: gate check --cli opencode
//
// OpenCode loads plugin/*.js from its config dir and calls tool.execute.before before every tool call;
// throwing blocks the call and the message goes back to the model. The decision is made by the same
// Niyantrak gate every other CLI uses. If the gate cannot answer, the call is blocked (fail closed).
import { spawnSync } from "node:child_process";

const GATE = __ARGV__;

export const NiyantrakGate = async () => ({
  "tool.execute.before": async (input, output) => {
    const payload = JSON.stringify({ tool: input && input.tool, args: (output && output.args) || {} });
    const r = spawnSync(GATE[0], GATE.slice(1), { input: payload, encoding: "utf8", timeout: 15000 });
    let res = null;
    try { res = JSON.parse(r.stdout || ""); } catch (e) { res = null; }
    if (!res || (res.decision !== "allow" && res.decision !== "deny")) {
      throw new Error("Niyantrak gate unavailable (" + (r.error ? r.error.message : "exit " + r.status) +
        "); tool call blocked. Remove the gate with: niyantrak gate uninstall --cli opencode");
    }
    if (res.decision === "deny") throw new Error(res.reason || "Blocked by Niyantrak gate");
  },
});
"""


@dataclass
class Result:
    cli: str
    path: str
    ok: bool
    changed: bool
    message: str


def default_command():
    return [sys.executable, "-m", "niyantrak.cli"]


def hook_argv(cli, command=None):
    return list(command or default_command()) + ["gate", "check", "--cli", cli]


def hook_command(cli, command=None):
    argv = hook_argv(cli, command)
    return subprocess.list2cmdline(argv) if os.name == "nt" else shlex.join(argv)


def target_path(cli, home):
    rel = JSON_HOOKS[cli][0] if cli in JSON_HOOKS else AGY_PATH if cli == "antigravity" else OPENCODE_PATH
    return os.path.join(os.fspath(home), *rel.split("/"))


def _ours(obj, cli=None):
    s = json.dumps(obj)
    return MARK in s and (cli is None or f"{MARK} {cli}" in s)


def _read_json(path):
    """(doc, text) -- ({}, None) when absent; raises ValueError when not a JSON object."""
    if not os.path.isfile(path):
        return {}, None
    with open(path, encoding="utf-8") as fh:
        text = fh.read()
    doc = json.loads(text) if text.strip() else {}
    if not isinstance(doc, dict):
        raise ValueError("not a JSON object")
    return doc, text


def _write(path, text, old_text):
    if old_text is not None:
        backup = path + ".niyantrak-backup"
        if not os.path.exists(backup):
            with open(backup, "w", encoding="utf-8") as fh:
                fh.write(old_text)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".niyantrak-tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        fh.write(text)
    if os.path.exists(path):
        os.chmod(tmp, os.stat(path).st_mode & 0o7777)
    os.replace(tmp, path)


def _dump(doc):
    return json.dumps(doc, indent=2) + "\n"


def _entry(cli, command):
    _rel, _event, matcher, timeout = JSON_HOOKS.get(cli, (None, None, ".*", 10))
    return {"matcher": matcher, "hooks": [{"type": "command", "command": hook_command(cli, command),
                                           "timeout": timeout}]}


def _install_json(cli, path, doc, command):
    event = JSON_HOOKS[cli][1]
    hooks = doc.setdefault("hooks", {})
    if not isinstance(hooks, dict) or not isinstance(hooks.setdefault(event, []), list):
        raise ValueError(f'"hooks.{event}" has an unexpected shape')
    new, out, placed = _entry(cli, command), [], False
    for e in hooks[event]:                      # replace our entry where it was; drop duplicates
        if not _ours(e):
            out.append(e)
        elif not placed:
            out.append(new)
            placed = True
    if not placed:
        out.append(new)
    hooks[event] = out
    return doc


def _install_agy(cli, path, doc, command):
    doc[GROUP] = {"enabled": True, "PreToolUse": [_entry(cli, command)]}
    return doc


def _uninstall_json(cli, doc):
    event = JSON_HOOKS[cli][1]
    hooks = doc.get("hooks")
    if not isinstance(hooks, dict) or not isinstance(hooks.get(event), list):
        return doc
    hooks[event] = [e for e in hooks[event] if not _ours(e)]
    if not hooks[event]:
        del hooks[event]
    if not hooks:
        del doc["hooks"]
    return doc


def install(cli, home, command=None):
    path = target_path(cli, home)
    if cli == "opencode":
        text = OPENCODE_PLUGIN.replace("__ARGV__", json.dumps(hook_argv(cli, command)))
        old = open(path, encoding="utf-8").read() if os.path.isfile(path) else None
        if old is not None and MARK not in old:
            return Result(cli, path, False, False, f"{path} exists and is not ours; left untouched")
        if old == text:
            return Result(cli, path, True, False, "already current")
        _write(path, text, None)
        return Result(cli, path, True, True, "installed")
    try:
        doc, old = _read_json(path)
        doc = (_install_agy if cli == "antigravity" else _install_json)(cli, path, doc, command)
    except ValueError as exc:
        return Result(cli, path, False, False, f"{path}: not valid JSON or unexpected shape ({exc}); left untouched")
    text = _dump(doc)
    if text == old:
        return Result(cli, path, True, False, "already current")
    _write(path, text, old)
    return Result(cli, path, True, True, "installed" + INSTALL_NOTES.get(cli, ""))


def uninstall(cli, home):
    path = target_path(cli, home)
    if not os.path.isfile(path):
        return Result(cli, path, True, False, "not installed")
    if cli == "opencode":
        if MARK not in open(path, encoding="utf-8").read():
            return Result(cli, path, False, False, f"{path} is not ours; left untouched")
        os.remove(path)
        return Result(cli, path, True, True, "removed")
    try:
        doc, old = _read_json(path)
    except ValueError as exc:
        return Result(cli, path, False, False, f"{path}: not valid JSON ({exc}); left untouched")
    if cli == "antigravity":
        doc.pop(GROUP, None)
    else:
        doc = _uninstall_json(cli, doc)
    if not doc:
        os.remove(path)
        return Result(cli, path, True, True, "removed (file was only the gate)")
    text = _dump(doc)
    if text == old or json.loads(old or "{}") == doc:
        return Result(cli, path, True, False, "not installed")
    _write(path, text, None)
    return Result(cli, path, True, True, "removed")


def is_installed(cli, home):
    path = target_path(cli, home)
    try:
        with open(path, encoding="utf-8") as fh:
            text = fh.read()
    except OSError:
        return False
    if cli == "opencode":
        return f"{MARK} opencode" in text
    try:
        doc = json.loads(text)
    except ValueError:
        return False
    if cli == "antigravity":
        return isinstance(doc, dict) and _ours(doc.get(GROUP), cli)
    hooks = doc.get("hooks") if isinstance(doc, dict) else None
    return isinstance(hooks, dict) and any(_ours(e, cli) for e in hooks.get(JSON_HOOKS[cli][1]) or [])


def status(home):
    return {cli: is_installed(cli, home) for cli in CLIS}


def install_many(clis, home, command=None):
    return [install(c, home, command) for c in clis]


def uninstall_many(clis, home):
    return [uninstall(c, home) for c in clis]
