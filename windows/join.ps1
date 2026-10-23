#Requires -Version 5.1
<#
.SYNOPSIS
  Niyantrak join for Windows 10 / 11 / Server: prepare OpenSSH for keys-only remote management and ask a Niyantrak
  control node to join, with a card signed by this machine's own SSH host key.

.DESCRIPTION
  Dry run by default: every step is printed with what is there now, and nothing is changed. Add -Apply to make the
  changes (needs "Run as Administrator").

  With -Apply, in this order:
    1. OpenSSH Server (a Windows optional feature) is turned on and set to start automatically.
    2. sshd_config gets "PasswordAuthentication no" (keys only); a backup sshd_config.niyantrak-bak is kept and the new
       file is checked with "sshd -t" before sshd restarts. A failed check puts the backup back.
    3. administrators_authorized_keys is readable only by SYSTEM and Administrators (sshd ignores it otherwise).
    4. Firewall: the built-in "OpenSSH-Server-In-TCP" rule (any address) is switched off and "Niyantrak-SSH-In"
       allows TCP 22 only from the control node (-ControlAddress, plus -ExtraSshFrom).
    5. Only with -PreferIPv4: the IPv4-mapped prefix policy is raised so IPv4 is tried first. IPv6 stays on.
    6. A node card (same fields as niyantrak/card.py) is signed with C:\ProgramData\ssh\ssh_host_ed25519_key
       (ssh-keygen -Y sign, namespace niyantrak-node-card) and sent to <PanelUrl>/api/join over HTTPS. The panel's
       certificate must hash to -Pin before anything is sent.

  The join token is asked for at step 6 (hidden input) or read once from the NIYANTRAK_JOIN_TOKEN environment
  variable, which is then cleared. It is never a parameter, never printed and never written to disk.

  Undo: see docs/WINDOWS.md ("How to undo").

.EXAMPLE
  powershell -NoProfile -ExecutionPolicy Bypass -File .\join.ps1 -PanelUrl https://192.0.2.10:8771 -Pin sha256:<64 hex> -ControlAddress 192.0.2.10
  (dry run; repeat with -Apply)
#>
[CmdletBinding()]
param(
  [string]$PanelUrl = '',
  [string]$Pin = '',
  [string]$ControlAddress = '',
  [string[]]$ExtraSshFrom = @(),
  [string]$Role = '',
  [switch]$Apply,
  [switch]$PreferIPv4
)
Set-StrictMode -Version 2.0
$ErrorActionPreference = 'Stop'

$NykNamespace = 'niyantrak-node-card'
$ProgramDataDir = $(if ($env:ProgramData) { $env:ProgramData } else { 'C:\ProgramData' })
# plain strings, not Join-Path: Join-Path needs the drive to exist, and the tests dot-source this on Linux
$SshDir = "$ProgramDataDir\ssh"
$HostKey = "$SshDir\ssh_host_ed25519_key"
$RoleFile = "$ProgramDataDir\niyantrak\role"
$FirewallRuleName = 'Niyantrak-SSH-In'
$SkipInterfaces = 'Loopback|vEthernet|Hyper-V|WSL|Docker|VMware|VirtualBox|Npcap|TAP-|Bluetooth'

# -- plan / gate ---------------------------------------------------------------------------------------------
function Invoke-NykStep {
  <# Print the step; run its action only with -Apply. The only place where a change can happen. #>
  param([string]$Name, [scriptblock]$Action, [string]$Now = '')
  Write-Host "  - $Name"
  if ($Now) { Write-Host "      now: $Now" }
  if (-not $Apply) {
    return
  }
  & $Action
  Write-Host '      done'
}

# -- checks (read only) --------------------------------------------------------------------------------------
function ConvertTo-NykPin {
  <# Same rules as niyantrak/tls.py normalise_pin: 'sha256:<hex>', plain or colon-separated hex -> 64 lower-case hex. #>
  param([string]$Value)
  $h = ([string]$Value).Trim().ToLowerInvariant()
  if ($h.StartsWith('sha256:')) { $h = $h.Substring(7) }
  $h = $h -replace '[:\s]', ''
  if ($h -notmatch '^[0-9a-f]{64}$') { throw 'The certificate pin must be a SHA-256 fingerprint (64 hex characters), as shown in the panel.' }
  return $h
}

