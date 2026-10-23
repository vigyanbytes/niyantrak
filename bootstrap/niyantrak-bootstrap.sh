#!/usr/bin/env bash
# niyantrak-bootstrap.sh -- first-node bootstrap v0: stock Ubuntu Server -> governed base node. Deterministic, no LLM.
#
#   sudo bash niyantrak-bootstrap.sh [--dry-run] [--role control|node] [--from-step N]
#
# Steps (each idempotent, recorded in $STATE/state; a re-run skips finished steps and resumes after a power cut):
#   1 preflight   root via sudo, supported OS/version/arch, time sync (S-9, S-11)
#   2 packages    auditd, ufw, unattended-upgrades, avahi-daemon, git, curl, jq, gh — official Ubuntu archive only (S-8)
#   3 scaffold    /etc/niyantrak (0755), /etc/niyantrak/secret.d (0700), /var/lib/niyantrak, /var/log/niyantrak; node-id from SMBIOS uuid
#   4 auditd      targeted rules with nyk-* keys (identity, sudo, ssh, units, firewall, secrets, gate)
#   5 ssh         PermitRootLogin no, no password/keyboard-interactive logins, pre-login banner
#                 GUARD: refuses unless the invoking admin has an authorized key (no lock-out)
#   6 root        root password locked (Ubuntu default; enforced)
#   7 firewall    UFW deny incoming; SSH/HTTP/HTTPS only from private ranges + tailnet; mDNS on the LAN
#                 GUARD: refuses if the current SSH client address would not be allowed
#   8 motd        login status page (no secrets, no network calls)
#   9 setup-code  one-time code for claiming vPanel (30 min; only its hash is stored) shown on console + MOTD
#  10 report      $STATE/report.json
#
# Exit: 0 done, 2 usage/unsupported, 3 guard refused, 4 step failed (re-run resumes).
# Test hooks (unit tests only): NIYANTRAK_ROOT=<dir> writes files under <dir> and skips system commands;
# NIYANTRAK_OS_RELEASE=<file> replaces /etc/os-release; NIYANTRAK_FAKE_EUID, NIYANTRAK_FAKE_ARCH.
set -euo pipefail
umask 022

VERSION="0.1.0"
R=${NIYANTRAK_ROOT:-}                       # file-system prefix (tests)
ETC="$R/etc/niyantrak"
STATE="$R/var/lib/niyantrak/bootstrap"
LOGDIR="$R/var/log/niyantrak"
LOG="$LOGDIR/bootstrap.log"
OS_RELEASE=${NIYANTRAK_OS_RELEASE:-/etc/os-release}
SUPPORTED_UBUNTU=("24.04" "26.04")
PRIVATE_NETS=(10.0.0.0/8 172.16.0.0/12 192.168.0.0/16 100.64.0.0/10)
DRY=0
ROLE=control
FROM=1
STEPS=(preflight packages scaffold auditd ssh root firewall motd setup-code report)

usage() { sed -n '2,24p' "$0" | sed 's/^# \{0,1\}//'; }
while [[ $# -gt 0 ]]; do
  case $1 in
    --dry-run) DRY=1 ;;
    --role) ROLE=${2:?}; shift ;;
    --from-step) FROM=${2:?}; shift ;;
    -h|--help) usage; exit 0 ;;
    *) echo "unknown option: $1" >&2; usage >&2; exit 2 ;;
  esac
  shift
done
[[ $ROLE == control || $ROLE == node ]] || { echo "role must be control or node" >&2; exit 2; }

