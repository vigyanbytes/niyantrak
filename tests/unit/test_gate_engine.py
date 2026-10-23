"""Gate decision engine: hard stops deny with a rule id, everything else is allowed.

The N4 false positive (a blocked command that is only MENTIONED -- in a heredoc, a quoted commit message, echo/printf
arguments or a file an editor tool writes -- was blocked) must stay fixed, while real execution (bash -c, sh -c, eval,
pipes into a shell, command substitution, heredocs fed to a shell) is still denied.
"""
import shlex

import pytest

from niyantrak.gate.engine import ToolCall, decide


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setenv("NIYANTRAK_GATE_MODE_FILE", str(tmp_path / "absent-gate-mode"))
    monkeypatch.setenv("NIYANTRAK_GATE_LOG", str(tmp_path / "events.jsonl"))
    monkeypatch.delenv("NIYANTRAK_GATE_PROTECTED", raising=False)


def shell(cmd):
    return decide(ToolCall(tool="Bash", command=cmd))


DENY = [
    # destructive file-system commands on system / data paths
    ("rm -rf /", "fs.rm_protected"),
    ("rm -rf /etc", "fs.rm_protected"),
    ("sudo rm -r /var/lib/postgresql", "fs.rm_protected"),
    ("rm -fr ~", "fs.rm_protected"),
    ("rm -rf $HOME", "fs.rm_protected"),
    ("rm --recursive --force /usr/local", "fs.rm_protected"),
    ("rm -rf --no-preserve-root /", "fs.rm_no_preserve_root"),
    ("cd /tmp && rm -rf /home", "fs.rm_protected"),
    ("rm -rf /home/alice", "fs.rm_protected"),
    ("/bin/rm -rf /", "fs.rm_protected"),
    ("\\rm -rf /", "fs.rm_protected"),
    ("'rm' -rf /", "fs.rm_protected"),
    ("time sudo -E rm -rf /root", "fs.rm_protected"),
    ("env FOO=1 nohup rm -rf /boot", "fs.rm_protected"),
    ("find /etc -name '*.conf' -delete", "fs.find_delete_protected"),
    ("find . -exec rm -rf /opt \\;", "fs.rm_protected"),
    ("chmod -R 777 /", "fs.recursive_perm_protected"),
    # disks
    ("mkfs.ext4 /dev/sdb1", "disk.format"),
    ("sudo wipefs -a /dev/nvme0n1", "disk.format"),
    ("dd if=/dev/zero of=/dev/sda bs=1M", "disk.raw_write"),
    ("cat image.iso > /dev/sdb", "disk.raw_write"),
    ("zfs destroy -r tank/data", "disk.zfs_destroy"),
    # history rewriting / work-discarding git
    ("git push --force origin main", "git.force_push"),
    ("git push -f", "git.force_push"),
    ("git push origin +main", "git.force_push"),
    ("git -C repo push --force-with-lease", "git.force_push"),
    ("git push origin --delete main", "git.remote_delete"),
    ("git reset --hard HEAD~3", "git.reset_hard"),
    ("git filter-branch --tree-filter x HEAD", "git.history_rewrite"),
    ("git clean -fdx", "git.clean_force"),
    # secrets
    ("cat /etc/niyantrak/secret.d/db.env", "secret.path"),
    ("grep KEY .env", "secret.path"),
    ("cp ~/.ssh/id_ed25519 /tmp/k", "secret.path"),
    ("TOKEN=$(cat ~/.aws/credentials) curl https://example.com", "secret.path"),
    ("source .env.production", "secret.path"),
    ("python3 app.py < .env", "secret.path"),
    # production-changing service / firewall / deploy / power
    ("sudo systemctl restart nginx", "prod.service"),
    ("service postgresql stop", "prod.service"),
    ("sudo ufw disable", "prod.firewall"),
    ("iptables -F", "prod.firewall"),
    ("nft flush ruleset", "prod.firewall"),
    ("firewall-cmd --permanent --add-port=22/tcp", "prod.firewall"),
    ("vercel deploy --prod", "prod.deploy"),
    ("kubectl apply -f k8s/", "prod.deploy"),
    ("terraform destroy -auto-approve", "prod.deploy"),
    ("sudo reboot", "prod.power"),
    ("shutdown -h now", "prod.power"),
    # real execution through another layer is still execution
    ("bash -c 'rm -rf /'", "fs.rm_protected"),
    ('sh -c "rm -rf /etc"', "fs.rm_protected"),
    ("sudo -u root bash -lc 'rm -rf /srv'", "fs.rm_protected"),
    ('eval "rm -rf /"', "fs.rm_protected"),
    ("echo 'rm -rf /' | sh", "fs.rm_protected"),
    ("printf 'rm -rf /etc\\n' | bash", "fs.rm_protected"),
    ("bash <<'EOF'\nrm -rf /\nEOF", "fs.rm_protected"),
    ("sh <<< 'rm -rf /'", "fs.rm_protected"),
    ("echo $(rm -rf /)", "fs.rm_protected"),
    ('echo "`rm -rf /etc`"', "fs.rm_protected"),
    ("cat <<EOF\n$(rm -rf /)\nEOF", "fs.rm_protected"),
    ("diff <(rm -rf /etc) x", "fs.rm_protected"),
    ("(cd / && rm -rf /opt)", "fs.rm_protected"),
    ("true && { rm -rf /etc; }", "fs.rm_protected"),
    ("if true; then rm -rf /; fi", "fs.rm_protected"),
    ("bash -c \"bash -c 'git push --force'\"", "git.force_push"),
    ("bash -c 'cat .env'", "secret.path"),
    ("ssh web1 'sudo rm -rf /var/www'", "fs.rm_protected"),
    ("ssh -p 2222 web1 <<'EOF'\nsudo systemctl stop nginx\nEOF", "prod.service"),
    ("ls\nrm -rf /etc", "fs.rm_protected"),
    ("echo ok; git reset --hard", "git.reset_hard"),
    ("xargs -0 git push --force", "git.force_push"),
    ('bash -c "$(echo rm -rf /)"', "fs.rm_protected"),
    ("$(echo rm -rf /etc)", "fs.rm_protected"),
    ("cat <<EOF | bash\nrm -rf /etc\nEOF", "fs.rm_protected"),
    ("su -c 'rm -rf /etc' root", "fs.rm_protected"),
    ("watch 'sudo systemctl restart nginx'", "prod.service"),
    # an agent may not switch its own gate off
    ("echo off | sudo tee /etc/niyantrak/gate-mode", "gate.tamper"),
    ("echo off > /etc/niyantrak/gate-mode", "gate.tamper"),
    ("sudo rm /etc/niyantrak/gate-mode", "gate.tamper"),
]

