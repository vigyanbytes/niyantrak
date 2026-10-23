"""Which commands in a shell string would actually EXECUTE.

A plain pattern match over the raw string blocks text that only *mentions* a command (a commit message, an echo, a
heredoc that writes a runbook). This module tokenises the string the way a POSIX shell would -- quotes, escapes,
comments, operators, redirections, heredocs, here-strings, command and process substitution -- and returns the simple
commands that run, with quotes removed. Data stays data:

* arguments of a command (``git commit -m "rm -rf /"``, ``echo 'git push --force'``) are words, not commands;
* a heredoc body is stdin for its command, not script -- unless that command is a shell (``bash <<EOF``) or an
  unquoted delimiter lets ``$(...)`` inside the body run;

while real execution is followed: ``$(...)``, backticks, ``<(...)``, ``bash -c``/``sh -c``/``su -c``, ``eval``,
``ssh host cmd``, ``find -exec``, a shell reading a heredoc/here-string, and ``echo ... | sh``. Wrappers such as
``sudo``, ``env``, ``nohup``, ``timeout`` and ``xargs`` are stripped to reach the real program (``Cmd.core``).

Limits (documented, not hidden): a script file's or interpreter's own contents (``python -c``, ``./deploy.sh``) and
``curl ... | sh`` are opaque; variables are not expanded. This is a guard against accidents and the obvious, not a
sandbox. Nesting deeper than ``MAX_DEPTH`` raises ``TooDeep`` so the caller can fail closed.
"""
import posixpath
import re

MAX_DEPTH = 8
SUBST = "\x00"          # placeholder for the (unknown) output of a substitution inside a word

SHELLS = {"sh", "bash", "zsh", "dash", "ksh", "ash", "mksh", "fish", "busybox", "rbash"}
KEYWORDS = {"if", "then", "else", "elif", "fi", "do", "done", "while", "until", "!", "{", "}", "esac", "in", "[[", "]]"}
NON_EXEC_HEADS = {"for", "select", "case", "function"}
ASSIGN_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*(\[[^\]]*\])?\+?=")

# wrapper -> (options that take a value, number of positional args before the wrapped command)
PREFIXES = {
    "sudo": ({"-u", "-g", "-h", "-p", "-C", "-D", "-r", "-t", "-U", "-T", "--user", "--group", "--host", "--prompt",
              "--chdir", "--role", "--type", "--other-user", "--close-from", "--command-timeout"}, 0),
    "doas": ({"-u", "-C"}, 0),
    "env": ({"-u", "-C", "--unset", "--chdir"}, 0),
    "nohup": (set(), 0), "command": (set(), 0), "builtin": (set(), 0), "exec": ({"-a"}, 0),
    "time": ({"-f", "-o", "--format", "--output"}, 0), "nice": ({"-n", "--adjustment"}, 0),
    "ionice": ({"-c", "-n", "-p", "-P", "-u", "--class", "--classdata"}, 0),
    "timeout": ({"-s", "-k", "--signal", "--kill-after"}, 1), "stdbuf": ({"-i", "-o", "-e"}, 0),
    "setsid": (set(), 0), "chrt": (set(), 1), "taskset": (set(), 1), "unbuffer": (set(), 0),
    "chroot": ({"--userspec", "--groups"}, 1), "runuser": ({"-u", "-g", "-G", "--user", "--group"}, 0),
    "xargs": ({"-a", "-d", "-E", "-e", "-I", "-i", "-L", "-l", "-n", "-P", "-s", "--arg-file", "--delimiter",
               "--max-args", "--max-procs", "--max-chars", "--max-lines", "--replace", "--process-slot-var"}, 0),
    "flock": ({"-w", "-E", "--timeout", "--conflict-exit-code"}, 1), "caffeinate": (set(), 0),
    "systemd-run": ({"-u", "-p", "-E", "--unit", "--property", "--setenv", "--uid", "--gid", "--slice"}, 0),
}
SSH_ARG_OPTS = set("bBcDEeFIiJLlmOoPpQRSWw")


class TooDeep(Exception):
    """Nesting (substitutions, shells running shells) beyond MAX_DEPTH: callers fail closed."""


class Cmd:
    """One simple command that would run: argv after quote removal, redirections, stdin data, pipe source."""

    def __init__(self, argv=None):
        self.argv = list(argv or [])
        self.redirects = []        # [(op, target)]
        self.stdin = None          # heredoc body or here-string, when known
        self.prev = None           # the command piping into this one
        self.skip = False          # head word of for/case/select: its words are not a command
        self.expanded = False
        self.opaque = False        # runs something this parser cannot see (a shell reading an unknown stdin)

    @property
    def core(self):
        return strip_prefixes(self.argv)

    def __repr__(self):
        return f"Cmd({self.argv!r})"


