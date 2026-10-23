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

Design rule for every stage: personal data never needs to leave your premises, and every change is approved and recorded.