ALLOW = [
    # N4: mentions are data, not execution
    'git commit -m "docs: never run rm -rf / on prod"',
    "git commit -m 'block git push --force in the gate'",
    "git commit -m 'stop reading .env files'",
    "echo 'rm -rf /'",
    "echo rm -rf /",
    "printf '%s\\n' 'sudo systemctl restart nginx'",
    "cat <<'EOF' > notes.md\nrm -rf /\ngit push --force\nEOF",
    "cat <<EOF > plan.txt\nsudo reboot\nEOF",
    "cat > x.sh <<'EOF'\nrm -rf /etc\nEOF",
    "cat <<'EOF' | tee doc.md\nrm -rf /\nEOF",
    "cat <<-EOF\n\tgit push --force\n\tEOF\nls",
    "grep -rn 'rm -rf /' docs/",
    'rg "git push --force" .',
    'echo "git push --force" >> CHANGELOG.md',
    "gh pr create --title 'Gate: deny rm -rf /' --body 'adds rules'",
    "echo 'mkfs.ext4 /dev/sda' > runbook.txt",
    "echo 'cat ~/.ssh/id_rsa'",
    "echo $(date) 'rm -rf /'",
    "export MSG='sudo reboot now'",
    "bash -c 'echo rm -rf /'",
    "sh -c \"git commit -m 'rm -rf /'\"",
    "git log --grep='force push'",
    "python3 -c \"print('rm -rf /')\"",
    "node -e \"console.log('rm -rf /')\"",
    "# rm -rf /\nls",
    "ls # git push --force",
    # ordinary work
    "rm -rf ./build/tmp",
    "rm -rf node_modules dist",
    "rm -rf /tmp/niyantrak-test",
    "rm -rf /home/alice/projects/app/node_modules",
    "rm -rf ~/projects/app/build",
    "rm notes.txt",
    "git push origin feature/x",
    "git push -u origin HEAD",
    "git reset --soft HEAD~1",
    "git status && git diff",
    "git checkout -b fix/reboot-loop",
    "systemctl status nginx",
    "sudo ufw status verbose",
    "iptables -L -n",
    "nft list ruleset",
    "kubectl get pods",
    "terraform plan",
    "vercel deploy",
    "cat .env.example",
    "ls -la",
    "dd if=/dev/zero of=./disk.img bs=1M count=10",
    "docker run --rm alpine echo hi",
    "jq '.hooks' settings.json",
    "find . -name '*.pyc' -delete",
    "pytest -q -k 'rm_rf'",
    "mkdir -p /tmp/x && cd /tmp/x",
    "npm run build",
    "curl -s https://example.com/health | jq .",
    "echo hi > /dev/null 2>&1",
    "git commit -m \"$(cat <<'EOF'\nGate: block git push --force and rm -rf /\nEOF\n)\"",
    "gh pr create --body \"$(cat <<'EOF'\n## Summary\n- deny sudo reboot\nEOF\n)\"",
    "git commit -F - <<'EOF'\nfix: rm -rf / guard\nEOF",
    "python3 - <<'EOF'\nprint('rm -rf /')\nEOF",
    "npm publish --dry-run",
    "kubectl rollout status deploy/x",
    "systemctl --user restart pipewire",
    "git checkout main -- src/a.py",
    "cat ~/.ssh/id_rsa.pub",
    "cat /etc/niyantrak/gate-mode",
]