def name_of(word):
    return posixpath.basename(word.replace("\\", "/")).lower()


def strip_prefixes(argv):
    i, n = 0, len(argv)
    while i < n:
        name = name_of(argv[i])
        if name not in PREFIXES:
            break
        with_arg, positional = PREFIXES[name]
        i += 1
        while i < n:
            a = argv[i]
            if a == "--":
                i += 1
                break
            if name == "env" and ASSIGN_RE.match(a):
                i += 1
            elif a.startswith("-") and len(a) > 1:
                i += 2 if (a in with_arg and "=" not in a) else 1
            else:
                break
        i += positional
    return argv[i:]


class _Parser:
    def __init__(self, script, depth):
        if depth > MAX_DEPTH:
            raise TooDeep()
        self.s, self.n, self.depth = script, len(script), depth
        self.out = []
        self.cur = Cmd()
        self.buf, self.in_word, self.quoted, self.split = [], False, False, False
        self.redir_op = None
        self.heredocs = []         # pending (cmd, delimiter, strip_tabs, quoted)
        self.pipe_prev = None

    # -- substitutions -------------------------------------------------------------------------------------------
    def _subst(self, inner, in_dq=False):
        """Run a substitution; put its output in the word when it is a known data producer, else SUBST.

        `$(echo rm -rf /)` really produces "rm -rf /", so `bash -c "$(echo rm -rf /)"` must be judged on that text.
        Unquoted, the output is word-split like the shell does (so it can become a command)."""
        cmds = executed(inner, self.depth + 1)
        self.out.extend(cmds)
        text = output_of(cmds[0]) if len(cmds) == 1 else None
        if text is None:
            self.buf.append(SUBST)
        else:
            self.buf.append(text.rstrip("\n"))
            if not in_dq:
                self.split = True
        self.in_word = True

    def _match_paren(self, i):
        """Index of the ')' closing a '(' that was just before i (quote-aware)."""
        s, depth = self.s, 1
        while i < self.n:
            c = s[i]
            if c == "\\":
                i += 2
                continue
            if c == "'":
                j = s.find("'", i + 1)
                i = self.n if j < 0 else j + 1
                continue
            if c == '"':
                i = self._skip_dq(i + 1)
                continue
            if c == "(":
                depth += 1
            elif c == ")":
                depth -= 1
                if depth == 0:
                    return i
            i += 1
        return self.n

    def _skip_dq(self, i):
        while i < self.n:
            if self.s[i] == "\\":
                i += 2
                continue
            if self.s[i] == '"':
                return i + 1
            if self.s.startswith("$(", i):
                i = self._match_paren(i + 2) + 1
                continue
            i += 1
        return self.n

    def _backtick(self, i):
        """i is just after an opening backtick; returns (inner, index after the closing one)."""
        j = i
        while j < self.n and self.s[j] != "`":
            j += 2 if self.s[j] == "\\" else 1
        inner = self.s[i:j].replace("\\`", "`").replace("\\$", "$").replace("\\\\", "\\")
        return inner, j + 1

    def _run_only(self, inner):
        self.out.extend(executed(inner, self.depth + 1))

    def _dollar(self, i, in_dq=False):
        """At '$': handles $( ) and $(( )). Returns the new index, or None for a plain '$'."""
        s = self.s
        if s.startswith("$((", i):
            j = self._match_paren(i + 2)
            self.buf.append(s[i:j + 1])
            self.in_word = True
            return j + 1
        if s.startswith("$(", i):
            j = self._match_paren(i + 2)
            self._subst(s[i + 2:j], in_dq)
            return j + 1
        return None

    # -- words and commands --------------------------------------------------------------------------------------
    def _end_word(self):
        if not self.in_word:
            return
        word, quoted, split = "".join(self.buf), self.quoted, self.split
        self.buf, self.in_word, self.quoted, self.split = [], False, False, False
        if self.redir_op:
            op, self.redir_op = self.redir_op, None
            if op in ("<<", "<<-"):
                self.heredocs.append((self.cur, word, op == "<<-", quoted))
            elif op == "<<<":
                self.cur.stdin = word + "\n"
            else:
                self.cur.redirects.append((op, word))
            return
        if split and not quoted:                # unquoted substitution output is word-split by the shell
            for piece in word.split():
                self._add_word(piece, False)
            return
        self._add_word(word, quoted)

    def _add_word(self, word, quoted):
        if not self.cur.argv and not quoted:
            if word in KEYWORDS or word in ("(", ")"):
                return
            if word in NON_EXEC_HEADS:
                self.cur.skip = True
        if not self.cur.argv and ASSIGN_RE.match(word):
            return
        self.cur.argv.append(word)

    def _end_command(self, pipe=False):
        self._end_word()
        cmd = self.cur
        self.cur = Cmd()
        if cmd.argv and not cmd.skip:
            cmd.prev = self.pipe_prev
            self.out.append(cmd)
            self.pipe_prev = cmd if pipe else None
        else:
            self.pipe_prev = None

    def _read_heredocs(self, i):
        """i is just after a newline: consume pending heredoc bodies, return the index after them."""
        s = self.s
        for cmd, delim, strip, quoted in self.heredocs:
            lines = []
            while i < self.n:
                j = s.find("\n", i)
                line = s[i:] if j < 0 else s[i:j]
                i = self.n if j < 0 else j + 1
                check = line.lstrip("\t") if strip else line
                if check == delim:
                    break
                lines.append(check if strip else line)
            body = "".join(x + "\n" for x in lines)
            cmd.stdin = body
            if not quoted:
                self._expansions(body)
        self.heredocs = []
        return i

    def _expansions(self, text):
        """Run the $( ) and backtick substitutions of an unquoted-delimiter heredoc body."""
        sub = _Parser(text, self.depth)
        i = 0
        while i < sub.n:
            c = text[i]
            if c == "\\":
                i += 2
            elif text.startswith("$(", i) and not text.startswith("$((", i):
                j = sub._match_paren(i + 2)
                self._run_only(text[i + 2:j])
                i = j + 1
            elif c == "`":
                inner, i = sub._backtick(i + 1)
                self._run_only(inner)
            else:
                i += 1

    def run(self):
        s, i = self.s, 0
        while i < self.n:
            c = s[i]
            nxt = s[i + 1] if i + 1 < self.n else ""
            if c == "\\":
                if nxt == "\n":
                    i += 2
                    continue
                if nxt:
                    self.buf.append(nxt)
                self.in_word = self.quoted = True
                i += 2
                continue
            if c == "'":
                j = s.find("'", i + 1)
                j = self.n if j < 0 else j
                self.buf.append(s[i + 1:j])
                self.in_word = self.quoted = True
                i = j + 1
                continue
            if c == '"':
                i = self._double_quoted(i + 1)
                continue
            if c == "$":
                if nxt == "'":
                    i = self._ansi_c(i + 2)
                    continue
                j = self._dollar(i)
                if j is not None:
                    i = j
                    continue
            if c == "`":
                inner, i = self._backtick(i + 1)
                self._subst(inner)
                continue
            if c in "<>" and nxt == "(" and not self.in_word:
                j = self._match_paren(i + 2)
                self._run_only(s[i + 2:j])          # process substitution: the word is a file name
                self.buf.append(SUBST)
                self.in_word = True
                i = j + 1
                continue
            if c == "#" and not self.in_word:
                j = s.find("\n", i)
                i = self.n if j < 0 else j
                continue
            if c in " \t\r":
                self._end_word()
                i += 1
                continue
            if c == "\n":
                self._end_command()
                i = self._read_heredocs(i + 1) if self.heredocs else i + 1
                continue
            if c == "&" and nxt == ">":
                self._end_word()
                op = "&>>" if s.startswith("&>>", i) else "&>"
                self.redir_op = op
                i += len(op)
                continue
            if c in ";&|()":
                if c == "|":
                    if nxt == "|":
                        self._end_command()
                        i += 2
                    else:
                        self._end_command(pipe=True)
                        i += 2 if nxt == "&" else 1
                elif c == "&":
                    self._end_command()
                    i += 2 if nxt == "&" else 1
                elif c == ";":
                    self._end_command()
                    i += 2 if nxt in ";&" else 1
                else:
                    self._end_command()
                    i += 1
                continue
            if c in "<>":
                if self.in_word and self.buf and "".join(self.buf).isdigit() and not self.quoted:
                    self.buf, self.in_word = [], False          # file-descriptor number, e.g. 2>
                else:
                    self._end_word()
                for op in ("<<<", "<<-", "<<", "<>", "<&", ">>", ">&", ">|", "<", ">"):
                    if s.startswith(op, i):
                        break
                self.redir_op = op
                i += len(op)
                continue
            self.buf.append(c)
            self.in_word = True
            i += 1
        self._end_command()
        for cmd, _delim, _strip, _quoted in self.heredocs:      # unterminated heredoc at end of input
            cmd.stdin = cmd.stdin or ""
        return self.out

    def _double_quoted(self, i):
        s = self.s
        self.in_word = self.quoted = True
        while i < self.n:
            c = s[i]
            if c == "\\" and i + 1 < self.n:
                if s[i + 1] in '$`"\\':
                    self.buf.append(s[i + 1])
                elif s[i + 1] != "\n":
                    self.buf.append(c + s[i + 1])
                i += 2
                continue
            if c == '"':
                return i + 1
            if c == "$":
                j = self._dollar(i, in_dq=True)
                if j is not None:
                    i = j
                    continue
            if c == "`":
                inner, i = self._backtick(i + 1)
                self._subst(inner, in_dq=True)
                continue
            self.buf.append(c)
            i += 1
        return self.n

    def _ansi_c(self, i):
        s, esc = self.s, {"n": "\n", "t": "\t", "\\": "\\", "'": "'", '"': '"', "r": "\r", "e": "\x1b", "a": "\a"}
        self.in_word = self.quoted = True
        while i < self.n:
            c = s[i]
            if c == "\\" and i + 1 < self.n:
                self.buf.append(esc.get(s[i + 1], "\\" + s[i + 1]))
                i += 2
                continue
            if c == "'":
                return i + 1
            self.buf.append(c)
            i += 1
        return self.n


