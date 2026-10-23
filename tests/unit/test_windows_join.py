"""windows/join.ps1 — the Windows join agent, tested from Linux.

No PowerShell here (normally): the script is checked statically for its safety properties, its card schema is compared
with card.py, and its node_id hashing is pinned to a value computed by Windows PowerShell 5.1 on a real laptop.
When `pwsh` is on PATH, the same functions are also run for real (dot-sourcing the script loads them without running
the main body).

Manual check of the node_id scheme (Windows PowerShell 5.1.26100, Windows 11 Pro, 2026-10-23), pure computation:
    $u = "4C4C4544-0042-3510-8051-B4C04F4A4A32"; $s = [Security.Cryptography.SHA256]::Create()
    "nyk-" + (-join ($s.ComputeHash([Text.Encoding]::UTF8.GetBytes($u.Trim().ToLowerInvariant())) |
              ForEach-Object { $_.ToString("x2") })).Substring(0,12)          ->  nyk-772dfe876b59
"""
import hashlib
import json
import os
import re
import shutil
import subprocess

import pytest

from niyantrak import card as cardmod

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SCRIPT = os.path.join(ROOT, "windows", "join.ps1")
FIXED_UUID = "4C4C4544-0042-3510-8051-B4C04F4A4A32"
FIXED_NODE_ID = "nyk-772dfe876b59"          # Windows PowerShell 5.1 on dev-laptop, see module docstring
PWSH = shutil.which("pwsh")

MUTATING = ("Add-WindowsCapability", "Set-Service", "Start-Service", "Restart-Service", "Stop-Service", "Set-Acl",
            "New-NetFirewallRule", "Set-NetFirewallRule", "Disable-NetFirewallRule", "Remove-NetFirewallRule",
            "Set-Content", "Add-Content", "Out-File", "New-Item", "Copy-Item", "Move-Item", "Remove-Item",
            "netsh", "icacls", "Invoke-RestMethod", "Invoke-WebRequest", "WriteAllText", "WriteAllBytes",
            "ssh-keygen", "Set-ItemProperty", "New-ItemProperty")


@pytest.fixture(scope="module")
def src():
    with open(SCRIPT, encoding="utf-8-sig") as f:
        return f.read()


def code_lines(text):
    """Lines without comments (block comments <# #> and # to end of line, outside strings — good enough here)."""
    text = re.sub(r"<#.*?#>", lambda m: "\n" * m.group(0).count("\n"), text, flags=re.S)
    out = []
    for line in text.splitlines():
        s, q = [], None
        for ch in line:
            if q:
                s.append(ch)
                if ch == q:
                    q = None
            elif ch in "'\"":
                q = ch
                s.append(ch)
            elif ch == "#":
                break
            else:
                s.append(ch)
        out.append("".join(s))
    return out


def region(src, name):
    m = re.search(rf"#region {name}\n(.*?)#endregion {name}", src, re.S)
    assert m, f"#region {name} missing"
    return m.group(1)


def function_body(src, name):
    m = re.search(rf"function {re.escape(name)}\b[^{{]*\{{", src)
    assert m, f"function {name} missing"
    i, depth = m.end(), 1
    while depth:
        depth += {"{": 1, "}": -1}.get(src[i], 0)
        i += 1
    return src[m.end():i - 1]


def parse_hashtable(text):
    """Keys of a PowerShell `[ordered]@{ k = v; ... }` literal, nested literals as dicts, other values as None."""
    text = text.strip()
    text = re.sub(r"^\[ordered\]", "", text).strip()
    assert text.startswith("@{") and text.endswith("}"), text[:60]
    inner, parts, depth, cur = text[2:-1], [], 0, ""
    for ch in inner:
        if ch in "{([":
            depth += 1
        elif ch in "})]":
            depth -= 1
        if ch in ";\n" and depth == 0:
            parts.append(cur)
            cur = ""
        else:
            cur += ch
    parts.append(cur)
    out = {}
    for p in (p.strip() for p in parts):
        if not p:
            continue
        k, v = (x.strip() for x in p.split("=", 1))
        out[k] = parse_hashtable(v) if re.match(r"^(\[ordered\])?@\{", v) else None
    return out


def keys_tree(d):
    return {k: keys_tree(v) if isinstance(v, dict) else None for k, v in d.items()}


def literal_after(body, marker):
    """The balanced @{ ... } literal that follows `marker` in body."""
    j = body.index("@{", body.index(marker) + len(marker))
    depth, k = 0, j + 1
    while True:
        depth += {"{": 1, "}": -1}.get(body[k], 0)
        k += 1
        if depth == 0:
            return body[j:k]


# ── safety properties ─────────────────────────────────────────────────────────────────────────────────────
def test_script_exists_and_targets_windows_powershell_51(src):
    assert "#Requires -Version 5.1" in src
    assert "Set-StrictMode" in src and "$ErrorActionPreference = 'Stop'" in src


