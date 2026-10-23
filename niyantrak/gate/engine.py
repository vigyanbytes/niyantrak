"""Gate decision engine (free edition): hard stops are denied with a rule id and a reason; everything else is allowed.

Hard stops:
  destructive  rm -r on system/data roots or a home, find -delete / chmod -R on them, disk formatting and raw
               block-device writes, zfs/zpool destroy, history-rewriting or work-discarding git
  secret       reading or touching credential files by path (shell arguments, redirections, file tools)
  production   changing services, firewalls, deployments or power state

Shell commands are judged on what would actually execute (niyantrak.gate.shell), never on text that merely mentions
a command. File contents written by an editor tool are data and are never inspected as commands.
"""
import json
import os
import posixpath
import re
import shlex
from dataclasses import dataclass, field

from . import shell as sh
from .mode import current_mode, mode_file_path

RULES = {
    "fs.rm_protected": "Recursive delete of a system, data or home directory",
    "fs.rm_no_preserve_root": "rm --no-preserve-root removes the whole file system",
    "fs.find_delete_protected": "find -delete on a system or data directory",
    "fs.recursive_perm_protected": "Recursive permission/ownership change on a system or data directory",
    "disk.format": "Formatting, wiping or repartitioning a disk",
    "disk.raw_write": "Writing raw data to a block device",
    "disk.zfs_destroy": "Destroying a ZFS dataset or pool",
    "docker.data_loss": "Deleting Docker volumes or pruning the Docker system",
    "git.force_push": "Force-push rewrites shared history on the remote",
    "git.remote_delete": "Deleting a remote branch or tag",
    "git.reset_hard": "git reset --hard discards uncommitted work",
    "git.clean_force": "git clean -f deletes untracked files",
    "git.history_rewrite": "Rewriting or expiring repository history",
    "git.discard_changes": "Discarding all working-tree changes",
    "git.branch_force_delete": "Force-deleting a branch",
    "git.stash_drop": "Dropping stashed work",
    "secret.path": "Access to a credential or secret file",
    "prod.service": "Changing a system service",
    "prod.firewall": "Changing firewall rules",
    "prod.deploy": "Deploying, publishing or changing production infrastructure",
    "prod.power": "Rebooting or powering off the machine",
    "gate.tamper": "Changing the gate's own machine switch",
    "gate.too_deep": "Command nests shells too deeply to inspect",
    "gate.bad_payload": "The hook payload could not be read",
}
CLASS_OF = {"fs": "destructive", "disk": "destructive", "docker": "destructive", "git": "destructive",
            "secret": "secret", "prod": "production", "gate": "governance"}

SHELL_TOOLS = {"bash", "shell", "exec_command", "local_shell", "run_shell_command", "run_command", "terminal",
               "execute_command", "powershell"}
PATH_LIST_KEYS = ("paths", "file_paths", "files")
GLOB_TOOLS = {"glob", "find_files", "list", "find_by_name"}
PATCH_TOOLS = {"apply_patch", "patch"}
PATCH_FILE_RE = re.compile(r"^\*\*\* (?:Add File|Update File|Delete File|Move to): (.+?)\s*$", re.M)

SECRET_RE = re.compile("|".join([
    r"(^|/)secret\.d(/|$)",
    r"(^|/)\.claude/\.credentials\.json$",
    r"(^|/)\.codex/auth\.json$",
    r"(^|/)\.gemini/(oauth_creds|google_accounts)\.json$",
    r"(^|/)opencode/auth\.json$",
    r"(^|/)\.ssh/id_[a-z0-9_]+$",
    r"(^|/)\.ssh/[^/]+\.pem$",
    r"(^|/)\.env(\.[\w.-]+)?$",
    r"(^|/)\.aws/credentials$",
    r"(^|/)\.netrc$",
    r"(^|/)\.git-credentials$",
    r"(^|/)\.pgpass$",
    r"(^|/)\.docker/config\.json$",
    r"(^|/)\.kube/config$",
    r"(^|/)\.config/gh/hosts\.yml$",
    r"(^|/)\.npmrc$",
    r"(^|/)\.pypirc$",
    r"(^|/)\.gnupg/private-keys",
    r"^/etc/g?shadow$",
]), re.I)
SECRET_EXEMPT_RE = re.compile(r"\.(example|sample|template|dist)$", re.I)
READ_ONLY_TOOLS = {"read", "read_file", "view_file", "view", "glob", "grep", "ls", "list", "list_dir",
                   "list_directory", "read_many_files", "search_file_content", "find_by_name", "grep_search",
                   "codebase_search", "notebookread"}
