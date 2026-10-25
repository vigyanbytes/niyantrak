# Niyantrak

[![CI](https://github.com/vigyanbytes/niyantrak/actions/workflows/ci.yml/badge.svg)](https://github.com/vigyanbytes/niyantrak/actions/workflows/ci.yml)
[![License: Apache-2.0](https://img.shields.io/badge/license-Apache--2.0-blue.svg)](LICENSE)
[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-3776AB.svg?logo=python&logoColor=white)](pyproject.toml)
[![Status: alpha](https://img.shields.io/badge/status-alpha%20v0.1.1-E8821A.svg)](CHANGELOG.md)

**Use any AI. Expose no one. Prove everything.**

Niyantrak is **enterprise AI governance**, for security, platform, compliance and IT-admin teams. Your organisation
wants to use any model and any coding agent, but every prompt can carry a customer's national ID, card or phone
number, and every agent can run a command nobody approved. Niyantrak sits in between, on infrastructure you own: it
takes personal data out before a model sees it, stops dangerous agent actions, and records every decision as
evidence you can query.

**This repository is the open evaluation edition (Apache-2.0)**: inspect the code, run a trial without a purchase
order, and use it as the reference implementation of the 6W record. The governance features an organisation runs
in production come in the [Pro / Enterprise / Government editions](#pro--enterprise--government-commercial)
(commercial, in build and lab validation). There is no consumer or home edition.

- **Expose no one**: checksum-validated detection of identifiers from India, the EU, the UK, the US and global
  formats; a model receives placeholders, never the values.
- **Stop what should not run**: one agent gate with hard stops for Claude Code, Codex, Gemini CLI, OpenCode and
  Antigravity (destructive commands, credential files, production changes). In this evaluation edition it installs
  at user level, for evaluation only: a seatbelt, not a sandbox.
- **Prove everything**: every action becomes a **6W (who, whom, what, where, why, which) + when** event in a
  tamper-evident store, answerable in plain words with the exact SQL shown. This release: 801 tests passed,
  89.2% line coverage, leak scan clean ([proof/latest](proof/latest/index.html)).

> **What this edition is.** The open evaluation edition for enterprise security and platform teams. Its agent gate
> installs at user level, for evaluation only — a seatbelt, not a sandbox: a user could remove it. Organisation-wide
> enforcement uses admin-managed settings deployed by IT (Intune, Jamf, Group Policy, Fleet) and is part of the
> commercial editions, in build with lab validation next. No consumer or home edition.

> **Status: alpha (v0.1.1).** The evaluation tools in this repository work and are tested on every commit, but interfaces
> may change before 1.0. Lab-tested and ready for a first pilot; there is no pilot customer yet. Do not rely on it as
> your only control for regulated data yet. See [CHANGELOG.md](CHANGELOG.md).

![Niyantrak panel walkthrough: Try it, Overview, Fleet, Activity (6W), Decisions, Rules, Proof — sample data](docs/media/niyantrak-walkthrough.gif)

*90-second walkthrough with a fictional sample team — [watch the video (MP4)](docs/media/niyantrak-walkthrough.mp4) ·
[WebM](docs/media/niyantrak-walkthrough.webm). Everything shown is sample data from `tools/demo-data.py`.*

Built in India, for the world, by VigyanBytes Solutions Private Limited. "Niyantrak" (नियंत्रक, *controller*) is a
working name pending trademark clearance. Licence: Apache-2.0.

## 60-second quickstart

You need Python 3.10 or newer. The evaluation tools use the standard library only — nothing else is downloaded.
Not on PyPI yet: install from a clone of this repository.

**Ubuntu / Debian**
```bash
sudo apt install -y python3-venv git                 # once
git clone https://github.com/vigyanbytes/niyantrak.git && cd niyantrak
python3 -m venv .venv && .venv/bin/pip install .
.venv/bin/niyantrak scan "My Aadhaar is 2345 6789 0124, PAN ABCPE1234F, UPI ramesh@okhdfc"
.venv/bin/niyantrak panel                            # then open http://127.0.0.1:8770
```

**Windows 10/11** (PowerShell; WSL is **not** needed for the panel or the scan — not yet verified on real Windows, see [FAQ](docs/FAQ.md))
```powershell
winget install -e --id Python.Python.3.12; winget install -e --id Git.Git   # once, if missing
git clone https://github.com/vigyanbytes/niyantrak.git; cd niyantrak
py -3 -m venv .venv; .venv\Scripts\pip install .
.venv\Scripts\niyantrak scan "My Aadhaar is 2345 6789 0124, PAN ABCPE1234F"
.venv\Scripts\niyantrak panel                        # then open http://127.0.0.1:8770
```

What you should see:
```console
$ niyantrak scan "Hi, my Aadhaar is 2345 6789 0124, PAN ABCPE1234F, card 4111 1111 1111 1111. Pay ramesh@okhdfc or call +91 98450 12345."
A model would receive:
  Hi, my Aadhaar is <AADHAAR_1>, PAN <PAN_1>, card <CARD_1>. Pay <UPI_ID_1> or call <IN_PHONE_1>.

Found: AADHAAR 1, PAN 1, CARD 1, UPI_ID 1, IN_PHONE 1
```
Checksums, not guesses: an Aadhaar must pass Verhoeff, a card Luhn, an IBAN mod-97, a GSTIN its check character —
so order numbers and invoice ids are left alone. More detail: [docs/QUICKSTART.md](docs/QUICKSTART.md).

## Works with
What the **evaluation edition in this repository** works with today:

| | |
|---|---|
| **AI coding agents** (agent gate) | Claude Code, Codex, Gemini CLI, OpenCode, Antigravity — `niyantrak gate install --cli all`. Installs into user-level settings and hooks, which that user can remove: for evaluation only, not organisation-wide enforcement |
| **Activity ingest** (6W sink) | OpenTelemetry: OTLP/HTTP logs in **JSON** encoding (`POST /v1/logs`); plain JSON 6W events (`POST /v1/events`, or a file with `niyantrak telemetry ingest`) — see [docs/6W.md](docs/6W.md) |
| **Operating systems** | Linux: everything. Windows 10/11: scan, panel, 6W questions and decisions, without WSL (the gate installer, node bootstrap and joining as a node are Linux today; see [FAQ](docs/FAQ.md)). macOS: not tested |
| **Python** | 3.10 – 3.13; the core uses the standard library only |
| **Storage** | local files only: Parquet + DuckDB for 6W (`[telemetry]` extra); append-only JSONL segments with a manifest for decisions |

What organisations run in production (IT-managed enforcement, the redact-and-reclaim gateway, the rule book,
evidence packs, approvals, the fleet console) is in the commercial editions, which are in build and lab validation
and not in this repository: see [Pro / Enterprise / Government](#pro--enterprise--government-commercial).

## Screenshots
The panel (`niyantrak panel`) showing a **fictional sample team** — asha, ravi, meera and tomas using Claude Code,
Codex and Antigravity on six machines for two weeks. The data is generated by `tools/demo-data.py` (fixed seed),
written through the real 6W store and decision log, and every screen is labelled *Sample data*. Recorded headlessly by
`tools/record-demo.py`; the test run keeps its own copies in [proof/latest](proof/latest/index.html).

| Try it — what a model would receive | Overview — governance checks and what was caught |
|---|---|
| ![Try it](docs/media/screens/try.png) | ![Overview](docs/media/screens/overview.png) |
| **Fleet — machines and join approvals** | **Activity (6W) — who, which agent, which project, what, where, why** |
| ![Fleet](docs/media/screens/fleet.png) | ![Activity](docs/media/screens/activity.png) |
| **Decisions — append-only log, derived status** | **Rule book** |
| ![Decisions](docs/media/screens/decisions.png) | ![Rules](docs/media/screens/rules.png) |
| **Proof — tests, coverage, leak scan** | |
| ![Proof](docs/media/screens/proof.png) | |

Build the same demo page yourself (needs the `[telemetry]` extra): `python3 tools/demo-data.py --out demo && python3
tools/build-demo.py demo/demo.html --bundle demo/bundle.json`, then open `demo/demo.html` in a browser.

## What is in the evaluation edition
| Tool | Command | What it does |
|---|---|---|
| Identifier scan | `niyantrak scan` | India, EU, UK, US and global identifiers, checksum-validated; prints placeholders, never values |
| Web panel | `niyantrak panel` | Try-it screen, machine checks, fleet and join approvals, activity, decisions, as-built docs, proof |
| Agent gate | `niyantrak gate install --cli all` | hard stops for Claude Code, Codex, Gemini CLI, Antigravity and OpenCode: destructive commands, credential files, production changes |
| Join flow | `niyantrak panel --join-bind <addr>` | single-use token + card signed with the machine's SSH host key, over TLS pinned by fingerprint; operator approves |
| Decisions | `niyantrak decisions open` | append-only decision log; status derived, never edited in place |
| As-built docs | `niyantrak docs generate` | Markdown/HTML pages and a network map from node cards — same facts, byte-identical output |
| 6W activity | `niyantrak telemetry …` | **6W (who, whom, what, where, why, which) + when** events with counts only — `which` is the project / repo, filled by the agent gate from git; tamper-evident store (`[telemetry]` extra) |
| 6W questions | `niyantrak telemetry ask "who ran destructive commands this week"` | plain-word question → the exact SQL → the answer; or `telemetry sql "SELECT …"`; table, CSV, JSON, Markdown, Parquet |
| Node bootstrap | `sudo bash bootstrap/niyantrak-bootstrap.sh --dry-run` | stock Ubuntu → hardened, audited node, with lock-out guards and resume (Linux only) |

How the pieces fit: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md). Common questions: [docs/FAQ.md](docs/FAQ.md).
Event format: [docs/6W.md](docs/6W.md). Asking the record questions in SQL: [docs/QUERYING_6W.md](docs/QUERYING_6W.md).
Security mapping to the OWASP LLM Top 10 (2025) and agentic AI threats: [docs/OWASP.md](docs/OWASP.md).
How the features relate to the EU AI Act, GDPR, ISO/IEC 42001 and 27001, NIST AI RMF, India's DPDP Act and other
regions (not legal advice): [docs/compliance/README.md](docs/compliance/README.md). Roadmap: [docs/ROADMAP.md](docs/ROADMAP.md). Launch status: [docs/LAUNCH_CHECKLIST.md](docs/LAUNCH_CHECKLIST.md).

Optional extras: `pip install ".[discovery]"` (mDNS, zeroconf), `".[telemetry]"` / `".[decisions]"` (pyarrow + duckdb),
`".[all]"`, `".[dev]"` (pytest, coverage, build).

## Ask the record questions
```console
$ niyantrak telemetry ask "Who ran destructive commands this week?" --as-of 2026-10-23
who    agent        machine       attempts  blocked  rules
-----  -----------  ------------  --------  -------  -----------------------------------------------
ravi   Codex        build-01      3         3        git.clean_force, git.force_push, git.reset_hard
asha   Codex        build-01      2         2        docker.data_loss, fs.rm_protected
meera  Claude Code  laptop-meera  1         1        git.history_rewrite
tomas  Codex        build-01      1         1        fs.rm_protected
(4 rows)
```
The SQL it ran is printed above the answer (shortened here), so every answer can be checked and re-run. No AI model is
involved, and queries are read-only. Thirteen questions with their SQL and real output: [docs/QUERYING_6W.md](docs/QUERYING_6W.md).

## Security: OWASP mapping
[docs/OWASP.md](docs/OWASP.md) maps Niyantrak to the **OWASP Top 10 for LLM Applications (2025)** and the **OWASP
Agentic AI threats (T1–T15)** with an honest *covered / partial / not yet* for each, plus a reading list. The short
version: no item is fully covered by the evaluation edition; it gives hard limits and evidence for part of sensitive-data
disclosure (LLM02), excessive agency (LLM06), tool misuse, privilege compromise, repudiation, identity spoofing and
unexpected code execution (T2, T3, T8, T9, T11). Prompt-injection detection and resource limits are not there yet.

Laws and standards: [docs/compliance/](docs/compliance/README.md) maps the same features to the EU AI Act, GDPR,
ISO/IEC 42001 and 27001, the NIST AI RMF, India's DPDP Act and Rules with CERT-In, and the UK, US, Singapore and
Brazil, with *helps / partial / commercial / roadmap / yours* for each duty. It is our own reading, not legal advice.

## Pro / Enterprise / Government (commercial)
The paid editions are what an organisation runs in production. **None of the items below ships yet**; each is marked
honestly as *in build* or *in lab validation*. They are not in this repository. For a pilot, write to
**info@vigyanbytes.com**.

| Will be available in the paid editions | Status |
|---|---|
| **IT-managed enforcement**: the agent gate and policy delivered as admin-managed settings by IT (Intune, Jamf, Group Policy, Fleet), which a governed user cannot change or remove | in build; lab validation next |
| **Redact-and-reclaim gateway**: personal data masked before any model call and restored in the reply (multi-turn, encrypted map with expiry and erasure), with local-only routing for sensitive data | in lab validation (ready for a first pilot; no pilot customer yet) |
| **Rule book** in plain words, compiled to policy engines (for example the Microsoft Agent Governance Toolkit, OPA, Cedar) and to the gateway | in build |
| **Evidence packs** that map to the OWASP Top 10 for LLM Applications and agentic threats, India's DPDP Act, the EU AI Act, GDPR, ISO/IEC 42001 and 27001, and the NIST AI RMF ("maps to", never "compliant") | in build |
| **Approvals with separation of duties**: governance-officer roles, no self-approval, signed approvals | in build |
| **Fleet console**: every machine, agent and decision in one read-only governance view | in build |
| **Per-connection SSH key governance** across the fleet (built on the open-source [niyantrak-keys](https://github.com/vigyanbytes/niyantrak-keys)) | in build |

## Editions & licensing
| | **Evaluation** (this repo, Apache-2.0) | **Pro / Enterprise / Government** (commercial) |
|---|---|---|
| `niyantrak scan`: identifier detection with checksums (India, EU, UK, US, global) | ✅ | ✅ |
| Panel: try-it, machine checks, fleet join + approval, activity, decisions, docs, proof | ✅ single operator, local | in build: multi-user, self-hosted or air-gapped |
| Agent gate: hard stops for AI coding agents | ✅ user-level install, for evaluation (a seatbelt, not a sandbox) | in build: IT-managed enforcement |
| 6W activity record and plain-word questions | ✅ reference implementation | ✅ |
| Node bootstrap: stock Ubuntu → hardened, audited node | ✅ | ✅ |
| Redact-and-reclaim gateway, jurisdiction profiles, local-only routing | — | in lab validation |
| Rule book, approvals with separation of duties, evidence packs, fleet console, SSH key governance | — | in build |
| Support | community (issues) | pilot support; SLA planned |

There is **no consumer or home edition**. The evidence packs help you show how you meet your obligations; they do
not by themselves make an organisation compliant.
- **Evaluation edition**: everything in this repository is open source under **Apache-2.0**. You can use it, change
  it and redistribute it, including commercially, under the terms of `LICENSE` and `NOTICE`.
- **Pro, Enterprise and Government / on-prem** are separate commercial products under a proprietary licence. They are
  not in this repository. Contact **info@vigyanbytes.com**.
- **Contributions** are accepted under Apache-2.0 with a DCO sign-off (`git commit -s`); there is no CLA. Because
  Apache-2.0 permits it, VigyanBytes may also use contributed code in its commercial editions. See
  [CONTRIBUTING.md](CONTRIBUTING.md).

## Proof, not promises
Test evidence is kept in the repository as files, not claims: **[proof/latest/index.html](proof/latest/index.html)**
(dashboard), `junit.xml` (every test by name and outcome), `coverage/` (line coverage), `leak-scan.txt` and
`summary.json` (date, commit, counts, coverage). `proof/history.jsonl` gains one line per run. Runs up to v0.1.0
name commits of the development history before this public repository was created from a single fresh commit;
that first public commit holds exactly the tree of the last recorded run.
```bash
pip install ".[dev]" && python3 tools/prove.py --no-screens    # re-run it: same commit, same counts
python3 tools/leak-scan.py --history                           # every blob of every commit, plus commit metadata
```
CI runs the unit suite, coverage and the leak scanner on every push and uploads `proof/latest` as an artifact.
The panel shows the same numbers under **Operate → Proof**.

## Related
- **[niyantrak-keys](https://github.com/vigyanbytes/niyantrak-keys)**: open-source SSH key rotation, one key per
  connection, in a 7-step plan-first flow that never locks you out (Rust; Linux, Windows and macOS). Its audit log
  writes the same 6W events that `niyantrak telemetry ingest` accepts.
- **[niyantrak-demo](https://github.com/vigyanbytes/niyantrak-demo)**: the read-only demo of the panel with
  fictional sample data, built from this repository; run it locally with Docker.

## Security, contributing, conduct
- Report vulnerabilities privately: [SECURITY.md](SECURITY.md). Please do not open a public issue for them.
- How to contribute: [CONTRIBUTING.md](CONTRIBUTING.md). Code of conduct: [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md).

## Licence
Apache-2.0 for everything in this repository (`LICENSE`, `NOTICE`). The commercial editions are not in this repository
and are licensed separately — see [Editions & licensing](#editions--licensing).
