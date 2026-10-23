"""Shell parser: which argv lists would actually EXECUTE (quotes, heredocs, substitutions, nested shells)."""
from niyantrak.gate.shell import executed


def argvs(script):
    return [c.argv for c in executed(script)]


def test_simple_and_operators():
    assert argvs("a 1 && b 2 | c; d &") == [["a", "1"], ["b", "2"], ["c"], ["d"]]


def test_quotes_are_removed_and_kept_as_one_word():
    assert argvs("git commit -m 'rm -rf /' --amend") == [["git", "commit", "-m", "rm -rf /", "--amend"]]
    assert argvs('echo "a $HOME b"') == [["echo", "a $HOME b"]]


def test_heredoc_body_is_data_not_commands():
    cmds = executed("cat <<'EOF' > f\nrm -rf /\nEOF\nls")
    assert [c.argv for c in cmds] == [["cat"], ["ls"]]
    assert cmds[0].stdin == "rm -rf /\n"
    assert cmds[0].redirects == [(">", "f")]


def test_command_substitution_runs():
    assert argvs("echo $(whoami) `id`") == [["whoami"], ["id"], ["echo", "\x00", "\x00"]]


def test_nested_shells_are_unwrapped():
    assert ["rm", "-rf", "/"] in argvs("sudo bash -c 'rm -rf /'")
    assert ["rm", "-rf", "/"] in argvs("echo 'rm -rf /' | sh")
    assert ["rm", "-rf", "/"] in argvs("eval 'rm -rf /'")


def test_assignments_and_keywords_are_skipped():
    assert argvs("FOO=1 BAR=2 make all") == [["make", "all"]]
    assert argvs("if x; then y; else z; fi") == [["x"], ["y"], ["z"]]
    assert argvs("for f in a b; do rm $f; done") == [["rm", "$f"]]


def test_comments_ignored():
    assert argvs("# rm -rf /\nls # x") == [["ls"]]