MODE_FILE_WRITERS = {"tee", "cp", "mv", "rm", "install", "ln", "truncate", "chmod", "chown", "chattr", "sed", "perl",
                     "unlink", "shred", "touch", "rsync", "dd", "vi", "vim", "nano", "ed", "sponge"}
DATA_COMMANDS = {"echo", "printf", "export", "true", "false", ":", "declare", "typeset", "local", "readonly"}

SYSTEM_ROOTS = {"etc", "usr", "var", "boot", "root", "opt", "srv", "dev", "mnt", "media", "lib", "lib32", "lib64",
                "libx32", "bin", "sbin", "proc", "sys", "snap", "run", "home", "users", "system", "library",
                "applications", "volumes", "private"}
HOME_ROOTS = {"home", "users"}
SAFE_UNDER = ("/var/tmp",)
HOME_WORDS = {"~", "$HOME", "${HOME}"}
DEV_SAFE = {"null", "zero", "stdout", "stderr", "stdin", "tty", "random", "urandom", "full", "ptmx"}


@dataclass(frozen=True)
class ToolCall:
    """A normalised tool call: the tool name, the shell command (if any) and file paths it names."""
    tool: str
    command: str = None
    paths: tuple = ()

    @classmethod
    def from_input(cls, tool, tool_input):
        tool = str(tool or "")
        inp = tool_input if isinstance(tool_input, dict) else {"command": tool_input}
        cmd = inp.get("command", inp.get("cmd"))
        if cmd is None:
            for k, v in inp.items():
                if isinstance(v, str) and "command" in k.lower():
                    cmd = v
                    break
        if isinstance(cmd, (list, tuple)):
            cmd = shlex.join(str(x) for x in cmd)
        paths = []
        for k, v in inp.items():
            kl = k.lower()
            if isinstance(v, str) and kl != "command" and ("path" in kl or kl in ("file", "filename", "targetfile")):
                paths.append(v)
            elif kl in PATH_LIST_KEYS and isinstance(v, list):
                paths.extend(str(x) for x in v if isinstance(x, (str, int)))
        if tool.lower() in GLOB_TOOLS and isinstance(inp.get("pattern"), str):
            paths.append(inp["pattern"])
        for k, v in inp.items():
            if isinstance(v, str) and "*** Begin Patch" in v and (tool.lower() in PATCH_TOOLS or k in ("input", "patch")):
                paths.extend(PATCH_FILE_RE.findall(v))
        return cls(tool=tool, command=None if cmd is None else str(cmd), paths=tuple(paths))

    @property
    def is_shell(self):
        return self.command is not None

    @property
    def base_class(self):
        if self.is_shell:
            return "shell"
        return "file" if self.paths else "tool"

    def fingerprint(self):
        if self.is_shell:
            return self.command
        return json.dumps({"tool": self.tool, "paths": list(self.paths)}, sort_keys=True)


@dataclass(frozen=True)
class Decision:
    outcome: str            # allow | deny | audit (would deny, allowed because the machine is in audit mode)
    rule_id: str
    reason: str
    command_class: str
    mode: str = "enforce"
    detail: str = field(default="", compare=False)

    @property
    def blocks(self):
        return self.outcome == "deny"

    def to_dict(self):
        return {"outcome": self.outcome, "rule_id": self.rule_id, "reason": self.reason,
                "command_class": self.command_class, "mode": self.mode}


