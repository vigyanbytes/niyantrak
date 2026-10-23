#!/usr/bin/env bash
# verify-and-run.sh <url> <sha256> [args...]
# S-1: download a script, run it ONLY if its sha256 equals the published value; otherwise refuse and run nothing.
# Used in front of every `curl ... | bash` style step (first-node bootstrap, join.sh).
#   exit 2 = bad arguments, 3 = hash mismatch (nothing executed), 4 = download failed.
# https only; file:// is accepted only when NIYANTRAK_VERIFY_ALLOW_FILE=1 (unit tests).
set -euo pipefail
url=${1:-}
want=${2:-}
[[ -n $url && -n $want ]] || { echo "usage: verify-and-run.sh <url> <sha256> [args...]" >&2; exit 2; }
shift 2
want=${want,,}
[[ $want =~ ^[0-9a-f]{64}$ ]] || { echo "refused: expected sha256 must be 64 hex characters" >&2; exit 2; }
case $url in
  https://*) ;;
  file://*) [[ ${NIYANTRAK_VERIFY_ALLOW_FILE:-0} == 1 ]] || { echo "refused: file:// only in tests" >&2; exit 2; } ;;
  *) echo "refused: only https:// URLs" >&2; exit 2 ;;
esac

tmp=$(mktemp)
trap 'rm -f "$tmp"' EXIT
if [[ $url == file://* ]]; then
  cp -- "${url#file://}" "$tmp" || { echo "download failed: $url" >&2; exit 4; }
else
  curl -fsSL --proto '=https' --tlsv1.2 -o "$tmp" -- "$url" || { echo "download failed: $url" >&2; exit 4; }
fi

got=$(sha256sum "$tmp" | cut -d' ' -f1)
if [[ $got != "$want" ]]; then
  echo "refused: sha256 mismatch for $url" >&2
  echo "  expected $want" >&2
  echo "  got      $got" >&2
  exit 3
fi
echo "verified: $url ($got)" >&2
bash "$tmp" "$@"
