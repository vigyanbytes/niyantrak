#!/usr/bin/env bash
# lab.sh -- isolated KVM lab for testing governed installation (niyantrak lab).
#
#   lab.sh check                      read-only: tools, KVM, Secure Boot firmware, budget, isolation
#   lab.sh plan                       print what `up` would do
#   lab.sh up [--apply] [--all]       network + ISO + VMs marked start:true (--all: every VM whose needs are met)
#   lab.sh status                     lab VMs, state, addresses
#   lab.sh snapshot <vm> <name> [--apply] / revert <vm> <name> [--apply]
#   lab.sh powercut <vm> [--apply]    hard power-off (test I-9)
#   lab.sh down [--apply]             power off all lab VMs
#   lab.sh destroy [--apply]          remove lab VMs, their disks and the lab network
#
# Dry run unless --apply. Touches only libvirt objects named nyklab-* and the nyklab network.
# Env: NIYANTRAK_LAB_STATE (default ~/.local/share/niyantrak-lab), NIYANTRAK_LAB_WIN_ISO, NIYANTRAK_LAB_NEEDS (comma list of
# services already built, e.g. "pxe-service,join-endpoint").
set -euo pipefail
HERE=$(cd "$(dirname "$0")" && pwd)
DEFAULT_STATE=$HOME/.local/share/niyantrak-lab
[[ -d /var/lib/niyantrak-lab ]] && DEFAULT_STATE=/var/lib/niyantrak-lab   # shared lab dataset if present
STATE=${NIYANTRAK_LAB_STATE:-$DEFAULT_STATE}
VMS="$HERE/vms.json"
NET_XML="$HERE/network.xml"
export LIBVIRT_DEFAULT_URI=${LIBVIRT_DEFAULT_URI:-qemu:///system}
APPLY=0
ALL=0
ARGS=()
for a in "$@"; do
  case $a in
    --apply) APPLY=1 ;;
    --all) ALL=1 ;;
    *) ARGS+=("$a") ;;
  esac
done
set -- "${ARGS[@]}"
CMD=${1:-help}

say() { printf '%s\n' "$*"; }
run() {  # run a changing command only with --apply
  if [[ $APPLY == 1 ]]; then say "+ $*"; "$@"; else say "would: $*"; fi
}
cfg() { python3 -c "import json,sys; d=json.load(open('$VMS')); print(eval(sys.argv[1]))" "$1"; }
PREFIX=$(cfg "d['lab']['prefix']")
NET=$(cfg "d['lab']['network']")

vm_rows() {  # name role os boot vcpus ram disk sb tpm start needs iso_env
  python3 - "$VMS" <<'PY'
import json, sys
for v in json.load(open(sys.argv[1]))["vms"]:
    print("|".join(str(v.get(k, "")) for k in
          ("name", "role", "os", "boot", "vcpus", "ram_gb", "disk_gb", "secure_boot", "tpm", "start", "needs", "iso_env")))
PY
}

ovmf_pair() {  # prints "<code> <vars>" for Secure Boot firmware, or nothing
  local d=/usr/share/OVMF
  for c in OVMF_CODE_4M.secboot.fd OVMF_CODE.secboot.fd; do
    for v in OVMF_VARS_4M.ms.fd OVMF_VARS.ms.fd; do
      [[ -f $d/$c && -f $d/$v ]] && { echo "$d/$c $d/$v"; return; }
    done
  done
}

