# Quickstart

Ten minutes from nothing to a panel, a scan, and (optionally) a second machine joined and an AI coding agent gated.
Everything here is the free edition (Apache-2.0) and runs on your own machine.

## 0. What you need
| | Ubuntu / Debian | Windows 10/11 |
|---|---|---|
| Python | 3.10+ (`python3`, plus `python3-venv`) | 3.10+ (`py` launcher, from python.org or `winget install Python.Python.3.12`) |
| Git | `sudo apt install git` | `winget install Git.Git` |
| Admin rights | only for the node bootstrap and for joining a machine | not needed for the panel or the scan |
| WSL | — | **not needed** for the panel or the scan |

No other packages are downloaded: the free tools use the Python standard library. Optional extras are listed in step 6.

## 1. Install (from source; not on PyPI yet)
**Ubuntu**
```bash
git clone <repository URL> niyantrak && cd niyantrak
python3 -m venv .venv && . .venv/bin/activate
pip install .
niyantrak --version                     # niyantrak 0.1.1
```
**Windows (PowerShell)**
```powershell
git clone <repository URL> niyantrak; cd niyantrak
py -3 -m venv .venv; .venv\Scripts\Activate.ps1
pip install .
niyantrak --version
```
Ubuntu 24.04 refuses `pip install` outside a virtual environment (PEP 668) — that is expected; use the venv above.

## 2. Scan some text
```bash
niyantrak scan "Refund to ramesh@okhdfc, Aadhaar 2345 6789 0124, call +91 98450 12345"
niyantrak scan --file chat.txt --json            # machine-readable: types, offsets, counts, masked text
niyantrak scan --packs india,global "..."        # packs: india, eu, uk, us, health, global
```
The scan prints the text a model would receive and per-type counts. It never prints the values it found.
Numbers that fail their checksum (a mistyped Aadhaar, an order id that looks like a card) are left alone.

## 3. Open the panel
```bash
niyantrak panel                                  # http://127.0.0.1:8770 — loopback only by default
```
- **Try it** — paste a customer message, see what the model would receive.
- **Overview** — this machine's governance checks (Linux nodes after bootstrap; elsewhere they show as not set up).
- **Fleet / Add machine** — invite and approve machines (step 5).
- **Activity (6W)**, **Decisions**, **Docs**, **Proof** — see [ARCHITECTURE.md](ARCHITECTURE.md).

Screens marked *Sample data* show examples until your own data exists. State is kept in `/var/lib/niyantrak` (root),
else `~/.local/share/niyantrak`, on Windows `%LOCALAPPDATA%\Niyantrak`; `NIYANTRAK_STATE_ROOT` overrides.

## 4. Gate your AI coding agents (Linux)
```bash
niyantrak gate install --cli all --home ~        # merges a hook into Claude Code, Codex, Gemini CLI, OpenCode configs
niyantrak gate status                            # mode (enforce / audit / off), log location, where hooks are installed
niyantrak gate uninstall --cli all --home ~      # removes only what it added
```
Hard stops: destructive commands on system/data roots or home folders, reading credential files, and production
changes (services, firewalls, deployments, power). Everything else is allowed. Each decision is logged as a 6W event
with the command's sha256, not its text.

Codex runs a newly added hook only after you review and trust it in Codex ("hooks need review before they can run");
Niyantrak never marks its own hook as trusted for you. The files written for each CLI are checked against the real
CLIs in `tests/unit/test_gate_cli_formats.py` (`claude doctor`, Gemini's settings validation, Codex's own hook list,
`opencode debug config`).

## 5. Join a second machine (Linux)
On the control node:
```bash
niyantrak panel --join-bind <LAN or tailnet address>   # adds a TLS join-only listener on port 8771
```
In the panel: **Fleet → Invite a machine** gives a one-line command with a single-use token and the certificate
fingerprint. On the new machine (root is needed to read its SSH host key):
```bash
sudo python3 -m niyantrak.join https://<address>:8771 <token> --pin sha256:<fingerprint>
```
The machine appears under **Fleet** as pending until you approve it. An edited card, a wrong key or a reused token is
refused; a known machine arriving with a different host key raises an impersonation alert.

## 6. Optional extras
```bash
pip install ".[discovery]"     # find machines on the LAN over mDNS (zeroconf)
pip install ".[telemetry]"     # 6W activity store (pyarrow + duckdb); without it Activity shows sample data
pip install ".[decisions]"     # Parquet/DuckDB views for the decision log
pip install ".[dev]"           # pytest, pytest-cov, build — to run the tests and tools/prove.py
```

## 7. Harden a Linux node (optional, needs root)
```bash
sudo bash bootstrap/niyantrak-bootstrap.sh --dry-run   # every change it would make, nothing applied
niyantrak node                                         # after a real run: node status
```

## 8. Check it yourself
```bash
python3 -m pytest tests/unit -q                 # the unit suite
python3 tools/leak-scan.py --history            # secrets / private infrastructure in any commit
bash tools/fresh-machine-check.sh dist/niyantrak-0.1.1-py3-none-any.whl   # this quickstart in a clean Ubuntu 24.04 container
```

## Trouble?
See [FAQ.md](FAQ.md). Security problems: [../SECURITY.md](../SECURITY.md) — please report privately.