def _hit_decision(rule_id, mode, detail=""):
    return Decision("deny" if mode == "enforce" else "audit", rule_id, RULES[rule_id],
                    CLASS_OF[rule_id.split(".")[0]], mode, detail)


def decide(call, mode=None):
    mode = mode or current_mode()
    if mode == "off":
        return Decision("allow", "gate.off", "Gate switched off on this machine", call.base_class, mode)
    hit = evaluate(call)
    if not hit:
        return Decision("allow", "allow.default", "No hard stop matched", call.base_class, mode)
    return _hit_decision(hit[0], mode, hit[1])


def bad_payload(mode=None):
    mode = mode or current_mode()
    if mode == "off":
        return Decision("allow", "gate.off", "Gate switched off on this machine", "tool", mode)
    return _hit_decision("gate.bad_payload", mode)


def evaluate(call):
    """(rule_id, detail) for the first hard stop, else None."""
    if call.tool.lower() not in READ_ONLY_TOOLS and any(is_mode_file(p) for p in call.paths):
        return "gate.tamper", ""
    for p in call.paths:
        if is_secret_path(p):
            return "secret.path", p
    if call.is_shell:
        try:
            cmds = sh.executed(call.command)
        except sh.TooDeep:
            return "gate.too_deep", ""
        for cmd in cmds:
            hit = check_command(cmd)
            if hit:
                return hit
    return None


# -- path helpers --------------------------------------------------------------------------------------------------
def is_mode_file(p):
    p = str(p).strip().replace("\\", "/").rstrip("/").lower()
    return bool(p) and (p.endswith("niyantrak/gate-mode") or p == mode_file_path().replace("\\", "/").lower())


def is_secret_path(p):
    p = str(p).strip().replace("\\", "/")
    return bool(p) and bool(SECRET_RE.search(p)) and not SECRET_EXEMPT_RE.search(p)


def extra_protected():
    raw = os.environ.get("NIYANTRAK_GATE_PROTECTED", "")
    return [posixpath.normpath(x) for x in raw.split(os.pathsep) if x.strip().startswith("/")]


def is_protected(target, include_cwd=True):
    """True for /, a system or data root (or anything under it), a home directory itself, ~, . and .."""
    t = target.strip()
    if not t or sh.SUBST in t:
        return False
    if t in (".", "..", "./", "../", "./*", "../*", "./.*"):
        return include_cwd
    for hw in HOME_WORDS:
        if t == hw or t in (hw + "/", hw + "/*", hw + "/.*"):
            return True
        if t.startswith(hw + "/"):
            return False
    if t.startswith("~"):                      # ~user is another person's home
        return "/" not in t.rstrip("/")
    if not t.startswith("/"):
        return False
    norm = posixpath.normpath(t)
    if norm.startswith("//"):
        norm = "/" + norm.lstrip("/")
    if norm == "/" or norm.startswith("/*") or norm == "/.":
        return True
    for p in extra_protected():
        if norm == p or norm.startswith(p.rstrip("/") + "/"):
            return True
    if any(norm == s or norm.startswith(s + "/") for s in SAFE_UNDER):
        return False
    parts = norm.strip("/").split("/")
    top = parts[0].lower()
    if top in HOME_ROOTS:
        return len(parts) <= 2
    return top in SYSTEM_ROOTS


def is_block_device(path):
    if not path.startswith("/dev/"):
        return False
    rest = path[5:]
    return bool(rest) and rest.split("/")[0] not in DEV_SAFE and not rest.startswith(("fd/", "pts/", "shm/"))