def parse(script, depth=0):
    """Simple commands of one script level (substitutions already followed), in execution order."""
    return _Parser(script, depth).run()


# -- following execution into other layers ----------------------------------------------------------------------
def output_of(cmd):
    """Best-effort text a data producer writes to stdout (echo/printf/cat of a heredoc), else None."""
    if cmd is None:
        return None
    core = cmd.core
    if not core:
        return None
    name, args = name_of(core[0]), core[1:]
    if name == "echo":
        while args and re.fullmatch(r"-[neE]+", args[0]):
            args = args[1:]
        return " ".join(args).replace("\\n", "\n") + "\n"
    if name == "printf":
        if not args:
            return None
        text = "\n".join(args[1:]) if (len(args) > 1 and "%" in args[0]) else args[0]
        return text.replace("\\n", "\n") + "\n"
    if name == "cat" and len(core) == 1:
        return cmd.stdin if cmd.stdin is not None else output_of(cmd.prev)
    return None


def _stdin_script(cmd):
    if cmd.stdin is not None:
        return cmd.stdin
    return output_of(cmd.prev)


def nested(cmd):
    """(scripts, argv-lists) that this command itself runs."""
    core = cmd.core
    if not core:
        return [], []
    name = name_of(core[0])
    if name == "busybox" and len(core) > 1 and name_of(core[1]) in SHELLS:
        core, name = core[1:], name_of(core[1])
    if name in SHELLS:
        j, has_c = 1, False
        while j < len(core):
            a = core[j]
            if a == "--":
                j += 1
                break
            if a[:1] in "-+" and len(a) > 1:
                if not a.startswith("--") and "c" in a[1:]:
                    has_c = True
                j += 2 if a in ("-o", "+o", "-O", "+O", "--rcfile", "--init-file") else 1
                continue
            break
        if has_c:
            return ([core[j]] if j < len(core) else []), []
        if j < len(core):
            return [], []                       # runs a script file: contents not visible here
        script = _stdin_script(cmd)
        if script is None:
            cmd.opaque = True
            return [], []
        return [script], []
    if name == "su":
        for k, a in enumerate(core[1:-1], start=1):
            if a in ("-c", "--command"):
                return [core[k + 1]], []
            if a.startswith("--command="):
                return [a.split("=", 1)[1]], []
        return [], []
    if name == "eval":
        return [" ".join(core[1:])], []
    if name == "watch":
        j = 1
        while j < len(core) and core[j].startswith("-"):
            j += 2 if core[j] in ("-n", "-d", "--interval", "-q") else 1
        return ([" ".join(core[j:])] if j < len(core) else []), []
    if name == "ssh":
        j = 1
        while j < len(core) and core[j].startswith("-") and len(core[j]) > 1:
            a = core[j]
            j += 2 if (len(a) == 2 and a[1] in SSH_ARG_OPTS) else 1
        rest = core[j + 1:]
        if rest:
            return [" ".join(rest)], []
        script = _stdin_script(cmd)
        return ([script] if script is not None else []), []
    if name == "find":
        found, j = [], 1
        while j < len(core):
            if core[j] in ("-exec", "-execdir", "-ok", "-okdir"):
                k = j + 1
                while k < len(core) and core[k] not in (";", "+"):
                    k += 1
                if k > j + 1:
                    found.append(core[j + 1:k])
                j = k + 1
                continue
            j += 1
        return [], found
    return [], []


def executed(script, depth=0):
    """Every simple command that would run for `script`, following nested execution."""
    result = []
    for cmd in parse(script, depth):
        if cmd.expanded:
            result.append(cmd)
            continue
        result.extend(_expand(cmd, depth))
    return result


def _expand(cmd, depth):
    cmd.expanded = True
    out = [cmd]
    scripts, argvs = nested(cmd)
    for sc in scripts:
        out.extend(executed(sc, depth + 1))
    for argv in argvs:
        if depth + 1 > MAX_DEPTH:
            raise TooDeep()
        out.extend(_expand(Cmd(argv), depth + 1))
    return out
