"""Machine switch for the gate: one root-owned file per machine, so an agent cannot turn its own gate off.

    Linux / macOS   /etc/niyantrak/gate-mode
    Windows         %ProgramData%\\niyantrak\\gate-mode

Contents: ``enforce`` (or ``on``) blocks hard stops; ``audit`` logs what would be blocked and allows it; ``off``
allows everything (decisions are still logged). A missing, empty or unreadable file, or any other value, means
``enforce``: the gate fails closed. NIYANTRAK_GATE_MODE_FILE points somewhere else (tests).
"""
import ntpath
import os

MODES = ("enforce", "audit", "off")


def mode_file_path(os_name=None, environ=None):
    environ = os.environ if environ is None else environ
    if environ.get("NIYANTRAK_GATE_MODE_FILE"):
        return environ["NIYANTRAK_GATE_MODE_FILE"]
    if (os_name or os.name) == "nt":
        return ntpath.join(environ.get("ProgramData") or "C:\\ProgramData", "niyantrak", "gate-mode")
    return "/etc/niyantrak/gate-mode"


def current_mode(path=None):
    try:
        with open(path or mode_file_path(), encoding="utf-8") as fh:
            value = fh.read().strip().lower()
    except OSError:
        return "enforce"
    if value in ("off", "disabled"):
        return "off"
    if value == "audit":
        return "audit"
    return "enforce"