def test_dry_run_is_the_default_and_apply_is_a_switch(src):
    params = re.search(r"param\((.*?)\n\)", src, re.S).group(1)
    assert re.search(r"\[switch\]\$Apply\b", params) and re.search(r"\[switch\]\$PreferIPv4\b", params)
    assert "$Apply = $true" not in src and "$Apply=$true" not in src.replace(" ", "")
    assert "DRY RUN" in src                      # says so when nothing is changed


def test_every_change_goes_through_the_apply_gate(src):
    gate = function_body(src, "Invoke-NykStep")
    lines = [l for l in code_lines(gate) if l.strip()]
    i_check = next(i for i, l in enumerate(lines) if re.search(r"if \(-not \$Apply\)", l))
    i_run = next(i for i, l in enumerate(lines) if "& $Action" in l)
    assert i_check < i_run and "return" in "".join(lines[i_check:i_run])
    actions = region(src, "apply-actions")
    outside = src.replace(actions, "")
    for ln in code_lines(outside):
        for cmd in MUTATING:
            assert not re.search(rf"(?<![\w-]){re.escape(cmd)}(?![\w-])", ln), f"{cmd} outside the apply region: {ln.strip()}"
    # functions of the apply region are only ever called as an Invoke-NykStep action
    for fn in re.findall(r"function (Set-Nyk\w+|Invoke-NykJoinRequest)", actions):
        for ln in code_lines(outside):
            if re.search(rf"\b{fn}\b", ln):
                assert "Invoke-NykStep" in ln or ln.strip().startswith("-Action"), ln


def test_apply_needs_administrator_and_a_supported_windows(src):
    assert "WindowsBuiltInRole]::Administrator" in src
    osb = function_body(src, "Test-NykWindows")
    assert "Win32_OperatingSystem" in osb and "ProductType" in osb and re.search(r"Version.*'10\.", osb)
    main = region(src, "main")
    assert re.search(r"if \(\$Apply -and -not \$isAdmin\)", main)


def test_token_is_never_a_parameter_and_never_written(src):
    params = re.search(r"param\((.*?)\n\)", src, re.S).group(1)
    assert "$Token" not in params, "a -Token parameter ends up in shell history and process listings"
    tb = function_body(src, "Read-NykToken")
    assert "Read-Host" in tb and "-AsSecureString" in tb
    assert "NIYANTRAK_JOIN_TOKEN" in tb and re.search(r"Remove-Item\s+Env:\\?NIYANTRAK_JOIN_TOKEN|\[Environment\]::SetEnvironmentVariable\('NIYANTRAK_JOIN_TOKEN', \$null", tb)
    assert "ZeroFreeBSTR" in tb
    for ln in code_lines(src):
        if re.search(r"\$(token|plainToken)\b", ln, re.I):
            assert not re.search(r"Set-Content|Add-Content|Out-File|WriteAll|Export-|>\s*\S|Write-Host|Write-Output|Start-Transcript", ln), ln
    assert "Start-Transcript" not in src


def test_tls_pin_checked_before_the_token_is_sent(src):
    assert re.search(r"\^https://", src), "plain http must be refused"
    pin = function_body(src, "ConvertTo-NykPin")
    assert "[0-9a-f]{64}" in pin
    jr = function_body(src, "Invoke-NykJoinRequest")
    assert "ServerCertificateValidationCallback" in src and "GetRawCertData" in src
    i_cb = jr.index("NykPin]::Install")
    i_post = jr.index("Invoke-RestMethod")
    assert i_cb < i_post and "NykPin]::Uninstall" in jr[i_post:]
    assert re.search(r"finally\s*\{[^}]*NykPin\]::Uninstall", jr), "callback removed even when the request fails"


def test_sshd_password_login_off_and_config_validated(src):
    s = function_body(src, "Set-NykSshdConfig")
    assert "PasswordAuthentication no" in s and "sshd_config" in s
    assert "-t" in s and "sshd.exe" in s, "config must be validated with sshd -t before restarting"
    assert "niyantrak-bak" in s, "a backup is kept so the change can be undone"


def test_admin_keys_acl_is_system_and_administrators_only(src):
    s = function_body(src, "Set-NykAdminKeysAcl")
    assert "administrators_authorized_keys" in s
    assert "SetAccessRuleProtection($true, $false)" in s
    assert "S-1-5-18" in s and "S-1-5-32-544" in s
    sids = set(re.findall(r"S-1-5-[\d-]+", s))
    assert sids == {"S-1-5-18", "S-1-5-32-544"}, sids
    assert "RemoveAccessRule" in s or "PurgeAccessRules" in s


def test_firewall_allows_ssh_only_from_the_control_node(src):
    s = function_body(src, "Set-NykFirewall")
    assert "New-NetFirewallRule" in s and "-LocalPort 22" in s and "-RemoteAddress" in s and "-Direction Inbound" in s
    assert "OpenSSH-Server-In-TCP" in s           # the wide-open default rule is turned off


