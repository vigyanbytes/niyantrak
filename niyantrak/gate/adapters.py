"""Hook adapters: read one CLI's PreToolUse-style payload, decide, log, answer in that CLI's format.

    claude       Claude Code PreToolUse: {tool_name, tool_input}. Deny = stdout
                 {"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny", ...}}, exit 0.
                 Allow = no output, exit 0, so the user's own permission rules still apply (the gate only narrows).
    codex        Codex hooks.json PreToolUse (Claude-compatible input; command may be an argv list).
                 Deny = reason on stderr, exit 2. Allow = no output, exit 0.
    gemini       Gemini CLI BeforeTool {tool_name, tool_input}; also accepts the Antigravity shape.
    antigravity  Antigravity hooks {toolCall: {name, args}}. Both answer {"decision": "allow"|"deny", "reason"}.
    opencode     The installed plugin sends {tool, args}; answers {"decision": "allow"|"deny", "reason"}.

A payload that cannot be read is denied (rule gate.bad_payload) unless the machine switch is off.
"""
import json

from . import events
from .engine import ToolCall, bad_payload, decide

CLIS = ("claude", "codex", "gemini", "antigravity", "opencode")


def parse_payload(cli, payload):
    if isinstance(payload.get("toolCall"), dict):
        tc = payload["toolCall"]
        return ToolCall.from_input(tc.get("name", ""), tc.get("args") or {})
    if cli == "opencode" or ("tool" in payload and "args" in payload and "tool_name" not in payload):
        return ToolCall.from_input(payload.get("tool", ""), payload.get("args") or {})
    return ToolCall.from_input(payload.get("tool_name", ""), payload.get("tool_input") or {})


def message(decision):
    verb = "Blocked" if decision.blocks else "Would block (audit mode)"
    return (f"{verb} by Niyantrak gate [{decision.rule_id}]: {decision.reason}. AI agents may not do this on their "
            "own; ask a human operator to run it if it is really needed.")


def render(cli, decision):
    """(stdout, stderr, exit code) in the CLI's own hook format."""
    deny = decision.blocks
    if cli == "claude":
        if not deny:
            return "", "", 0
        return json.dumps({"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny",
                                                  "permissionDecisionReason": message(decision)}}), "", 0
    if cli == "codex":
        return ("", message(decision), 2) if deny else ("", "", 0)
    if deny:
        return json.dumps({"decision": "deny", "reason": message(decision)}), "", 0
    return json.dumps({"decision": "allow"}), "", 0


def handle(cli, raw):
    if cli not in CLIS:
        raise ValueError(f"unknown CLI {cli!r}; expected one of {', '.join(CLIS)}")
    try:
        payload = json.loads(raw)
        if not isinstance(payload, dict):
            raise ValueError("payload is not a JSON object")
    except ValueError:
        call, decision = ToolCall(tool=""), bad_payload()
    else:
        call = parse_payload(cli, payload)
        decision = decide(call)
    events.record(call, decision, agent=cli)
    return render(cli, decision)
