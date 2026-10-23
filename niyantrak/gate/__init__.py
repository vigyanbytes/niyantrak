"""Niyantrak agent gate (free edition): hard stops for AI coding agents, enforced by each CLI's own hook.

    engine      decide(ToolCall) -> Decision (allow, or deny with a rule id and reason)
    shell       which commands in a shell string actually execute (mentions are data)
    mode        the per-machine switch file (enforce / audit / off)
    events      5W JSONL log of every decision (no command text, only its sha256)
    adapters    Claude Code, Codex, Gemini CLI / Antigravity and OpenCode hook formats
    installers  merge the hook into a given home's CLI configs; idempotent; uninstall
"""
from .engine import Decision, ToolCall, decide  # noqa: F401
