# Adding a Windows laptop or server to Niyantrak

For the person who looks after the office machines. You need the control machine (where the Niyantrak panel
runs) and the Windows machine side by side. It takes about ten minutes.

Works on Windows 10, Windows 11 and Windows Server 2016 or later, with the Windows PowerShell 5.1 that comes with
Windows. Nothing extra is installed apart from Windows' own OpenSSH Server feature.

## Before you start
- The panel was started with a join listener, for example `niyantrak panel --join-bind <LAN or tailnet address>`.
  Without it the panel says "Other machines cannot reach this panel yet".
- You can sign in to the Windows machine with an account that is an **Administrator**.
- Both machines are on the same office network or tailnet. IPv6 can stay on; nothing needs to be switched off.

## Step 1: Create an invitation on the control machine
1. Open the panel on the control machine (`http://127.0.0.1:8770`) and go to **Fleet**.
2. Press **Invite a machine**.
3. The box shows a **Windows** line and a **join token** below it. Keep this screen open: the token is shown only
   once, works once and expires in 24 hours.

> [screenshot placeholder: Fleet > Invite a machine, showing the Windows line, the token and the fingerprint]

## Step 2: Open PowerShell as Administrator on the Windows machine
1. Press the Windows key and type **PowerShell**.
2. Right-click **Windows PowerShell** and choose **Run as administrator**. Say **Yes** to the prompt.

> [screenshot placeholder: Start menu, right-click Windows PowerShell > Run as administrator]

## Step 3: Paste the Windows line (dry run, nothing changes)
Copy the Windows line from the panel and paste it into PowerShell, then press Enter. The line:
1. downloads `join.ps1` from the control machine, accepting only the certificate whose fingerprint is in the line;
2. refuses to run it unless its SHA-256 matches the value in the line (the same value as `windows/join.ps1.sha256`
   in this repository);
3. runs it as a **dry run**: it prints each step and what is there now, and changes nothing.

Read the plan. It looks like this:

```
Niyantrak join for Windows - Microsoft Windows 11 Pro 10.0.26300
DRY RUN - nothing is changed. Read the plan, then run again with -Apply.
  - Turn on OpenSSH Server and start it automatically
      now: sshd service Running, start Automatic
  - Remote login with keys only: PasswordAuthentication no (checked with sshd -t, backup kept)
      now: not set (sshd default: passwords allowed)
  - administrators_authorized_keys readable only by SYSTEM and Administrators
      now: readable by: NT AUTHORITY\SYSTEM, BUILTIN\Administrators
  - Firewall: SSH (TCP 22) only from 192.0.2.10; built-in any-address SSH rule off
      now: built-in SSH rule enabled=True
Node card: nyk-xxxxxxxxxxxx  LAPTOP-01  windows 10.0.26300  2 IPv4 / 3 IPv6 addresses
  - Sign the card with this machine's SSH host key and ask the control node to join (asks for the token)
Nothing was changed. To apply: run the same command with -Apply.
```

> [screenshot placeholder: PowerShell window with the dry-run plan]

If the line stops with "join.ps1 does not match the published SHA-256" or the download fails with a certificate
error, **stop**: you are not talking to your control machine, or the script was changed. Tell whoever runs the panel.

## Step 4: Run it again with -Apply
Press the Up arrow to get the same line back, add ` -Apply` at the very end, and press Enter. When it asks for the
**join token**, copy it from the panel and paste it (it is hidden while you type and is not saved on the machine).

It finishes with a line such as `nyk-xxxxxxxxxxxx: pending - an operator approves it in the panel under Fleet.`

> [screenshot placeholder: PowerShell asking for the join token, then "pending"]

## Step 5: Approve it on the control machine
In the panel under **Fleet**, the machine shows as waiting for approval. Check the name and the node id match what
the Windows machine printed, then press **Approve**.

> [screenshot placeholder: Fleet with the new Windows machine and the Approve button]