def _flags(args):
    """Short-option letters and long options among args (before a bare --)."""
    short, long_ = set(), set()
    for a in args:
        if a == "--":
            break
        if a.startswith("--"):
            long_.add(a.split("=", 1)[0])
        elif a.startswith("-") and len(a) > 1:
            short.update(a[1:])
    return short, long_


def _operands(args):
    out, after = [], False
    for a in args:
        if after or not a.startswith("-") or a == "-":
            out.append(a)
        elif a == "--":
            after = True
    return out


# -- per-command rules ---------------------------------------------------------------------------------------------
def check_command(cmd):
    core = cmd.core
    writes = [t for op, t in cmd.redirects if op in (">", ">>", ">|", "&>", "&>>", "<>")]
    if any(is_mode_file(t) for t in writes) or (
            core and sh.name_of(core[0]) in MODE_FILE_WRITERS
            and any(is_mode_file(a.split("=", 1)[-1]) for a in core[1:])):
        return "gate.tamper", ""
    for target in writes:
        if is_block_device(target):
            return "disk.raw_write", target
    if core:
        name, args = sh.name_of(core[0]), core[1:]
        for rule in (_rm, _find, _perm, _disk, _git, _docker, _service, _firewall, _deploy, _power):
            hit = rule(name, args)
            if hit:
                return hit
        if name not in DATA_COMMANDS:
            for a in args:
                for piece in (a, a.split("=", 1)[-1]):
                    if is_secret_path(piece):
                        return "secret.path", piece
    for _op, target in cmd.redirects:
        if is_secret_path(target):
            return "secret.path", target
    return None


def _rm(name, args):
    if name != "rm":
        return None
    short, long_ = _flags(args)
    if "--no-preserve-root" in long_:
        return "fs.rm_no_preserve_root", ""
    if not ({"r", "R"} & short or "--recursive" in long_):
        return None
    for t in _operands(args):
        if is_protected(t):
            return "fs.rm_protected", t
    return None


def _find(name, args):
    if name != "find" or "-delete" not in args:
        return None
    for a in args:
        if a.startswith(("-", "(", "!")):
            break
        if is_protected(a, include_cwd=False):
            return "fs.find_delete_protected", a
    return None


def _perm(name, args):
    if name not in ("chmod", "chown", "chgrp", "setfacl"):
        return None
    short, long_ = _flags(args)
    if "R" not in short and "--recursive" not in long_:
        return None
    for t in _operands(args):
        if is_protected(t, include_cwd=False):
            return "fs.recursive_perm_protected", t
    return None


def _disk(name, args):
    if name.startswith("mkfs") or name in ("mke2fs", "mkswap", "wipefs", "blkdiscard", "sfdisk", "pvremove",
                                           "vgremove", "lvremove"):
        return "disk.format", name
    if name == "cryptsetup" and ("luksFormat" in args or "erase" in args):
        return "disk.format", name
    if name in ("sgdisk", "gdisk") and any(a in ("-z", "-Z", "-o", "--zap", "--zap-all", "--clear") for a in args):
        return "disk.format", name
    if name == "parted" and any(a in ("mklabel", "rm", "mkpart", "resizepart") for a in args):
        return "disk.format", name
    if name == "dd":
        for a in args:
            if a.startswith("of=") and is_block_device(a[3:]):
                return "disk.raw_write", a[3:]
    if name in ("shred", "badblocks") and any(is_block_device(a) for a in args):
        return "disk.raw_write", name
    if name == "zfs" and args[:1] == ["destroy"]:
        return "disk.zfs_destroy", ""
    if name == "zpool" and args[:1] and args[0] in ("destroy", "labelclear"):
        return "disk.zfs_destroy", ""
    return None


