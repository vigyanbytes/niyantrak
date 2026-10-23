# Niyantrak and the NIST AI Risk Management Framework

> **Voluntary framework; mapping only.** The NIST AI RMF is guidance, not a law, and there is no certification
> against it. This page shows which outcomes Niyantrak's features can support. Not legal advice.

## The framework in one paragraph

The US National Institute of Standards and Technology published the **AI Risk Management Framework 1.0 (NIST AI
100-1)** in January 2023 and the **Generative AI Profile (NIST AI 600-1)** in July 2024. The RMF has four functions:
**GOVERN** (culture, policies, roles), **MAP** (context and risks), **MEASURE** (analyse and track risks) and
**MANAGE** (act on risks). Each has categories and subcategories (for example MEASURE 2.10). The Generative AI Profile
lists 12 risks specific to generative AI and suggests actions for each subcategory. It is used worldwide, not only in
the US.

**Sources**
- NIST AI 100-1: <https://nvlpubs.nist.gov/nistpubs/ai/NIST.AI.100-1.pdf>
- NIST AI 600-1: <https://nvlpubs.nist.gov/nistpubs/ai/NIST.AI.600-1.pdf> (also <https://doi.org/10.6028/NIST.AI.600-1>)
- NIST AI Resource Center (playbook): <https://airc.nist.gov/>

Subcategory wording below was checked against the AI 100-1 PDF (downloaded 23 Oct 2026).

## Mapping to the four functions

Status: **Helps** (free edition) · **Partial** · **Commercial** · **Yours**.

### GOVERN

| Subcategory | Outcome (short) | Niyantrak | Status |
|---|---|---|---|
| GOVERN 1.1 | Legal and regulatory requirements are understood and documented | These compliance pages; commercial rule book links each rule to the law it serves. | Partial / Commercial |
| GOVERN 1.4 | Risk management runs through transparent policies and controls | Gate rules are named and listed (`RULES` in `niyantrak/gate/engine.py`); every deny names its rule. | Partial |
| GOVERN 1.6 | AI systems are inventoried | 5W `agent` and `route` fields, gate logs per CLI, as-built docs show which agents and models run where. | Partial |
| GOVERN 2.1 | Roles and lines of communication are documented | Identity from OS login on every decision. Roles and separation of duties: Commercial (in build). | Partial |
| GOVERN 4.3 | Practices enable testing, incident identification and information sharing | `proof/` folder per test run; tamper-evident records. | Partial |
| GOVERN 6.1 | Policies address third-party AI risks | Destinations of each request recorded (`where`, `route`). | Partial |

### MAP

| Subcategory | Outcome (short) | Niyantrak | Status |
|---|---|---|---|
| MAP 1.1 | Intended purpose and context are documented | `why` field on every 5W event; decision log. | Partial |
| MAP 3.5 | Human oversight processes are defined | Gate modes `enforce` / `audit` / `off` per machine; approvals: Commercial. | Partial |
| MAP 4.1, 4.2 | Legal and technology risks of components, including third-party AI, are mapped; internal controls documented | `niyantrak scan` shows what personal data would reach a third-party model; gate rule list documents controls. | Partial |

### MEASURE

| Subcategory | Outcome (short) | Niyantrak | Status |
|---|---|---|---|
| MEASURE 2.4 | Behaviour is monitored in production | Activity (5W) screen; `telemetry ask "who ran destructive commands this week"`. | Partial |
| MEASURE 2.7 | Security and resilience are evaluated and documented | Gate hard stops, hardened nodes, pinned-TLS join; `proof/` evidence. No adversarial testing of models. | Partial |
| MEASURE 2.8 | Transparency and accountability risks are examined | Tamper-evident records answer "who, whose data, what, where, why" with the SQL shown. | Partial |
| MEASURE 2.10 | Privacy risk is examined and documented | Counts of identifier types per flow; placeholders instead of values. | Partial |
| MEASURE 3.1 | Risks are tracked over time | Weekly series by outcome and rule in the activity view. | Partial |

### MANAGE

| Subcategory | Outcome (short) | Niyantrak | Status |
|---|---|---|---|
| MANAGE 2.4 | Mechanisms exist to supersede, disengage or deactivate AI behaviour inconsistent with intended use | Gate denies listed actions in real time, whatever the agent's instructions. | Partial |
| MANAGE 3.1 | Third-party AI risks are monitored and controlled | Masking and local-only routing to limit what a third-party model sees: Commercial. | Commercial |
| MANAGE 4.1 | Post-deployment monitoring, including override | Gate audit mode to observe; enforce to block; logs for review. | Partial |
| MANAGE 4.3 | Incidents are tracked, communicated, recovered from | Records to reconstruct incidents. No incident workflow. | Partial |

## Generative AI Profile (NIST AI 600-1): the 12 risks

| GAI risk | Relevance to Niyantrak |
|---|---|
| 1 CBRN information or capabilities | Not addressed |
| 2 Confabulation | Not addressed |
| 3 Dangerous, violent or hateful content | Not addressed |
| **4 Data privacy** | **Main focus.** Detection (free) and masking / local routing (commercial) reduce leakage of personal data to models; records hold counts only. |
| 5 Environmental impacts | Not addressed |
| 6 Harmful bias or homogenisation | Not addressed |
| **7 Human-AI configuration** | Partial: hard stops limit what agents may do unsupervised; approvals commercial. |
| 8 Information integrity | Not addressed |
| **9 Information security** | Partial: gate denies destructive, credential and production actions by agents; hardened nodes; signed join. No prompt-injection detection. |
| 10 Intellectual property | Not addressed |
| 11 Obscene, degrading or abusive content | Not addressed |
| **12 Value chain and component integration** | Partial: records which model provider received each request; no model provenance checks. |

## Limits

Niyantrak does not test models for accuracy, bias, safety or confabulation, and does not filter model output.
It addresses privacy, agent control and accountability — a slice of the RMF, not all of it.

## Related

[ISO_42001.md](ISO_42001.md), [OWASP.md](../OWASP.md), [EU_AI_ACT.md](EU_AI_ACT.md).