function Test-NykWindows {
  <# Windows 10 / 11 (ProductType 1) or Windows Server 2016+ (ProductType 2/3): all report version 10.0.x. #>
  if ($PSVersionTable.PSVersion -lt [version]'5.1') { return @{ Ok = $false; Reason = 'PowerShell 5.1 or later is needed.'; Caption = '' } }
  $os = Get-CimInstance Win32_OperatingSystem
  $ok = ([string]$os.Version).StartsWith('10.') -and (@(1, 2, 3) -contains [int]$os.ProductType)
  $reason = $(if ($ok) { '' } else { "Unsupported Windows: $($os.Caption) $($os.Version). Windows 10, 11 or Server 2016+ is needed." })
  return @{ Ok = $ok; Reason = $reason; Caption = "$($os.Caption) $($os.Version)" }
}

function Test-NykAdmin {
  $p = New-Object Security.Principal.WindowsPrincipal ([Security.Principal.WindowsIdentity]::GetCurrent())
  return $p.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}

function Resolve-NykControlAddress {
  <# Addresses SSH is allowed from: -ControlAddress (default: the panel host) plus -ExtraSshFrom (addresses or CIDR). #>
  param([string]$Address, [string]$Url, [string[]]$Extra)
  $first = $(if ($Address) { $Address } else { ([Uri]$Url).Host.Trim('[', ']') })
  $out = New-Object System.Collections.Generic.List[string]
  foreach ($c in @(@($first) + @($Extra))) {
    if (-not $c) { continue }
    $ip = $null
    if ($c -match '/') { $out.Add($c); continue }
    if ([Net.IPAddress]::TryParse($c, [ref]$ip)) { $out.Add(($ip.ToString() -replace '%.*$', '')); continue }
    try { foreach ($a in [Net.Dns]::GetHostAddresses($c)) { $out.Add(($a.ToString() -replace '%.*$', '')) } }
    catch { throw "Cannot resolve the control node '$c'. Pass -ControlAddress <its LAN or tailnet address>." }
  }
  return @($out | Select-Object -Unique)
}

function Get-NykNow {
  <# Current value for the plan; a read that needs Administrator just says so. #>
  param([scriptblock]$Read)
  try { return [string](& $Read) } catch { return 'not readable without Administrator' }
}

function Get-NykSshdNow {
  $svc = Get-Service -Name sshd -ErrorAction SilentlyContinue
  if (-not $svc) { return 'OpenSSH Server is not installed' }
  return "sshd service $($svc.Status), start $($svc.StartType)"
}

function Get-NykPasswordAuthNow {
  $cfg = Join-Path $SshDir 'sshd_config'
  if (-not (Test-Path $cfg)) { return 'no sshd_config yet (sshd default: passwords allowed)' }
  $l = @(Get-Content $cfg | Where-Object { $_ -match '^\s*PasswordAuthentication\s' } | Select-Object -First 1)
  if ($l.Count) { return $l[0].Trim() }
  return 'not set (sshd default: passwords allowed)'
}

function Get-NykAdminKeysNow {
  $f = Join-Path $SshDir 'administrators_authorized_keys'
  if (-not (Test-Path $f)) { return 'file does not exist yet' }
  $who = @((Get-Acl $f).Access | ForEach-Object { [string]$_.IdentityReference }) -join ', '
  return "readable by: $who"
}

function Get-NykFirewallNow {
  $r = Get-NetFirewallRule -Name 'OpenSSH-Server-In-TCP' -ErrorAction SilentlyContinue
  $mine = Get-NetFirewallRule -Name $FirewallRuleName -ErrorAction SilentlyContinue
  $off = @(Get-NetFirewallProfile -ErrorAction SilentlyContinue | Where-Object { -not $_.Enabled } | ForEach-Object { $_.Name })
  $s = $(if ($r) { "built-in SSH rule enabled=$($r.Enabled)" } else { 'no built-in SSH rule' })
  if ($mine) { $s += "; $FirewallRuleName present" }
  if ($off.Count) { $s += "; WARNING firewall profile off: $($off -join ', ')" }
  return $s
}

