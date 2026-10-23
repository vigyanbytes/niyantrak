# Changelog

All notable changes to the free edition. Format: [Keep a Changelog](https://keepachangelog.com/en/1.1.0/);
versions follow [Semantic Versioning](https://semver.org/) — before 1.0, minor versions may break interfaces.

## [Unreleased]

### Added
- `docs/compliance/`: how the features relate to the EU AI Act, GDPR, ISO/IEC 42001, ISO/IEC 27001, NIST AI RMF, India
  (DPDP Act, DPDP Rules 2025, CERT-In) and other regions, with honest status per duty. Not legal advice.
- Roadmap: configurable log retention (EU AI Act deployer logs at least 6 months, DPDP Rules 1 year, CERT-In 180 days).

### Fixed
- 5W store: a segment changed after the query view was built went unnoticed by `activity()`, the panel and
  `telemetry sql|ask` until the manifest changed (only `telemetry verify` saw it). The integrity check now runs on
  every query, also when the cached view is reused. Reported by the dashboard build.
- `tools/build-demo.py` and the proof reader use UTF-8 explicitly (Windows opens text as cp1252 by default).
- **Windows:** `niyantrak telemetry`, `niyantrak decisions` and the panel failed to start on Windows (`No module
  named 'pwd'`): `niyantrak/identity.py` now takes the person from the Windows logon (USERNAME, and the account SID
  from `whoami /user` as the stable id) when there is no NSS.
- `niyantrak/recognizers.py` docstring no longer refers to modules that are not in this repository.
- `windows/join.ps1` can be loaded by PowerShell on Linux and macOS (the CI tests dot-source it): state paths are
  plain strings instead of `Join-Path`, which needs the `C:` drive to exist. Behaviour on Windows is unchanged; the
  published SHA-256 in `windows/join.ps1.sha256` changes.
- `lab/lab.sh`: shellcheck clean (two fields read but not used are named `_role`, `_start`).

## [0.1.0] — 2026-10-23 — alpha

First public release of the free edition (Apache-2.0).

### Added
- **Identifier scan** — `niyantrak scan`: India (Aadhaar, PAN, GSTIN, IFSC, UPI id, phone), EU (IBAN), UK (NI number),
  US (SSN) and global (email, card, phone) packs, checksum-validated (Verhoeff, Luhn, mod-97, GSTIN check character);
  prints placeholders and per-type counts, never values; `--json`, `--file`, `--packs`.
- **Web panel** — `niyantrak panel` on 127.0.0.1:8770, standard library only: Try it, Overview (machine governance
  checks), Fleet, Add machine, Activity (5W), Decisions, Docs, Proof; Pro screens shown as previews.
- **Agent gate** — `niyantrak gate install|uninstall|status|check`: hard stops (destructive, secret, production) for
  Claude Code, Codex, Gemini CLI / Antigravity and OpenCode via each CLI's own hook; shell-aware parsing (a mention
  is not an execution); enforce / audit / off per machine; decisions logged as 5W events with command hashes.
- **Join flow** — single-use, expiring tokens (only the hash stored), node cards signed with the machine's SSH host
  key, operator approval, impersonation alerts on host-key change; TLS join-only listener with a self-signed
  certificate pinned by SHA-256 (`--join-bind`).
- **5W telemetry** — privacy-checked event schema (labels and counts only), OTLP/HTTP JSON and plain JSON sink,
  append-only Parquet store with hash-chained manifest, DuckDB queries (`[telemetry]` extra).
- **5W querying** — `niyantrak telemetry ask "<question>"` (ten plain-word questions mapped to SQL templates, no model;
  the SQL is printed with the answer) and `niyantrak telemetry sql "<SELECT …>"` over tables `ev` and `decisions`;
  read-only (in-memory copy, file and network access off, configuration locked); output as table, CSV, JSON,
  Markdown or Parquet. See `docs/QUERYING_5W.md`.
- **Sample team** — `tools/demo-data.py`: a deterministic, fictional team (Claude Code, Codex, Antigravity across six
  machines, 14 days) written through the real stores; `tools/build-demo.py --bundle` and `tools/record-demo.py`
  turn it into the demo page, screenshots and walkthrough video in `docs/media/`.
- **OWASP mapping** — `docs/OWASP.md`: OWASP Top 10 for LLM Applications 2025 and the Agentic AI threats, with an
  honest covered / partial / not yet status for each.
- **Decision log** — append-only DECISION / WORK / THING events with derived status, open items, export, local-model
  `ask` that refuses non-local endpoints.
- **As-built docs** — deterministic Markdown/HTML pages and an SVG network map from node cards and the join store.
- **Node bootstrap** — stock Ubuntu → hardened, audited node with lock-out guards, resume and `--dry-run`;
  verify-and-run; isolated install lab with network/budget policy checks.
- **Discovery** — dual-stack mDNS announce/browse (`[discovery]` extra); announcements are hints, cards are trust.
- **Proof** — test evidence kept in `proof/` per run (junit, coverage, leak scan, screenshots, history).
- **Leak scanner** — `tools/leak-scan.py` for the working tree; `--history` scans every blob of every commit on every
  ref plus commit author/committer identities and messages; `NIYANTRAK_PRIVATE_TERMS` file support.
- **Launch readiness** — `niyantrak --version`; complete package metadata and extras (`discovery`, `telemetry`,
  `decisions`, `all`, `dev`); Windows-safe state folder (`%LOCALAPPDATA%\Niyantrak`); `tools/fresh-machine-check.sh`
  (quickstart in a clean Ubuntu 24.04 container); README, quickstart, architecture, FAQ, security policy,
  contributing guide, code of conduct, issue and PR templates.

### Known limitations
- Alpha: interfaces may change; no external security audit yet.
- Windows: panel and scan only, not yet verified on a real Windows machine; bootstrap, gate installer and joining as a
  node are Linux-only.
- Free-edition panel is single-operator: approvals are accepted from loopback only.
- Not yet published to PyPI; install from source.

[Unreleased]: https://github.com/vigyanbytes/niyantrak/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/vigyanbytes/niyantrak/releases/tag/v0.1.0