TESTMODE=0; [[ -n $R ]] && TESTMODE=1
log() {
  local line; line="$(date -Is) [bootstrap] $*"
  echo "$line"
  if [[ $DRY == 0 ]]; then mkdir -p "$LOGDIR"; echo "$line" >> "$LOG"; fi
}
die() { log "FAILED: $*"; exit "${2:-4}"; }
sys() {  # run a system command (skipped in dry-run and test mode)
  if [[ $DRY == 1 ]]; then log "would run: $*"; return 0; fi
  if [[ $TESTMODE == 1 ]]; then log "test mode, skipped: $*"; return 0; fi
  "$@"
}
put() {  # put <path> <mode> <content>: write a file only if content changed
  local path=$1 mode=$2 content=$3
  if [[ -f $path ]] && [[ "$(cat "$path")" == "$content" ]]; then log "unchanged: ${path#"$R"}"; return 0; fi
  if [[ $DRY == 1 ]]; then log "would write: ${path#"$R"} ($mode)"; return 0; fi
  mkdir -p "$(dirname "$path")"
  local tmp; tmp=$(mktemp "$(dirname "$path")/.nyk.XXXXXX")
  printf '%s\n' "$content" > "$tmp"
  chmod "$mode" "$tmp"
  mv -f "$tmp" "$path"
  log "wrote: ${path#"$R"} ($mode)"
}
done_step() { [[ -f $STATE/state ]] && grep -qx "$1" "$STATE/state"; }
mark() { [[ $DRY == 1 ]] && return 0; mkdir -p "$STATE"; echo "$1" >> "$STATE/state"; }
admin_user() { echo "${SUDO_USER:-${NIYANTRAK_ADMIN:-}}"; }
admin_home() { local u; u=$(admin_user); [[ -n $u ]] && getent passwd "$u" | cut -d: -f6; }

# ── pure renderers (unit-tested) ────────────────────────────────────────────────────────────────────────
render_audit_rules() {
  cat <<'EOF'
## niyantrak-bootstrap: targeted audit rules (named keys; query with: ausearch -k <key>)
-w /etc/passwd -p wa -k nyk-identity
-w /etc/shadow -p wa -k nyk-identity
-w /etc/group -p wa -k nyk-identity
-w /etc/gshadow -p wa -k nyk-identity
-w /etc/sudoers -p wa -k nyk-sudoers
-w /etc/sudoers.d/ -p wa -k nyk-sudoers
-a always,exit -F arch=b64 -F path=/usr/bin/sudo -F perm=x -k nyk-sudo-exec
-w /etc/ssh/sshd_config -p wa -k nyk-ssh
-w /etc/ssh/sshd_config.d/ -p wa -k nyk-ssh
-w /root/.ssh/ -p wa -k nyk-ssh-keys
-w /etc/systemd/system/ -p wa -k nyk-units
-w /etc/ufw/ -p wa -k nyk-firewall
-w /etc/niyantrak/secret.d/ -p rwa -k nyk-secrets
-w /etc/niyantrak/gate-mode -p wa -k nyk-gate
-w /etc/audit/ -p wa -k nyk-audit-config
EOF
}

render_sshd() {
  cat <<'EOF'
# niyantrak-bootstrap: SSH hardening (root never logs in; keys only)
PermitRootLogin no
PasswordAuthentication no
KbdInteractiveAuthentication no
PermitEmptyPasswords no
PubkeyAuthentication yes
MaxAuthTries 4
LoginGraceTime 30
X11Forwarding no
Banner /etc/issue.net
EOF
}

render_banner() {
  cat <<'EOF'
Authorised access only. This machine is governed: every login and administrative action is recorded.
EOF
}