cmd_check() {
  local bad=0 t
  for t in virsh virt-install qemu-img swtpm cloud-localds python3 curl sha256sum; do
    if command -v "$t" >/dev/null; then say "ok   tool: $t"; else say "FAIL tool: $t missing"; bad=1; fi
  done
  if [[ -r /dev/kvm && -w /dev/kvm ]]; then say "ok   kvm: /dev/kvm usable"; else say "FAIL kvm: /dev/kvm not usable by $USER (group kvm?)"; bad=1; fi
  if id -nG | tr ' ' '\n' | grep -qx libvirt; then say "ok   group: libvirt"; else say "FAIL group: $USER not in libvirt"; bad=1; fi
  if [[ -n $(ovmf_pair) ]]; then say "ok   firmware: Secure Boot OVMF ($(ovmf_pair))"; else say "FAIL firmware: Secure Boot OVMF not found (package ovmf)"; bad=1; fi
  if [[ $STATE == "$HOME"/* ]] && [[ -d /var/lib/niyantrak-lab ]]; then
    say "FAIL state: $STATE is in your home folder; the VM service cannot read disks there. Run:"
    say "     sudo install -d -o $USER -g libvirt -m 0770 /var/lib/niyantrak-lab"
    bad=1
  else
    say "ok   state: $STATE"
  fi
  python3 "$HERE/policy.py" network "$NET_XML" || bad=1
  local ram disk
  ram=$(awk '/MemAvailable/{printf "%d", $2/1048576}' /proc/meminfo)
  mkdir -p "$STATE"
  disk=$(df -BG --output=avail "$STATE" | tail -1 | tr -dc 0-9)
  python3 "$HERE/policy.py" budget "$VMS" --free-ram-gb "$ram" --free-disk-gb "$disk" || bad=1
  if command -v nvidia-smi >/dev/null && nvidia-smi --query-gpu=memory.used --format=csv,noheader >/dev/null 2>&1; then
    say "note gpu: GPU in use on this host; lab VMs do not use it (GPU tests use the simulated fixture)"
  fi
  [[ $bad == 0 ]] && say "check: ready" || say "check: NOT ready (fix the FAIL lines)"
  return $bad
}

needs_met() { [[ -z $1 ]] || [[ ",${NIYANTRAK_LAB_NEEDS:-}," == *",$1,"* ]]; }

iso_path() {  # newest verified Ubuntu ISO in STATE/iso (download + verify with --apply)
  local mirror pattern sums name
  mirror=$(cfg "d['lab']['ubuntu_mirror']"); mirror=${mirror%/}
  pattern=$(cfg "d['lab']['ubuntu_iso_pattern']")
  mkdir -p "$STATE/iso"
  sums="$STATE/iso/SHA256SUMS"
  if [[ $APPLY == 1 ]]; then
    curl -fsSL --proto '=https' -o "$sums" "$mirror/SHA256SUMS"
    curl -fsSL --proto '=https' -o "$sums.gpg" "$mirror/SHA256SUMS.gpg"
    if [[ -f /usr/share/keyrings/ubuntu-archive-keyring.gpg ]] && command -v gpgv >/dev/null; then
      gpgv --keyring /usr/share/keyrings/ubuntu-archive-keyring.gpg "$sums.gpg" "$sums" 2>/dev/null \
        && say "ok   SHA256SUMS signature" >&2 \
        || say "WARN SHA256SUMS signature not verified with the archive keyring (check the cdimage key manually)" >&2
    fi
  fi
  [[ -f $sums ]] || { say "would: download $mirror/SHA256SUMS and the ISO matching $pattern" >&2; echo "$STATE/iso/<ubuntu-iso>"; return; }
  name=$(grep -oE "${pattern//\*/[^ ]*}" "$sums" | sort -V | tail -1)
  [[ -n $name ]] || { say "FAIL no ISO matching $pattern in SHA256SUMS" >&2; return 1; }
  if [[ ! -f $STATE/iso/$name ]]; then run curl -fL --proto '=https' -o "$STATE/iso/$name" "$mirror/$name" >&2; fi
  if [[ -f $STATE/iso/$name ]]; then
    (cd "$STATE/iso" && grep " \*\?$name\$" SHA256SUMS | sha256sum -c --status) \
      || { say "FAIL ISO hash mismatch: $name (deleted)" >&2; rm -f "$STATE/iso/$name"; return 1; }
    say "ok   ISO verified: $name" >&2
  fi
  echo "$STATE/iso/$name"
}

cloudimg_path() {  # official Ubuntu cloud image, verified against its SHA256SUMS (download with --apply)
  local base=https://cloud-images.ubuntu.com/noble/current name=noble-server-cloudimg-amd64.img dir="$STATE/cloudimg"
  mkdir -p "$dir"
  if [[ $APPLY == 1 ]]; then
    curl -fsSL --proto '=https' -o "$dir/SHA256SUMS" "$base/SHA256SUMS"
    [[ -f $dir/$name ]] || curl -fL --proto '=https' -o "$dir/$name" "$base/$name" >&2
    (cd "$dir" && grep " \*\?$name\$" SHA256SUMS | sha256sum -c --status) \
      || { say "FAIL cloud image hash mismatch (deleted)" >&2; rm -f "$dir/$name"; return 1; }
    say "ok   cloud image verified: $name" >&2
  else
    say "would: download + verify $base/$name" >&2
  fi
  echo "$dir/$name"
}

net_up() {
  python3 "$HERE/policy.py" network "$NET_XML"
  if virsh net-info "$NET" >/dev/null 2>&1; then say "ok   network $NET exists"
  else run virsh net-define "$NET_XML"; run virsh net-autostart "$NET"; fi
  if [[ $(virsh net-info "$NET" 2>/dev/null | awk '/Active/{print $2}') != yes ]]; then run virsh net-start "$NET"; fi
}

vm_create() {  # one VM from a vm_rows line
  local name _role os boot vcpus ram disk sb tpm _start needs iso_env     # role, start: not used when creating
  IFS='|' read -r name _role os boot vcpus ram disk sb tpm _start needs iso_env <<<"$1"
  local dom="$PREFIX$name"
  if virsh dominfo "$dom" >/dev/null 2>&1; then say "ok   $dom exists"; return; fi
  if ! needs_met "$needs"; then say "skip $dom: needs '$needs' (not built yet; set NIYANTRAK_LAB_NEEDS when it is)"; return; fi
  local fw=() tpmopt=() install=() osinfo="ubuntu24.04"
  # let libvirt pick the firmware by feature (explicit loader paths failed: "Unable to find 'efi' firmware")
  if [[ $sb == True ]]; then
    fw=(--boot "uefi,firmware.feature0.name=secure-boot,firmware.feature0.enabled=yes,firmware.feature1.name=enrolled-keys,firmware.feature1.enabled=yes")
  else
    fw=(--boot "uefi,firmware.feature0.name=secure-boot,firmware.feature0.enabled=no")
  fi
  local diskopt=(--disk "path=$STATE/disks/$dom.qcow2,size=$disk,format=qcow2")
  [[ $tpm == True ]] && tpmopt=(--tpm "backend.type=emulator,backend.version=2.0,model=tpm-crb")
  case "$os/$boot" in
    ubuntu/iso)
      # bare-metal path: stock installer from the ISO; the installer asks "Continue with autoinstall?" once —
      # answer it on the console (`virsh console $dom`), as a person does on real hardware
      local iso seed="$STATE/seed/$name"
      iso=$(iso_path)
      if [[ $APPLY == 1 ]]; then bash "$HERE/seed/render-seed.sh" "$name" "$seed" user-data.tmpl; else say "would: render + policy-check installer seed for $name"; fi
      install=(--cdrom "$iso" --disk "path=$seed/seed.iso,device=cdrom")
      ;;
    ubuntu/cloudimg)
      # VPS-style path: official cloud image + cloud-init (boots via the signed shim, so Secure Boot stays on)
      local base seed="$STATE/seed/$name"
      base=$(cloudimg_path)
      if [[ $APPLY == 1 ]]; then bash "$HERE/seed/render-seed.sh" "$name" "$seed" cloud-config.tmpl; else say "would: render + policy-check cloud-init seed for $name"; fi
      run qemu-img create -q -f qcow2 -F qcow2 -b "$base" "$STATE/disks/$dom.qcow2" "${disk}G"
      diskopt=(--disk "path=$STATE/disks/$dom.qcow2,format=qcow2")
      install=(--import --disk "path=$seed/seed.iso,device=cdrom")
      ;;
    ubuntu/pxe) install=(--pxe) ;;
    windows/iso)
      local wiso=${!iso_env:-}
      [[ -n $wiso && -f $wiso ]] || { say "skip $dom: set $iso_env to the Windows 11 evaluation ISO (downloaded by you; licence accepted by you)"; return; }
      install=(--cdrom "$wiso"); osinfo="win11"
      ;;
  esac
  run virt-install --name "$dom" --osinfo "$osinfo" --vcpus "$vcpus" --memory $((ram * 1024)) \
    "${diskopt[@]}" --network "network=$NET" \
    "${fw[@]}" "${tpmopt[@]}" "${install[@]}" --graphics none --noautoconsole
}