## What changes on the Windows machine
| What | Change | Why |
|---|---|---|
| OpenSSH Server (Windows optional feature) | turned on; service `sshd` starts automatically | the control machine manages it over SSH |
| `C:\ProgramData\ssh\sshd_config` | `PasswordAuthentication no` added at the top; other `PasswordAuthentication` lines removed; original kept as `sshd_config.niyantrak-bak`; checked with `sshd -t` before `sshd` restarts (a failed check puts the original back) | keys only: passwords cannot be guessed over the network |
| `C:\ProgramData\ssh\administrators_authorized_keys` | created if missing; readable only by SYSTEM and Administrators (inherited permissions removed) | Windows OpenSSH ignores the file otherwise |
| Windows Firewall | built-in rule `OpenSSH-Server-In-TCP` switched off; new rule `Niyantrak-SSH-In` allows TCP 22 only from the control machine (and any `-ExtraSshFrom` addresses) | SSH reachable only from the control machine |
| IPv6 prefix policy (only with `-PreferIPv4`) | `::ffff:0:0/96` precedence 35 -> 45 | IPv4 tried first when both work; **IPv6 stays on** |
| Temporary folder | the node card is written to a temporary folder, signed, and the folder is deleted | `ssh-keygen -Y sign` signs files |

Nothing else is changed. The join token is never written to disk, never printed and never part of the command line
(so it is not in PowerShell history). The card holds facts only: node id, computer name, Windows version, processor
count, memory, NVIDIA GPU (if any) and network addresses.

### Options
| Option | Meaning |
|---|---|
| `-Apply` | make the changes (without it: dry run) |
| `-ControlAddress <address>` | where SSH is allowed from (the Windows line fills this in) |
| `-ExtraSshFrom <a>,<b>` | more addresses or ranges allowed to SSH in, e.g. your own desktop or `100.64.0.0/10` for a tailnet |
| `-PreferIPv4` | prefer IPv4 over IPv6 when both work (IPv6 stays on) |
| `-Role <role>` | role recorded in the card (otherwise `C:\ProgramData\niyantrak\role` if present) |

**Careful:** after `-Apply`, only the control machine (and `-ExtraSshFrom`) can SSH in. If you also SSH into this
machine from somewhere else, add that address with `-ExtraSshFrom` or you will lose that access.

## How to undo
Run these in PowerShell as Administrator. Each line undoes one row of the table above.

```powershell
# Firewall: remove the Niyantrak rule and switch the built-in SSH rule back on
Remove-NetFirewallRule -Name Niyantrak-SSH-In
Enable-NetFirewallRule -Name OpenSSH-Server-In-TCP

# sshd_config: put the original back and restart
Copy-Item C:\ProgramData\ssh\sshd_config.niyantrak-bak C:\ProgramData\ssh\sshd_config -Force
Restart-Service sshd

# Prefer IPv4 (only if you used -PreferIPv4): back to the Windows default
netsh interface ipv6 set prefixpolicy prefix=::ffff:0:0/96 precedence=35 label=4 store=persistent

# OpenSSH Server: switch off (and, if it was not there before, remove the feature)
Stop-Service sshd; Set-Service sshd -StartupType Disabled
# Remove-WindowsCapability -Online -Name OpenSSH.Server~~~~0.0.1.0
```

The permissions on `administrators_authorized_keys` are what Windows OpenSSH itself expects, so there is normally
no reason to change them back. On the control machine, reject or remove the node under **Fleet**.

## For the curious: how trust works
- The control machine's join listener uses its own certificate. The Windows line and the script accept only the
  certificate whose SHA-256 is in the line, before the token leaves the machine.
- The script itself is accepted only if its SHA-256 matches the published value.
- The card is signed with the machine's own SSH host key (`C:\ProgramData\ssh\ssh_host_ed25519_key`) using
  `ssh-keygen -Y sign`, namespace `niyantrak-node-card`, the same as on Linux. The node id is
  `nyk-` + the first 12 hex characters of SHA-256 of the lower-cased SMBIOS UUID (`Win32_ComputerSystemProduct`),
  the same scheme as Linux (`/sys/class/dmi/id/product_uuid`), so a dual-boot machine keeps one id.
- A machine that later presents a different host key under the same node id is refused and an alert is recorded.

## Troubleshooting
| Message | What to do |
|---|---|
| `Open PowerShell with "Run as Administrator" to use -Apply.` | Step 2 |
| `Unsupported Windows` | Windows 10, 11 or Server 2016+ only |
| `Refusing to join: the server certificate ... does not match the pin` | you reached a different machine; check the address and the fingerprint in the panel |
| `token expired` / `token already used` | create a new invitation (Step 1) |
| `Run this with Windows PowerShell 5.1 (powershell.exe)` | the line already uses `powershell.exe`; do not run the script from PowerShell 7 (`pwsh`) |
| `sshd -t rejected the new sshd_config` | the original was put back; send the message to whoever runs the panel |