render_motd() {
  cat <<'EOF'
#!/bin/sh
# niyantrak-bootstrap: login status (reads local files only; no network, no secrets)
S=/var/lib/niyantrak/bootstrap
printf '\n  governed node  %s   role: %s\n' "$(cat /etc/niyantrak/node-id 2>/dev/null || echo unknown)" "$(cat /etc/niyantrak/role 2>/dev/null || echo unknown)"
if [ -f "$S/report.json" ]; then printf '  bootstrap: done (%s)\n' "$(sed -n 's/.*"finished": "\([^"]*\)".*/\1/p' "$S/report.json")"
else printf '  bootstrap: in progress — see /var/log/niyantrak/bootstrap.log\n'; fi
if [ -f "$S/setup-code.expires" ] && [ "$(date +%s)" -lt "$(cat "$S/setup-code.expires")" ]; then
  printf '  vPanel setup code: see the machine console (valid until %s)\n' "$(date -d "@$(cat "$S/setup-code.expires")" +%H:%M)"
fi
printf '  firewall: %s   audit rules: %s\n\n' "$(ufw status 2>/dev/null | head -1 | cut -d' ' -f2)" "$(auditctl -l 2>/dev/null | grep -c 'nyk-')"
EOF
}

detect_os() {  # prints "ok <id> <version> <arch>" or "refuse <reason>"
  local id="" ver="" arch
  arch=${NIYANTRAK_FAKE_ARCH:-$(uname -m)}
  if [[ -r $OS_RELEASE ]]; then
    id=$(. "$OS_RELEASE" && echo "${ID:-}")
    ver=$(. "$OS_RELEASE" && echo "${VERSION_ID:-}")
  fi
  [[ $id == ubuntu ]] || { echo "refuse unsupported OS '${id:-unknown}': this release supports Ubuntu Server LTS ${SUPPORTED_UBUNTU[*]}"; return; }
  local v ok=0
  for v in "${SUPPORTED_UBUNTU[@]}"; do [[ $ver == "$v" ]] && ok=1; done
  [[ $ok == 1 ]] || { echo "refuse Ubuntu $ver is not a supported LTS (supported: ${SUPPORTED_UBUNTU[*]})"; return; }
  [[ $arch == x86_64 || $arch == aarch64 ]] || { echo "refuse architecture $arch not supported (x86_64, aarch64)"; return; }
  echo "ok $id $ver $arch"
}

ssh_peers() {  # addresses of every live SSH connection to this machine (sudo strips SSH_CLIENT, so ask the kernel)
  if [[ -n ${NIYANTRAK_FAKE_SSH_PEERS+x} ]]; then tr ',' '\n' <<<"$NIYANTRAK_FAKE_SSH_PEERS"; return; fi
  ss -tnH state established '( sport = :22 )' 2>/dev/null | awk '{print $4}' | sed -E 's/^\[?(::ffff:)?//; s/\]?:[0-9]+$//' | sort -u
}
ip_in_private() {  # ip_in_private <ipv4>: 0 if inside PRIVATE_NETS
  python3 - "$1" "${PRIVATE_NETS[@]}" <<'PY'
import ipaddress, sys
ip = sys.argv[1]
try:
    a = ipaddress.ip_address(ip)
except ValueError:
    sys.exit(1)
sys.exit(0 if any(a in ipaddress.ip_network(n) for n in sys.argv[2:]) else 1)
PY
}

# ── steps ───────────────────────────────────────────────────────────────────────────────────────────────
step_preflight() {
  local euid=${NIYANTRAK_FAKE_EUID:-$EUID}
  [[ $euid == 0 ]] || die "run with sudo (as your admin user): sudo bash $0" 2
  local os; os=$(detect_os)
  [[ $os == ok* ]] || die "${os#refuse }" 2
  log "os: ${os#ok }"
  [[ -n $(admin_user) ]] || die "run through sudo from your admin account (SUDO_USER is empty; root logins are not used)" 2
  log "admin: $(admin_user)"
  if [[ $TESTMODE == 0 && $DRY == 0 ]]; then
    timedatectl set-ntp true || true
    local i; for i in $(seq 1 30); do
      [[ $(timedatectl show -p NTPSynchronized --value 2>/dev/null) == yes ]] && break; sleep 2
    done
    log "time synced: $(timedatectl show -p NTPSynchronized --value 2>/dev/null || echo unknown)"
  fi
}

step_packages() {
  sys env DEBIAN_FRONTEND=noninteractive apt-get update -q
  sys env DEBIAN_FRONTEND=noninteractive apt-get install -y -q --no-install-recommends \
    auditd audispd-plugins ufw unattended-upgrades avahi-daemon git curl jq gh ca-certificates
}

step_scaffold() {
  if [[ $DRY == 0 ]]; then
    install -d -m 0755 "$ETC" "$R/var/lib/niyantrak" "$LOGDIR" "$STATE"
    install -d -m 0700 "$ETC/secret.d"
  else
    log "would create: /etc/niyantrak /etc/niyantrak/secret.d(0700) /var/lib/niyantrak /var/log/niyantrak"
  fi
  local uuid="" f=${NIYANTRAK_PRODUCT_UUID_FILE:-/sys/class/dmi/id/product_uuid}
  [[ -r $f ]] && uuid=$(tr '[:upper:]' '[:lower:]' < "$f")
  [[ -n $uuid ]] || uuid=$(cat /etc/machine-id 2>/dev/null || echo unknown)
  put "$ETC/node-id" 0644 "nyk-$(printf '%s' "$uuid" | sha256sum | cut -c1-12)"
  put "$ETC/role" 0644 "$ROLE"
}

step_auditd() {
  put "$R/etc/audit/rules.d/50-niyantrak.rules" 0640 "$(render_audit_rules)"
  sys augenrules --load
}

step_ssh() {
  local home keys; home=$(admin_home || true)
  keys="$R$home/.ssh/authorized_keys"
  if [[ -z $home || ! -s $keys ]]; then
    die "GUARD: $(admin_user) has no SSH key in ~/.ssh/authorized_keys; turning off password logins would lock you out. Add your key, then re-run." 3
  fi
  put "$R/etc/issue.net" 0644 "$(render_banner)"
  put "$R/etc/ssh/sshd_config.d/10-niyantrak.conf" 0644 "$(render_sshd)"
  if [[ $DRY == 0 && $TESTMODE == 0 ]]; then
    sshd -t || { rm -f /etc/ssh/sshd_config.d/10-niyantrak.conf; die "sshd config test failed; change removed" 4; }
    systemctl reload ssh || systemctl reload sshd
  fi
}

step_root() {
  sys passwd -l root
}

step_firewall() {
  local ip
  while read -r ip; do
    [[ -z $ip ]] && continue
    if ! ip_in_private "$ip"; then
      die "GUARD: an SSH session is connected from $ip, which is not a private/tailnet address; enabling the firewall would cut it off. Connect over the LAN or tailnet (or the provider console) and re-run." 3
    fi
  done < <(ssh_peers)
  sys ufw --force reset
  sys ufw default deny incoming
  sys ufw default allow outgoing
  local n p
  for n in "${PRIVATE_NETS[@]}"; do
    for p in 22 80 443; do sys ufw allow from "$n" to any port "$p" proto tcp comment "niyantrak-bootstrap"; done
  done
  for n in 10.0.0.0/8 172.16.0.0/12 192.168.0.0/16; do
    sys ufw allow from "$n" to any port 5353 proto udp comment "niyantrak-bootstrap mDNS"
  done
  sys ufw --force enable
}

step_motd() {
  put "$R/etc/update-motd.d/10-niyantrak" 0755 "$(render_motd)"
}

step_setup_code() {
  [[ $ROLE == control ]] || { log "setup code: not needed on role $ROLE"; return 0; }
  if [[ -f $STATE/setup-code.expires ]] && [[ $(date +%s) -lt $(cat "$STATE/setup-code.expires") ]]; then
    log "setup code: still valid (shown at first run on the console)"; return 0
  fi
  local code   # no tr|head on /dev/urandom: with pipefail its SIGPIPE ends the script
  code=$(python3 -c 'import secrets; a="ABCDEFGHJKLMNPQRSTUVWXYZ23456789"; c="".join(secrets.choice(a) for _ in range(9)); print(c[:3]+"-"+c[3:6]+"-"+c[6:])')
  put "$STATE/setup-code.sha256" 0600 "$(printf '%s' "$code" | sha256sum | cut -d' ' -f1)"
  put "$STATE/setup-code.expires" 0644 "$(( $(date +%s) + 1800 ))"
  if [[ $DRY == 0 ]]; then
    printf '\n  vPanel setup code: %s   (valid 30 minutes; shown only here)\n\n' "$code"
    [[ $TESTMODE == 0 ]] && printf 'vPanel setup code: %s (valid 30 min)\n' "$code" > /dev/console 2>/dev/null || true
  fi
}

step_report() {
  put "$STATE/report.json" 0644 "$(printf '{"version": "%s", "role": "%s", "node_id": "%s", "admin": "%s", "steps": "%s", "finished": "%s"}' \
    "$VERSION" "$ROLE" "$(cat "$ETC/node-id" 2>/dev/null || echo unknown)" "$(admin_user)" "${STEPS[*]}" "$(date -Is)")"
}

main() {
  log "niyantrak-bootstrap $VERSION role=$ROLE dry_run=$DRY"
  local i=0 s
  for s in "${STEPS[@]}"; do
    i=$((i + 1))
    [[ $i -lt $FROM ]] && continue
    if [[ $s != preflight ]] && done_step "$s"; then log "step $i $s: already done"; continue; fi
    log "step $i $s"
    "step_${s//-/_}"
    [[ $s == preflight ]] || mark "$s"
  done
  log "bootstrap finished"
}

[[ ${NIYANTRAK_BOOTSTRAP_SOURCE_ONLY:-0} == 1 ]] || main