cmd_up() {
  mkdir -p "$STATE/disks" "$STATE/seed"
  net_up
  while IFS= read -r row; do
    local f=(); IFS='|' read -r -a f <<<"$row"
    if [[ ${f[9]} == True || $ALL == 1 ]]; then vm_create "$row"; else say "skip $PREFIX${f[0]}: start:false (use --all)"; fi
  done < <(vm_rows)
  [[ $APPLY == 1 ]] || say "dry run: nothing changed. Re-run with --apply."
}

lab_doms() { virsh list --all --name 2>/dev/null | grep "^$PREFIX" || true; }

cmd_status() {
  local d
  for d in $(lab_doms); do
    printf '%-16s %-10s %s\n' "$d" "$(virsh domstate "$d" 2>/dev/null)" \
      "$(virsh domifaddr "$d" 2>/dev/null | awk '/ipv4/{print $4}' | head -1)"
  done
  virsh net-info "$NET" 2>/dev/null | grep -E 'Name|Active' || say "network $NET: not defined"
}

guard_vm() { [[ -n ${1:-} ]] && virsh dominfo "$PREFIX$1" >/dev/null 2>&1 || { say "unknown lab VM: ${1:-}"; exit 2; }; }

case $CMD in
  check) cmd_check ;;
  plan) APPLY=0; cmd_up ;;
  up) cmd_up ;;
  status) cmd_status ;;
  serve)  # stand-in for the public repo: serve this checkout to the lab network only, print the one-liner
    sha=$(sha256sum "$HERE/../bootstrap/niyantrak-bootstrap.sh" | cut -d' ' -f1)
    say "one-liner for a lab VM (hash-checked, so plain http on the lab bridge is fine):"
    say "  curl -fsSLo niyantrak-bootstrap.sh http://10.77.0.1:8088/bootstrap/niyantrak-bootstrap.sh && echo \"$sha  niyantrak-bootstrap.sh\" | sha256sum -c && sudo bash niyantrak-bootstrap.sh"
    say "serving $(cd "$HERE/.." && pwd) on 10.77.0.1:8088 (lab bridge only; Ctrl-C to stop)"
    exec python3 -m http.server 8088 --bind 10.77.0.1 --directory "$HERE/.."
    ;;
  snapshot) guard_vm "${2:-}"; run virsh snapshot-create-as "$PREFIX$2" "${3:?snapshot name}" ;;
  revert) guard_vm "${2:-}"; run virsh snapshot-revert "$PREFIX$2" "${3:?snapshot name}" ;;
  powercut) guard_vm "${2:-}"; run virsh destroy "$PREFIX$2" ;;
  down) for d in $(lab_doms); do [[ $(virsh domstate "$d") == running ]] && run virsh shutdown "$d"; done; true ;;
  destroy)
    for d in $(lab_doms); do
      [[ $(virsh domstate "$d") == running ]] && run virsh destroy "$d"
      run virsh undefine "$d" --nvram --remove-all-storage --snapshots-metadata --tpm
    done
    if virsh net-info "$NET" >/dev/null 2>&1; then run virsh net-destroy "$NET" || true; run virsh net-undefine "$NET"; fi
    ;;
  *) sed -n '2,16p' "$0" | sed 's/^# \{0,1\}//' ;;
esac