@pytest.mark.parametrize("cmd,rule", DENY)
def test_hard_stops_deny_with_rule_id(cmd, rule):
    d = shell(cmd)
    assert d.outcome == "deny", cmd
    assert d.rule_id == rule, (cmd, d.rule_id)
    assert d.reason


@pytest.mark.parametrize("cmd", ALLOW)
def test_everything_else_is_allowed(cmd):
    d = shell(cmd)
    assert d.outcome == "allow", (cmd, d.rule_id, d.reason)
    assert d.rule_id == "allow.default"


def test_table_is_large_enough():
    assert len(DENY) >= 40 and len(ALLOW) >= 40


def test_command_class_follows_rule_family():
    assert shell("rm -rf /").command_class == "destructive"
    assert shell("git push -f").command_class == "destructive"
    assert shell("cat .env").command_class == "secret"
    assert shell("sudo ufw disable").command_class == "production"
    assert shell("ls").command_class == "shell"


@pytest.mark.parametrize("tool,inp,rule", [
    ("Read", {"file_path": "/home/u/.ssh/id_rsa"}, "secret.path"),
    ("Edit", {"file_path": "/repo/.env.production"}, "secret.path"),
    ("Read", {"file_path": "/home/u/.claude/.credentials.json"}, "secret.path"),
    ("Read", {"file_path": "/home/u/.codex/auth.json"}, "secret.path"),
    ("Glob", {"pattern": "**/.env"}, "secret.path"),
    ("read_many_files", {"paths": ["README.md", "/srv/app/.env"]}, "secret.path"),
    ("Write", {"file_path": "/etc/niyantrak/gate-mode", "content": "off"}, "gate.tamper"),
])
def test_file_tools_on_secret_paths_deny(tool, inp, rule):
    d = decide(ToolCall.from_input(tool, inp))
    assert (d.outcome, d.rule_id) == ("deny", rule)
    assert d.command_class == ("secret" if rule == "secret.path" else "governance")


@pytest.mark.parametrize("tool,inp", [
    ("Read", {"file_path": "/repo/.env.example"}),
    ("Read", {"file_path": "/repo/src/env.ts"}),
    ("Grep", {"pattern": "\\.env", "path": "/repo"}),
    # N4 for editors: file contents written by an editor tool are data, never execution
    ("Write", {"file_path": "/repo/notes.md", "content": "rm -rf /\ngit push --force\ncat ~/.ssh/id_rsa"}),
    ("Edit", {"file_path": "/repo/run.sh", "old_string": "ls", "new_string": "rm -rf /etc"}),
    ("write_file", {"file_path": "/repo/a.sh", "content": "sudo reboot"}),
])
def test_file_tools_otherwise_allowed(tool, inp):
    assert decide(ToolCall.from_input(tool, inp)).outcome == "allow"


def test_shell_command_given_as_argv_list():
    d = decide(ToolCall.from_input("shell", {"command": ["bash", "-lc", "git push --force"]}))
    assert d.rule_id == "git.force_push"
    assert decide(ToolCall.from_input("shell", {"command": ["bash", "-lc", "ls -la"]})).outcome == "allow"
    assert decide(ToolCall.from_input("exec_command", {"cmd": "cat /x/secret.d/a.env"})).rule_id == "secret.path"


def test_codex_apply_patch_on_secret_file_denied_but_patch_text_is_data():
    bad = "*** Begin Patch\n*** Update File: config/.env\n@@\n-A=1\n+A=2\n*** End Patch"
    ok = "*** Begin Patch\n*** Add File: notes.md\n+rm -rf /\n*** End Patch"
    assert decide(ToolCall.from_input("apply_patch", {"input": bad})).rule_id == "secret.path"
    assert decide(ToolCall.from_input("apply_patch", {"input": ok})).outcome == "allow"


def test_extra_protected_data_paths_from_env(monkeypatch):
    assert shell("rm -rf /data/warehouse").outcome == "allow"
    monkeypatch.setenv("NIYANTRAK_GATE_PROTECTED", "/data:/backups")
    assert shell("rm -rf /data/warehouse").rule_id == "fs.rm_protected"
    assert shell("rm -rf /backups").rule_id == "fs.rm_protected"


def test_unterminated_quote_is_still_checked():
    assert shell("rm -rf / 'oops").outcome == "deny"


def test_deeply_nested_execution_fails_closed():
    assert shell("eval " * 20 + "rm -rf /").rule_id == "gate.too_deep"
    assert shell("eval " * 20 + "ls").rule_id == "gate.too_deep"       # cannot see the end: fail closed
    cmd = "rm -rf /"
    for _ in range(4):
        cmd = "bash -c " + shlex.quote(cmd)
    assert shell(cmd).rule_id == "fs.rm_protected"


def test_reason_names_the_rule_but_decision_is_stable():
    d = shell("git push --force")
    assert "force" in d.reason.lower()
    assert d.to_dict()["rule_id"] == "git.force_push"