# -- node card (read only; same fields as niyantrak/card.py) -------------------------------------------------
function Get-NykNodeIdFromString {
  <# nyk-<sha256(lower-cased, trimmed id)[:12]>, as card.node_id(). -Verbatim: hostname fallback, not lower-cased. #>
  param([string]$Raw, [switch]$Verbatim)
  $s = $(if ($Verbatim) { $Raw } else { $Raw.Trim().ToLowerInvariant() })
  $sha = [Security.Cryptography.SHA256]::Create()
  $bytes = $sha.ComputeHash([Text.Encoding]::UTF8.GetBytes($s))
  return 'nyk-' + (-join ($bytes | ForEach-Object { $_.ToString('x2') })).Substring(0, 12)
}

function Get-NykNodeId {
  <# SMBIOS UUID (Win32_ComputerSystemProduct) like /sys/class/dmi/id/product_uuid; MachineGuid like /etc/machine-id. #>
  $uuid = ''
  try { $uuid = [string](Get-CimInstance Win32_ComputerSystemProduct).UUID } catch { $uuid = '' }
  if ($uuid.Trim()) { return Get-NykNodeIdFromString $uuid }
  $guid = ''
  try { $guid = [string](Get-ItemProperty 'HKLM:\SOFTWARE\Microsoft\Cryptography' -Name MachineGuid).MachineGuid } catch { $guid = '' }
  if ($guid.Trim()) { return Get-NykNodeIdFromString $guid }
  return Get-NykNodeIdFromString ([Net.Dns]::GetHostName()) -Verbatim
}

function Get-NykGpu {
  <# Like card._gpu(): nvidia-smi only; one {name, vram_mb} per GPU on the pipeline, nothing without nvidia-smi. #>
  $smi = Get-Command nvidia-smi -ErrorAction SilentlyContinue
  if (-not $smi) { return }
  foreach ($l in @(& $smi.Source --query-gpu=name,memory.total --format=csv,noheader,nounits 2>$null)) {
    if ([string]$l -notmatch ',') { continue }
    $n, $m = ([string]$l) -split ',', 2
    [ordered]@{ name = $n.Trim(); vram_mb = [int]$m.Trim() }
  }
}

function Get-NykAddresses {
  <# Physical / LAN / VPN interfaces (virtual switches skipped); IPv6 link-local keeps %<interface index>. #>
  $v4 = New-Object System.Collections.Generic.List[string]
  $v6 = New-Object System.Collections.Generic.List[string]
  foreach ($a in @(Get-NetIPAddress -ErrorAction SilentlyContinue)) {
    if ([string]$a.InterfaceAlias -match $SkipInterfaces) { continue }
    $ip = [string]$a.IPAddress
    if ([string]$a.AddressFamily -eq 'IPv4') {
      if (-not $ip.StartsWith('127.') -and -not $v4.Contains($ip)) { $v4.Add($ip) }
    } else {
      if ($ip -eq '::1') { continue }
      if ($ip.StartsWith('fe80') -and $ip -notmatch '%') { $ip = "$ip%$($a.InterfaceIndex)" }
      if (-not $v6.Contains($ip)) { $v6.Add($ip) }
    }
  }
  $a4 = [string[]]$v4.ToArray(); $a6 = [string[]]$v6.ToArray()
  [Array]::Sort($a4, [StringComparer]::Ordinal); [Array]::Sort($a6, [StringComparer]::Ordinal)
  return @{ ipv4 = $a4; ipv6 = $a6 }
}

