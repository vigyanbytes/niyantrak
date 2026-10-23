#!/usr/bin/env bash
# render-seed.sh <vm-name> <out-dir> [template] -- render the autoinstall seed for one lab VM and policy-check it.
# Creates (once) a lab-only SSH key named by the operator pattern <source>-<target>-<user>-<YYYYMMDD>.
# Writes <out-dir>/user-data, <out-dir>/meta-data and, if cloud-localds exists, <out-dir>/seed.iso.
set -euo pipefail
HERE=$(cd "$(dirname "$0")" && pwd)
VM=${1:?vm name}
OUT=${2:?out dir}
TEMPLATE=${3:-user-data.tmpl}
DEFAULT_STATE=$HOME/.local/share/niyantrak-lab
[[ -d /var/lib/niyantrak-lab ]] && DEFAULT_STATE=/var/lib/niyantrak-lab   # shared lab dataset if present
STATE=${NIYANTRAK_LAB_STATE:-$DEFAULT_STATE}
KEY="$STATE/keys/lab_admin_ed25519"
HOSTNAME_VM="nyklab-$VM"

mkdir -p "$OUT" "$STATE/keys"
chmod 700 "$STATE/keys"
if [[ ! -f "$KEY" ]]; then
  ssh-keygen -q -t ed25519 -N "" -f "$KEY" -C "$(hostname -s)-nyklab-labadmin-$(date +%Y%m%d)"
fi
PUB=$(cat "$KEY.pub")

sed -e "s|@HOSTNAME@|$HOSTNAME_VM|g" -e "s|@PUBKEY@|$PUB|g" "$HERE/$TEMPLATE" > "$OUT/user-data"
printf 'instance-id: %s-%s\nlocal-hostname: %s\n' "$HOSTNAME_VM" "$(date +%s)" "$HOSTNAME_VM" > "$OUT/meta-data"

python3 "$HERE/../policy.py" seed "$OUT/user-data"

if command -v cloud-localds >/dev/null; then
  cloud-localds "$OUT/seed.iso" "$OUT/user-data" "$OUT/meta-data"
  echo "seed: $OUT/seed.iso"
else
  echo "seed: $OUT/user-data (cloud-localds missing: install cloud-image-utils to build seed.iso)"
fi