def test_ipv6_stays_on(src):
    low = src.lower()
    for bad in ("disabledcomponents", "disable-netadapterbinding", "ms_tcpip6", "set-netipv6protocol"):
        assert bad not in low, bad
    for ln in code_lines(src):
        assert not re.search(r"disable\S*.*ipv6|ipv6.*disable", ln, re.I), ln
    s = function_body(src, "Set-NykPreferIPv4")
    assert "prefixpolicy" in s and "::ffff:0:0/96" in s
    main = region(src, "main")
    assert re.search(r"if \(\$PreferIPv4\)", main) and "Set-NykPreferIPv4" in main


def test_card_is_signed_with_the_host_key_and_node_card_namespace(src):
    s = function_body(src, "Invoke-NykJoinRequest")
    assert "-Y" in s and "sign" in s and "ssh_host_ed25519_key" in src
    assert f"'{cardmod.NAMESPACE}'" in src


# ── card schema parity with card.py ───────────────────────────────────────────────────────────────────────
def test_card_fields_identical_to_card_py(src):
    body = function_body(src, "New-NykCard")
    ps = keys_tree(parse_hashtable(literal_after(body, "$card =")))
    py = keys_tree({k: v if isinstance(v, dict) else None for k, v in cardmod.collect().items()})
    assert ps == py
    assert re.search(r"card_version\s*=\s*" + str(cardmod.CARD_VERSION) + r"\b", body)


def test_gpu_entry_fields_identical_to_card_py(src):
    body = function_body(src, "Get-NykGpu")
    ps = set(parse_hashtable(literal_after(body, "[ordered]")))
    assert ps == {"name", "vram_mb"}                 # card._gpu(): {"name": ..., "vram_mb": int}


def test_node_id_scheme_matches_python(src):
    assert "nyk-" + hashlib.sha256(FIXED_UUID.lower().encode()).hexdigest()[:12] == FIXED_NODE_ID
    s = function_body(src, "Get-NykNodeIdFromString")
    for part in ("ToLowerInvariant()", ".Trim()", "SHA256", "UTF8", "Substring(0, 12)", "'nyk-'", "x2"):
        assert part in s, part
    g = function_body(src, "Get-NykNodeId")
    assert "Win32_ComputerSystemProduct" in g and "MachineGuid" in g and "GetHostName" in g


def test_canonical_json_rules_match_card_bytes(src):
    s = function_body(src, "ConvertTo-NykJson")
    assert "CompareOrdinal" in s or "StringComparer]::Ordinal" in s       # sort_keys over code points
    for esc in (r"'\"'", r"'\\'", r"'\n'", r"'\r'", r"'\t'", r"'\b'", r"'\f'", "x4"):
        assert esc in s, esc                                              # ensure_ascii escapes, lowercase hex
    assert "InvariantCulture" in s and "'R'" in s                         # 15.6 -> 15.6, never 15,6


# ── run for real when PowerShell is available ─────────────────────────────────────────────────────────────
def pwsh(expr):
    cmd = f". '{SCRIPT}'; {expr}"
    r = subprocess.run([PWSH, "-NoProfile", "-NonInteractive", "-Command", cmd], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr
    return r.stdout.strip()


@pytest.mark.skipif(not PWSH, reason="pwsh not installed; node_id pinned to the manual Windows check above")
def test_pwsh_node_id_matches_python():
    assert pwsh(f"Get-NykNodeIdFromString '{FIXED_UUID}'") == FIXED_NODE_ID


@pytest.mark.skipif(not PWSH, reason="pwsh not installed")
def test_pwsh_canonical_json_equals_card_bytes():
    card = {"card_version": 1, "node_id": FIXED_NODE_ID, "hostname": "Lab-Ä \"q\"\t", "role": None,
            "os": {"id": "windows", "version": "10.0.26300", "kernel": "10.0.26300.0", "arch": "AMD64"},
            "cpu": {"cores": 8}, "memory_gb": 15.6, "gpu": [{"name": "RTX", "vram_mb": 8192}],
            "addresses": {"ipv4": ["192.0.2.5"], "ipv6": ["fe80::1%12"]}}
    js = json.dumps(card).replace("'", "''")
    out = pwsh(f"ConvertTo-NykJson ('{js}' | ConvertFrom-Json)")
    assert out.encode() == cardmod.card_bytes(card)


@pytest.mark.skipif(not PWSH, reason="pwsh not installed")
def test_pwsh_dry_run_step_does_not_run_action():
    out = pwsh("$Apply = $false; $script:ran = $false; Invoke-NykStep 'probe' { $script:ran = $true }; \"ran=$script:ran\"")
    assert out.endswith("ran=False")


# ── published hash ────────────────────────────────────────────────────────────────────────────────────────
def test_published_sha256_matches_script():
    with open(SCRIPT, "rb") as f:
        h = hashlib.sha256(f.read()).hexdigest()
    with open(SCRIPT + ".sha256") as f:
        assert f.read().split()[0] == h, "run: sha256sum windows/join.ps1 > windows/join.ps1.sha256"


def test_script_is_ascii_for_windows_powershell_51(src):
    # PowerShell 5.1 reads a BOM-less script as the ANSI code page: any non-ASCII character can break parsing
    assert all(ord(c) < 128 for c in src)