function New-NykCard {
  param([string]$Role = '')
  $os = Get-CimInstance Win32_OperatingSystem
  $cs = Get-CimInstance Win32_ComputerSystem
  $ubr = ''
  try { $ubr = [string](Get-ItemProperty 'HKLM:\SOFTWARE\Microsoft\Windows NT\CurrentVersion' -Name UBR).UBR } catch { $ubr = '' }
  $osId = $(if ([int]$os.ProductType -eq 1) { 'windows' } else { 'windows-server' })
  $kernel = $(if ($ubr) { "$($os.Version).$ubr" } else { [string]$os.Version })
  $arch = $(if ($env:PROCESSOR_ARCHITEW6432) { $env:PROCESSOR_ARCHITEW6432 } else { [string]$env:PROCESSOR_ARCHITECTURE })
  $roleValue = $null
  if ($Role) { $roleValue = $Role } elseif (Test-Path $RoleFile) { $roleValue = ([string](Get-Content $RoleFile -Raw)).Trim() }
  $memGb = [math]::Round([double]$cs.TotalPhysicalMemory / 1GB, 1)
  $gpu = @(Get-NykGpu)
  $addr = Get-NykAddresses
  $nodeId = Get-NykNodeId
  $card = [ordered]@{
    card_version = 1
    node_id = $nodeId
    hostname = [Net.Dns]::GetHostName()
    role = $roleValue
    os = [ordered]@{ id = $osId; version = [string]$os.Version; kernel = $kernel; arch = $arch }
    cpu = [ordered]@{ cores = [Environment]::ProcessorCount }
    memory_gb = $memGb
    gpu = $gpu
    addresses = [ordered]@{ ipv4 = $addr.ipv4; ipv6 = $addr.ipv6 }
  }
  return $card
}

function ConvertTo-NykJson {
  <# Canonical JSON, byte-identical to card.card_bytes(): json.dumps(sort_keys=True, separators=(",", ":")),
     ensure_ascii (every character outside space..~ as \uXXXX, lower-case hex), Python float text. #>
  param($Value)
  if ($null -eq $Value) { return 'null' }
  if ($Value -is [bool]) { if ($Value) { return 'true' } else { return 'false' } }
  if ($Value -is [string] -or $Value -is [char]) {
    $sb = New-Object System.Text.StringBuilder
    [void]$sb.Append('"')
    foreach ($ch in ([string]$Value).ToCharArray()) {
      $c = [int]$ch
      if ($c -eq 0x22) { [void]$sb.Append('\"') }
      elseif ($c -eq 0x5C) { [void]$sb.Append('\\') }
      elseif ($c -eq 0x0A) { [void]$sb.Append('\n') }
      elseif ($c -eq 0x0D) { [void]$sb.Append('\r') }
      elseif ($c -eq 0x09) { [void]$sb.Append('\t') }
      elseif ($c -eq 0x08) { [void]$sb.Append('\b') }
      elseif ($c -eq 0x0C) { [void]$sb.Append('\f') }
      elseif ($c -lt 0x20 -or $c -gt 0x7E) { [void]$sb.Append(('\u{0:x4}' -f $c)) }
      else { [void]$sb.Append($ch) }
    }
    [void]$sb.Append('"')
    return $sb.ToString()
  }
  $inv = [Globalization.CultureInfo]::InvariantCulture
  if ($Value -is [double] -or $Value -is [single] -or $Value -is [decimal]) {
    $t = ([double]$Value).ToString('R', $inv).Replace('E', 'e')
    if ($t -match '^-?\d+$') { $t += '.0' }                            # Python: 16.0, not 16
    if ($t -match 'e[+-]?\d$') { $t = $t -replace 'e([+-]?)(\d)$', 'e${1}0$2' }   # Python: 1e-05
    return $t
  }
  if ($Value -is [int] -or $Value -is [long] -or $Value -is [int16] -or $Value -is [byte] -or
      $Value -is [uint16] -or $Value -is [uint32] -or $Value -is [uint64] -or $Value -is [sbyte]) {
    return $Value.ToString($inv)
  }
  if ($Value -is [System.Collections.IDictionary]) {
    $keys = [string[]]@($Value.Keys | ForEach-Object { [string]$_ })
    [Array]::Sort($keys, [StringComparer]::Ordinal)
    $parts = foreach ($k in $keys) { (ConvertTo-NykJson $k) + ':' + (ConvertTo-NykJson $Value[$k]) }
    return '{' + (@($parts) -join ',') + '}'
  }
  if ($Value -is [System.Collections.IEnumerable]) {
    $parts = foreach ($x in $Value) { ConvertTo-NykJson $x }
    return '[' + (@($parts) -join ',') + ']'
  }
  if ($Value -is [System.Management.Automation.PSCustomObject]) {
    $h = [ordered]@{}
    foreach ($p in $Value.PSObject.Properties) { $h[$p.Name] = $p.Value }
    return ConvertTo-NykJson $h
  }
  throw "ConvertTo-NykJson: unsupported type $($Value.GetType().FullName)"
}

