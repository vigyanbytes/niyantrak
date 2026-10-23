#!/usr/bin/env bash
# fresh-machine-check -- the README quickstart on a clean Ubuntu 24.04 container, from a built wheel.
#
#   bash tools/fresh-machine-check.sh path/to/niyantrak-*.whl     # needs docker or podman; nothing installed on the host
#
# Inside the container: apt python3 + venv, pip install the wheel into a venv (Ubuntu 24.04 refuses system-wide pip,
# PEP 668), `niyantrak scan`, start `niyantrak panel`, fetch / and /api/scan. Exit 0 only if every step passes.
set -euo pipefail
whl=${1:?usage: fresh-machine-check.sh <wheel>}
[ -f "$whl" ] || { echo "no such wheel: $whl" >&2; exit 2; }
engine=$(command -v docker || command -v podman || true)
[ -n "$engine" ] || { echo "PENDING: neither docker nor podman is available" >&2; exit 3; }
dir=$(cd "$(dirname "$whl")" && pwd); name=$(basename "$whl")
"$engine" run --rm -v "$dir/$name:/tmp/$name:ro" ubuntu:24.04 bash -euo pipefail -c "
  export DEBIAN_FRONTEND=noninteractive
  apt-get update -qq >/dev/null && apt-get install -y -qq python3 python3-venv curl >/dev/null
  python3 --version
  python3 -m venv /opt/niyantrak && /opt/niyantrak/bin/pip install -q /tmp/$name
  export PATH=/opt/niyantrak/bin:\$PATH
  niyantrak --version
  echo '--- scan'
  niyantrak scan 'Hi, my Aadhaar is 2345 6789 0124, PAN ABCPE1234F, card 4111 1111 1111 1111.' | tee /tmp/scan.txt
  grep -q '<AADHAAR_1>' /tmp/scan.txt; if grep -q '2345 6789 0124' /tmp/scan.txt; then echo 'raw value printed' >&2; exit 1; fi
  echo '--- panel'
  (niyantrak panel > /tmp/panel.log 2>&1 &)
  for i in \$(seq 1 50); do curl -fs -o /tmp/index.html http://127.0.0.1:8770/ && break; sleep 0.2; done
  grep -qi '<html' /tmp/index.html; echo 'GET / -> 200, html'
  curl -fsS -X POST -H 'Content-Type: application/json' -d '{\"text\":\"PAN ABCPE1234F\"}' http://127.0.0.1:8770/api/scan
  echo; echo 'FRESH-MACHINE CHECK: PASS'
"