def _git(name, args):
    if name != "git":
        return None
    j = 0
    while j < len(args) and args[j].startswith("-"):
        j += 2 if args[j] in ("-C", "-c", "--git-dir", "--work-tree", "--namespace", "--exec-path") else 1
    if j >= len(args):
        return None
    sub, rest = args[j], args[j + 1:]
    short, long_ = _flags(rest)
    ops = _operands(rest)
    if sub == "push":
        if ("f" in short or long_ & {"--force", "--force-with-lease", "--mirror"}
                or any(o.startswith("+") for o in ops[1:])):
            return "git.force_push", ""
        if "d" in short or "--delete" in long_ or any(o.startswith(":") for o in ops[1:]):
            return "git.remote_delete", ""
    elif sub == "reset" and "--hard" in long_:
        return "git.reset_hard", ""
    elif sub == "clean" and ("f" in short or "--force" in long_) and not ("n" in short or "--dry-run" in long_):
        return "git.clean_force", ""
    elif sub in ("filter-branch", "filter-repo"):
        return "git.history_rewrite", ""
    elif sub == "reflog" and rest[:1] and rest[0] in ("expire", "delete"):
        return "git.history_rewrite", ""
    elif sub in ("checkout", "restore") and ("." in ops or ("f" in short and sub == "checkout")
                                               or "--force" in long_):
        return "git.discard_changes", ""
    elif sub == "branch" and ("D" in short or ({"d"} & short or "--delete" in long_)
                              and ("f" in short or "--force" in long_)):
        return "git.branch_force_delete", ""
    elif sub == "stash" and rest[:1] and rest[0] in ("drop", "clear"):
        return "git.stash_drop", ""
    return None


def _docker(name, args):
    if name not in ("docker", "podman"):
        return None
    if args[:2] in (["system", "prune"], ["volume", "prune"], ["volume", "rm"]):
        return "docker.data_loss", ""
    return None


SYSTEMCTL_MUTATING = {"start", "stop", "restart", "reload", "try-restart", "reload-or-restart",
                      "try-reload-or-restart", "enable", "disable", "mask", "unmask", "kill", "isolate",
                      "set-default", "set-property", "edit", "revert", "link", "preset", "preset-all"}
SYSTEMCTL_POWER = {"reboot", "poweroff", "halt", "kexec", "soft-reboot", "suspend", "hibernate", "rescue",
                   "emergency"}


def _service(name, args):
    if name == "systemctl":
        if "--user" in args:
            return None
        ops = _operands(args)
        verb = ops[0] if ops else ""
        if verb in SYSTEMCTL_POWER:
            return "prod.power", verb
        if verb in SYSTEMCTL_MUTATING:
            return "prod.service", verb
    if name == "service":
        ops = _operands(args)
        if len(ops) >= 2 and ops[1] in ("start", "stop", "restart", "reload", "force-reload"):
            return "prod.service", ops[1]
    if name == "launchctl" and args[:1] and args[0] in ("unload", "bootout", "stop", "kickstart", "disable",
                                                        "remove", "load", "bootstrap"):
        return "prod.service", args[0]
    if name in ("sc", "sc.exe") and args[:1] and args[0].lower() in ("stop", "start", "delete", "config", "create"):
        return "prod.service", args[0]
    if name == "net" and args[:1] and args[0].lower() in ("stop", "start"):
        return "prod.service", args[0]
    if name in ("stop-service", "restart-service", "start-service", "set-service", "remove-service"):
        return "prod.service", name
    return None