function Read-NykToken {
  <# Hidden prompt, or NIYANTRAK_JOIN_TOKEN once (then cleared). Kept in memory only; the BSTR copy is zeroed. #>
  $t = [Environment]::GetEnvironmentVariable('NIYANTRAK_JOIN_TOKEN', 'Process')
  if ($t) {
    [Environment]::SetEnvironmentVariable('NIYANTRAK_JOIN_TOKEN', $null, 'Process')
    return $t
  }
  $sec = Read-Host -Prompt 'Join token from the panel (hidden; not saved)' -AsSecureString
  $b = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($sec)
  try { return [Runtime.InteropServices.Marshal]::PtrToStringBSTR($b) }
  finally { [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($b) }
}

#region apply-actions
# Everything in this region changes the machine. Each function is called only as an Invoke-NykStep action.
function Set-NykOpenSsh {
  if (-not (Get-Service -Name sshd -ErrorAction SilentlyContinue)) {
    $cap = Get-WindowsCapability -Online -Name 'OpenSSH.Server*' | Select-Object -First 1
    if (-not $cap) { throw 'This Windows has no OpenSSH Server feature to turn on.' }
    if ([string]$cap.State -ne 'Installed') { Add-WindowsCapability -Online -Name $cap.Name | Out-Null }
  }
  Set-Service -Name sshd -StartupType Automatic
  Start-Service -Name sshd                                    # first start creates the host keys
}

function Set-NykSshdConfig {
  $cfg = Join-Path $SshDir 'sshd_config'
  $bak = "$cfg.niyantrak-bak"
  if (-not (Test-Path $bak)) { Copy-Item -Path $cfg -Destination $bak }      # the original, kept for undo
  $out = New-Object System.Collections.Generic.List[string]
  $out.Add('# Niyantrak: keys only (first value wins in sshd_config). Original: sshd_config.niyantrak-bak')
  $out.Add('PasswordAuthentication no')
  foreach ($l in [IO.File]::ReadAllLines($cfg)) {
    if ($l -match '^\s*PasswordAuthentication\s' -or $l -match '^# Niyantrak: keys only') { continue }
    $out.Add($l)
  }
  [IO.File]::WriteAllLines($cfg, $out)
  $sshd = Join-Path $env:WINDIR 'System32\OpenSSH\sshd.exe'
  & $sshd -t
  if ($LASTEXITCODE -ne 0) {
    Copy-Item -Path $bak -Destination $cfg -Force
    throw 'sshd -t rejected the new sshd_config; the original was put back.'
  }
  Restart-Service -Name sshd
}

function Set-NykAdminKeysAcl {
  $f = Join-Path $SshDir 'administrators_authorized_keys'
  if (-not (Test-Path $f)) { New-Item -ItemType File -Path $f | Out-Null }
  $acl = Get-Acl -Path $f
  $acl.SetAccessRuleProtection($true, $false)                 # no inherited entries
  foreach ($r in @($acl.GetAccessRules($true, $false, [Security.Principal.SecurityIdentifier]))) { [void]$acl.RemoveAccessRule($r) }
  foreach ($sid in @('S-1-5-18', 'S-1-5-32-544')) {            # SYSTEM, BUILTIN\Administrators (any language)
    $id = New-Object Security.Principal.SecurityIdentifier $sid
    $acl.AddAccessRule((New-Object Security.AccessControl.FileSystemAccessRule $id, 'FullControl', 'Allow'))
  }
  Set-Acl -Path $f -AclObject $acl
}

function Set-NykFirewall {
  param([string[]]$From)
  if (-not $From -or $From.Count -eq 0) { throw 'No control node address for the SSH firewall rule.' }
  Get-NetFirewallRule -Name 'OpenSSH-Server-In-TCP' -ErrorAction SilentlyContinue | Disable-NetFirewallRule
  Get-NetFirewallRule -Name $FirewallRuleName -ErrorAction SilentlyContinue | Remove-NetFirewallRule
  New-NetFirewallRule -Name $FirewallRuleName -DisplayName 'Niyantrak: SSH from the control node' -Direction Inbound `
    -Protocol TCP -LocalPort 22 -RemoteAddress $From -Action Allow -Profile Any | Out-Null
}

function Set-NykPreferIPv4 {
  # IPv4-mapped addresses above ::/0 (40) and below ::1 (50). IPv6 itself is untouched. Undo: precedence=35.
  & netsh.exe interface ipv6 set prefixpolicy prefix=::ffff:0:0/96 precedence=45 label=4 store=persistent | Out-Null
  if ($LASTEXITCODE -ne 0) { throw 'netsh could not set the prefix policy.' }
}

function Install-NykPinType {
  if ('NykPin' -as [type]) { return }
  Add-Type -TypeDefinition @'
using System;
using System.Net;
using System.Net.Security;
using System.Security.Cryptography;
using System.Security.Cryptography.X509Certificates;
public static class NykPin {
    public static string Pin;
    public static string Seen;
    static bool Check(object sender, X509Certificate cert, X509Chain chain, SslPolicyErrors errors) {
        if (cert == null || Pin == null) { return false; }
        using (SHA256 sha = SHA256.Create()) {
            Seen = BitConverter.ToString(sha.ComputeHash(cert.GetRawCertData())).Replace("-", "").ToLowerInvariant();
        }
        return Seen == Pin;               // self-signed: identity is the pin, not a CA or a name
    }
    public static void Install(string pin) { Pin = pin; Seen = null; ServicePointManager.ServerCertificateValidationCallback = Check; }
    public static void Uninstall() { ServicePointManager.ServerCertificateValidationCallback = null; Pin = null; }
}
'@
}

function Invoke-NykJoinRequest {
  param([string]$Url, [string]$PinHex, $Card)
  if ($PSVersionTable.PSEdition -eq 'Core') {
    throw 'Run this with Windows PowerShell 5.1 (powershell.exe): the certificate pin is enforced through ServicePointManager.'
  }
  if (-not (Test-Path $HostKey)) { throw "No SSH host key at $HostKey (sshd creates it on first start)." }
  $cardJson = ConvertTo-NykJson $Card
  $tmp = Join-Path ([IO.Path]::GetTempPath()) ('niyantrak-card-' + [guid]::NewGuid().ToString('n'))
  New-Item -ItemType Directory -Path $tmp | Out-Null
  try {
    $f = Join-Path $tmp 'card.json'                            # the card is public facts; the token never goes here
    [IO.File]::WriteAllBytes($f, [Text.Encoding]::UTF8.GetBytes($cardJson))
    & ssh-keygen.exe -q -Y sign -f $HostKey -n $NykNamespace $f
    if ($LASTEXITCODE -ne 0) { throw 'ssh-keygen could not sign the card with the host key.' }
    $sig = [IO.File]::ReadAllText("$f.sig")
  } finally {
    Remove-Item -Recurse -Force -Path $tmp -ErrorAction SilentlyContinue
  }
  $pub = ([IO.File]::ReadAllText("$HostKey.pub")).Trim()
  Install-NykPinType
  [Net.ServicePointManager]::SecurityProtocol = [Net.ServicePointManager]::SecurityProtocol -bor [Net.SecurityProtocolType]::Tls12
  $token = Read-NykToken
  $body = [Text.Encoding]::UTF8.GetBytes('{"card":' + $cardJson + ',"host_pubkey":' + (ConvertTo-NykJson $pub) +
    ',"signature":' + (ConvertTo-NykJson $sig) + ',"token":' + (ConvertTo-NykJson $token) + '}')
  $token = $null
  [NykPin]::Install($PinHex)                                  # checked in the TLS handshake, before the body is sent
  try {
    return Invoke-RestMethod -Method Post -Uri ($Url.TrimEnd('/') + '/api/join') -ContentType 'application/json' `
      -Body $body -UseBasicParsing -TimeoutSec 30
  } catch {
    $seen = [NykPin]::Seen
    if ($seen -and $seen -ne $PinHex) { throw "Refusing to join: the server certificate sha256:$seen does not match the pin." }
    $msg = $_.Exception.Message
    if ($_.ErrorDetails -and $_.ErrorDetails.Message) {
      try { $msg = (ConvertFrom-Json $_.ErrorDetails.Message).error } catch { $msg = $_.ErrorDetails.Message }
    }
    throw "Join refused: $msg"
  } finally {
    [NykPin]::Uninstall()
    $body = $null
  }
}
#endregion apply-actions

