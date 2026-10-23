# Roadmap

| Stage | What | Status |
|---|---|---|
| 1. Nodes | stock Ubuntu → hardened, audited node in one script; isolated install lab | **available (free)** |
| 2. Data | identifier detection with checksums; redact-and-reclaim gateway | detection **available (free)**; gateway in pilots |
| 3. Panel | fleet, bots, approvals, audit chain, decisions; brand kit per client | in build |
| 4. Agents | one rule book compiled into Claude Code / Codex / Gemini / OpenCode policies; governance-officer approvals | in build |
| 5. Provisioning | panel provisions nodes automatically: bootstrap → join → reconciler (Python + shell today) | in build |
| 6. Scale-out | the same desired state on **k3s / Kubernetes** for multi-node GPU fleets; **NVIDIA NIM** model serving behind the governed gateway | planned |
| 7. Windows | signed installer for developer laptops joining the governed fleet | PowerShell join (windows/join.ps1, docs/WINDOWS.md) done; signed installer planned |
| 8. Cloud | ready-made images for Indian clouds (E2E Networks, Yotta, AWS/Azure India regions) | planned |

Also planned, across stages:

| Item | What | Status |
|---|---|---|
| Configurable log retention | keep 5W activity, gate logs and the decision log for a set period per law, then compact or delete on schedule: at least 6 months for EU AI Act deployer logs, 1 year under India's DPDP Rules, 180 days for CERT-In (minimums; your lawyer sets the actual period). Today the free stores grow until you remove them — see [compliance/README.md](compliance/README.md) | planned |

Design rule for every stage: personal data never needs to leave your premises, and every change is approved and recorded.
