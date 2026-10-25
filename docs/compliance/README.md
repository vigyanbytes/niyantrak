# How Niyantrak helps you meet AI and data rules

> **Not legal advice.** This folder explains how Niyantrak's features relate to laws and standards. It is our own
> assessment as of v0.1.0 (23 October 2026). Using Niyantrak does not make you compliant or certified; compliance
> depends on your organisation's processes, contracts and decisions. Talk to your own lawyer or auditor.

Niyantrak is enterprise AI governance for security, platform, compliance and IT-admin teams. This repository is the
**open evaluation edition** (Apache-2.0). Rows marked **Commercial** belong to the Pro / Enterprise / Government
editions, which are in build or in lab validation and not yet shipped. Their evidence packs will *map to* these
laws and standards; they will not make anyone compliant. There is no consumer or home edition.

## The problem, everywhere

Businesses now send customer messages to AI models and let AI agents run commands on real machines. Three things go
wrong, in every country:

1. **Personal data leaves.** A support bot forwards a whole chat, card number and phone number included, to a cloud
   model.
2. **Agents act without limits.** A coding agent deletes a data folder, reads a key file or changes a firewall.
3. **Nobody can prove what happened.** When a customer, auditor or regulator asks "who did what, with whose data, and
   why?", there is no record that can be trusted.

Almost every data-protection law and AI standard asks for the same three answers: **keep only the data you need,
control what systems may do, and keep records you can show.** Only the details change from region to region.

## What Niyantrak does about it

| Need | What Niyantrak does | Where | Edition |
|---|---|---|---|
| Know what personal data is in a message | `niyantrak scan` finds identifiers (India, EU, UK, US, global, health) with checksums and shows placeholders, never values | `niyantrak/recognizers.py` | Evaluation edition |
| Keep personal data away from cloud models | Redact-and-reclaim gateway: mask before the model, put real values back after; local-only routing for sensitive data | not in this repository | Commercial (in lab validation; ready for a first pilot) |
| Stop dangerous agent actions | Agent gate: hard stops for destructive commands, credential files and production changes, for Claude Code, Codex, Gemini CLI, Antigravity and OpenCode | `niyantrak/gate/` | Evaluation edition |
| Keep a record without creating a new privacy risk | 6W events (who, whom, what, where, why, which) with labels and counts only; tamper-evident store | `niyantrak/telemetry/` | Evaluation edition |
| Record decisions and who made them | Append-only decision log; person taken from the OS login, not typed in | `niyantrak/decisions/`, `niyantrak/identity.py` | Evaluation edition |
| Know your machines | Signed node cards, approved join over pinned TLS, as-built docs | `niyantrak/card.py`, `join.py`, `docs/` | Evaluation edition |
| Harden a server | Stock Ubuntu to hardened, audited node (auditd rules, SSH, firewall) | `bootstrap/` | Evaluation edition (Linux) |
| Rules per law, roles, approvals, evidence packs | Rule book with citations, jurisdiction profiles, roles and separation of duties, evidence packs | not in this repository | Commercial (in build) |

Details of the evaluation edition: [ARCHITECTURE.md](../ARCHITECTURE.md), [6W.md](../6W.md), [OWASP.md](../OWASP.md).

## Coverage grid

Legend: **Helps** = the evaluation edition does something concrete today, with code you can check. **Partial** = helps with
part of the duty; the page says what is missing. **Commercial** = in the Pro / Enterprise / Government editions, not in
this repository. **Roadmap** = planned. **Yours** = an organisational duty no tool can do for you.