# Dot-sourcing (". .\join.ps1") loads the functions only - used by the tests.
if ($MyInvocation.InvocationName -eq '.') { return }

#region main
try {
  if (-not $PanelUrl -or -not $Pin) {
    throw 'Usage: join.ps1 -PanelUrl https://<control node>:8771 -Pin sha256:<fingerprint> [-ControlAddress <address>] [-Apply] [-PreferIPv4]'
  }
  if ($PanelUrl -notmatch '^https://') { throw 'Use the https join address shown in the panel; plain http is refused.' }
  $pinHex = ConvertTo-NykPin $Pin
  $win = Test-NykWindows
  if (-not $win.Ok) { throw $win.Reason }
  $isAdmin = Test-NykAdmin
  if ($Apply -and -not $isAdmin) { throw 'Open PowerShell with "Run as Administrator" to use -Apply.' }
  $from = Resolve-NykControlAddress -Address $ControlAddress -Url $PanelUrl -Extra $ExtraSshFrom

  Write-Host "Niyantrak join for Windows - $($win.Caption)"
  if ($Apply) { Write-Host 'APPLYING the steps below.' }
  else {
    Write-Host 'DRY RUN - nothing is changed. Read the plan, then run again with -Apply.'
    if (-not $isAdmin) { Write-Host '(not running as Administrator: some current values may be hidden)' }
  }
  Write-Host "Panel: $PanelUrl  (certificate must be sha256:$pinHex)"

  Invoke-NykStep 'Turn on OpenSSH Server and start it automatically' -Now (Get-NykNow { Get-NykSshdNow }) -Action { Set-NykOpenSsh }
  Invoke-NykStep 'Remote login with keys only: PasswordAuthentication no (checked with sshd -t, backup kept)' -Now (Get-NykNow { Get-NykPasswordAuthNow }) -Action { Set-NykSshdConfig }
  Invoke-NykStep 'administrators_authorized_keys readable only by SYSTEM and Administrators' -Now (Get-NykNow { Get-NykAdminKeysNow }) -Action { Set-NykAdminKeysAcl }
  Invoke-NykStep "Firewall: SSH (TCP 22) only from $($from -join ', '); built-in any-address SSH rule off" -Now (Get-NykNow { Get-NykFirewallNow }) -Action { Set-NykFirewall -From $from }
  if ($PreferIPv4) {
    Invoke-NykStep 'Prefer IPv4 when both work (prefix policy ::ffff:0:0/96 -> 45). IPv6 stays on.' -Action { Set-NykPreferIPv4 }
  }

  $card = New-NykCard -Role $Role
  Write-Host ("Node card: {0}  {1}  {2} {3}  {4} IPv4 / {5} IPv6 addresses" -f $card.node_id, $card.hostname,
    $card.os.id, $card.os.version, @($card.addresses.ipv4).Count, @($card.addresses.ipv6).Count)
  $hostKeyNow = $(if (Test-Path "$HostKey.pub") { 'host key present' } else { 'no host key yet (created when sshd first starts)' })
  $script:joinResult = $null
  Invoke-NykStep 'Sign the card with this machine''s SSH host key and ask the control node to join (asks for the token)' -Now $hostKeyNow -Action { $script:joinResult = Invoke-NykJoinRequest -Url $PanelUrl -PinHex $pinHex -Card $card }

  if ($script:joinResult) {
    $r = $script:joinResult
    $next = $(if ($r.state -eq 'pending') { ' - an operator approves it in the panel under Fleet.' } else { '' })
    Write-Host "$($r.node_id): $($r.state)$next"
  } elseif (-not $Apply) {
    Write-Host 'Nothing was changed. To apply: run the same command with -Apply.'
  }
  exit 0
} catch {
  Write-Host "join refused: $($_.Exception.Message)" -ForegroundColor Red
  exit 1
}
#endregion main