def _firewall(name, args):
    if name == "ufw":
        ops = _operands(args)
        if "--dry-run" in args or not ops or ops[0] in ("status", "show", "version", "app", "help"):
            return None
        return "prod.firewall", ops[0]
    if name in ("iptables", "ip6tables", "iptables-legacy", "ip6tables-legacy", "iptables-nft", "ip6tables-nft",
                "ebtables", "arptables"):
        mutating = {"-A", "-D", "-I", "-R", "-F", "-X", "-P", "-N", "-E", "-Z", "--append", "--delete", "--insert",
                    "--replace", "--flush", "--delete-chain", "--policy", "--new-chain", "--rename-chain", "--zero"}
        if any(a in mutating for a in args):
            return "prod.firewall", name
        return None
    if name in ("iptables-restore", "ip6tables-restore", "iptables-legacy-restore", "ip6tables-legacy-restore"):
        return "prod.firewall", name
    if name == "nft":
        ops = _operands([a for a in args if a not in ("-a", "-e", "-j", "-n", "-s", "-t", "-c", "-y")])
        if "-f" in args or "--file" in args or (ops and ops[0] in ("add", "create", "insert", "replace", "delete",
                                                                  "destroy", "flush", "reset", "rename")):
            return "prod.firewall", name
        return None
    if name == "firewall-cmd":
        prefixes = ("--add", "--remove", "--set", "--change", "--reload", "--complete-reload",
                    "--runtime-to-permanent", "--new", "--delete", "--panic-on", "--lockdown-on", "--reset")
        if any(a.startswith(prefixes) for a in args):
            return "prod.firewall", name
        return None
    if name in ("netsh", "netsh.exe") and "advfirewall" in [a.lower() for a in args]:
        if any(a.lower() in ("set", "add", "delete", "reset", "import") for a in args):
            return "prod.firewall", name
    if name in ("new-netfirewallrule", "set-netfirewallrule", "remove-netfirewallrule", "disable-netfirewallrule",
                "enable-netfirewallrule", "set-netfirewallprofile"):
        return "prod.firewall", name
    return None


def _deploy(name, args):
    ops = _operands(args)
    first = ops[0] if ops else ""
    if name == "vercel" and ({"--prod", "--production"} & set(args) or first in ("promote", "rollback", "remove",
                                                                                  "rm")):
        return "prod.deploy", "vercel"
    if name == "netlify" and first == "deploy" and "--prod" in args:
        return "prod.deploy", "netlify"
    if name == "wrangler" and (first in ("deploy", "publish", "delete", "rollback")
                               or ops[:2] in (["versions", "deploy"], ["pages", "deploy"])):
        return "prod.deploy", "wrangler"
    if name in ("fly", "flyctl") and first in ("deploy", "destroy", "scale", "apps"):
        return "prod.deploy", name
    if name in ("kubectl", "oc") and first in ("apply", "create", "delete", "replace", "patch", "edit", "scale",
                                               "drain", "cordon", "uncordon", "taint", "set", "autoscale", "expose",
                                               "run", "label", "annotate") \
            or name in ("kubectl", "oc") and first == "rollout" and ops[1:2] not in (["status"], ["history"]):
        return "prod.deploy", name
    if name == "helm" and first in ("install", "upgrade", "uninstall", "delete", "rollback"):
        return "prod.deploy", name
    if name in ("terraform", "tofu", "terragrunt") and first in ("apply", "destroy", "import", "taint", "untaint",
                                                                 "force-unlock") \
            or name in ("terraform", "tofu") and ops[:2] in (["state", "rm"], ["state", "mv"], ["state", "push"]):
        return "prod.deploy", name
    if name == "pulumi" and first in ("up", "update", "destroy", "import"):
        return "prod.deploy", name
    if name == "gh" and (ops[:2] in (["pr", "merge"], ["release", "create"], ["release", "delete"],
                                     ["repo", "delete"], ["repo", "archive"])):
        return "prod.deploy", "gh"
    if "--dry-run" in args:
        return None
    if name in ("npm", "pnpm", "yarn", "bun") and "publish" in ops[:2]:
        return "prod.deploy", name
    if (name, first) in (("twine", "upload"), ("cargo", "publish"), ("gem", "push"), ("poetry", "publish"),
                         ("uv", "publish")):
        return "prod.deploy", name
    return None


def _power(name, args):
    if name in ("shutdown", "reboot", "poweroff", "halt", "restart-computer", "stop-computer"):
        return "prod.power", name
    if name in ("init", "telinit") and args[:1] and args[0] in ("0", "6"):
        return "prod.power", name
    return None