| Duty (common to most rules) | EU AI Act | GDPR / UK GDPR | ISO/IEC 42001 | ISO/IEC 27001 | NIST AI RMF | India DPDP + CERT-In | Niyantrak status |
|---|---|---|---|---|---|---|---|
| Data minimisation before a model | Art. 10 (providers) | Art. 5(1)(c), 25 | A.7 | A 8.11, 8.12 | MEASURE 2.10 | s. 8, Rule 6(1)(a) | Detection: **Helps**. Masking in the live path: **Commercial** |
| Security safeguards | Art. 15 | Art. 32 | A.6 | A 8.2, 8.9, 8.15 | MEASURE 2.7 | s. 8(5), Rule 6 | **Partial** (gate, bootstrap, join) |
| Logs and record-keeping | Art. 12, 19, 26(6) | Art. 5(2), 30 | A.6.2.8 | A 8.15, 5.28, 5.33 | GOVERN 1.6, MEASURE 2.8 | Rule 6(1)(c),(e), Rule 8(3); CERT-In 180 days | **Partial** (6W store, decision log, gate log; no retention policy) |
| Human oversight / control of agents | Art. 14, 26(2) | Art. 22 | A.9 | A 8.2, 8.18 | MANAGE 2.4 | — | **Partial** (hard stops). Approvals: **Commercial** |
| Third parties and model providers | Art. 25, 26 | Art. 28, 44–49 | A.10 | A 5.19–5.23 | GOVERN 6.1, MANAGE 3.1 | s. 16, Rule 15 | Evidence of where data went: **Partial**. Routing: **Commercial** |
| Risk and impact assessment | Art. 9, 27 | Art. 35 | Cl. 6.1, A.5 | Cl. 6.1 | MAP | s. 10, Rule 13 | Inputs only (**Partial**); the assessment is **Yours** |
| Incident detection and reporting | Art. 26(5), 73 | Art. 33, 34 | Cl. 10 | A 5.24–5.28 | MANAGE 4.3 | Rule 7; CERT-In 6 hours | Evidence for the report: **Partial**. Reporting itself: **Yours** |
| Rights requests (access, erasure) | — | Art. 15–22 | A.8 | A 5.34 | — | s. 11–14, Rule 14 | Evaluation edition stores no values (nothing to erase). Erasure of reclaim map: **Commercial** |
| Transparency to people | Art. 50 | Art. 13, 14 | A.8 | — | GOVERN 4.2, GOVERN 5.1 | s. 5, Rule 3 | **Yours** (not addressed) |
| AI literacy / training | Art. 4 | — | Cl. 7.2, 7.3 | A 6.3 | GOVERN 2.2 | — | **Yours** |

Every row is explained, with sources, on its own page:

| Page | Covers |
|---|---|
| [EU_AI_ACT.md](EU_AI_ACT.md) | EU Artificial Intelligence Act (Regulation (EU) 2024/1689) as amended by the Digital Omnibus on AI (Regulation (EU) 2026/1744) |
| [GDPR.md](GDPR.md) | EU General Data Protection Regulation (Regulation (EU) 2016/679) |
| [ISO_42001.md](ISO_42001.md) | ISO/IEC 42001:2023, AI management system — mapping only |
| [ISO_27001.md](ISO_27001.md) | ISO/IEC 27001:2022, information security management system — mapping only |
| [NIST_AI_RMF.md](NIST_AI_RMF.md) | NIST AI Risk Management Framework (AI 100-1) and Generative AI Profile (AI 600-1) |
| [INDIA_DPDP.md](INDIA_DPDP.md) | India: Digital Personal Data Protection Act 2023, DPDP Rules 2025, CERT-In Directions 2022 |
| [OTHER_REGIONS.md](OTHER_REGIONS.md) | UK, United States, Singapore, Brazil |
| [../OWASP.md](../OWASP.md) | OWASP Top 10 for LLM Applications 2025 and OWASP Agentic AI threats |

## Honest limits

- **Alpha software.** v0.1.1; no external security audit yet. Use it alongside your existing controls.
- **The evaluation edition does not sit in the path of live model calls.** It shows what a model *would* receive; the gateway
  that masks and reclaims on real traffic is commercial.
- **Regex and checksums only** in the evaluation edition. Names, addresses and free-text health details are not detected.
- **Hard stops only.** The gate denies listed dangerous actions; everything else is allowed. No approval workflow in
  the evaluation edition.
- **No retention or deletion schedule.** The evaluation edition's stores grow until you remove them; you must set retention to match
  your law (for example one year under India's DPDP Rules, 180 days under CERT-In, "at least six months" for EU AI Act
  deployer logs).
- **Masked data is still personal data** under GDPR and DPDP when the business can reverse the mask. Masking lowers
  risk; it does not take data out of scope.
- **No certification.** Niyantrak is not certified against ISO/IEC 42001, ISO/IEC 27001 or any other scheme, and these
  pages are not an audit.

## How we keep these pages honest

Each status points to code or a document in this repository, or says the feature is commercial or on the
[roadmap](../ROADMAP.md). Each legal or standard reference links to the official source. Where we could not check a
detail against the official text we say **unverified**. ISO standards are paid documents; we cite control titles only.
Corrections are welcome as issues or pull requests.
