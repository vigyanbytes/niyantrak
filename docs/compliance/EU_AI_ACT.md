# Niyantrak and the EU Artificial Intelligence Act

> **Not legal advice.** Our own reading as of 23 October 2026. Niyantrak does not make an AI system compliant with the
> AI Act. It provides controls and evidence that can support some obligations. Check your own role and risk class with
> a lawyer.

## The law in one paragraph

The EU AI Act sorts AI systems by risk. A few practices are banned. "High-risk" systems (for example AI used in hiring,
credit scoring, education, essential services or as a safety part of a regulated product) carry the heaviest duties.
Some systems that talk to people or generate content carry transparency duties. Companies that build
general-purpose AI models (GPAI, such as large language models) have their own duties. Most businesses that put a
chatbot or AI agent in front of customers are **deployers** of an AI system built on someone else's GPAI model, not GPAI
providers. A deployer can become a **provider** if it puts its own name on a high-risk system or substantially changes
it (Art. 25).

The Act applies to organisations outside the EU when their AI system is placed on the EU market or its output is used
in the EU (Art. 2).

**Sources**
- Regulation (EU) 2024/1689 (AI Act), official text: <https://eur-lex.europa.eu/eli/reg/2024/1689/oj/eng>
- Regulation (EU) 2026/1744 (Digital Omnibus on AI), official text: <https://eur-lex.europa.eu/eli/reg/2026/1744/oj/eng>
- Council of the EU, final adoption, 29 June 2026: <https://www.consilium.europa.eu/en/press/press-releases/2026/06/29/artificial-intelligence-council-gives-final-green-light-to-simplify-and-streamline-rules/>
- EUR-Lex summary of the AI Act: <https://eur-lex.europa.eu/EN/legal-content/summary/rules-for-trustworthy-artificial-intelligence-in-the-eu.html>

Our tools could not download the EUR-Lex pages directly (the site blocks automated fetches). Article numbers and
wording below were checked against the article-by-article reader at artificialintelligenceact.eu (unofficial, run by
the Future of Life Institute) and the Council press release. Where a detail rests only on secondary sources, it is
marked **unverified against the Official Journal**.

## When it applies

| Date | What applies | Source |
|---|---|---|
| 1 Aug 2024 | AI Act enters into force | Art. 113 |
| 2 Feb 2025 | Banned practices (Art. 5) and AI literacy (Art. 4) | Art. 113(a) |
| 2 Aug 2025 | General-purpose AI model duties (Chapter V), governance, penalties | Art. 113(b) |
| 2 Aug 2026 | Most remaining provisions, including transparency duties in Art. 50 | Art. 113 |
| 27 Jul 2026 | Digital Omnibus on AI (Regulation (EU) 2026/1744) enters into force | Council release; OJ |
| 2 Dec 2026 | New ban on AI that generates non-consensual intimate images or child sexual abuse material; end of grace period for machine-readable marking (Art. 50(2)) for systems already on the market before 2 Aug 2026 | Omnibus; Art. 50(2) grace **unverified against the Official Journal** |
| 2 Aug 2027 | GPAI models placed on the market before 2 Aug 2025 must comply (Art. 111(3)); national AI regulatory sandboxes due | Art. 111; Omnibus |
| **2 Dec 2027** | **High-risk AI systems listed in Annex III** (stand-alone high-risk uses) — moved from 2 Aug 2026 by the Omnibus | Art. 113(c) as amended |
| 2 Aug 2028 | High-risk AI that is part of a product covered by EU product law (Annex I) — moved from 2 Aug 2027 | Art. 113(c) as amended |

The Omnibus also softened the AI-literacy duty in Art. 4 to supporting AI literacy among staff (per secondary sources;
**unverified against the Official Journal**). The Commission's guidelines and harmonised standards for high-risk
systems are still being finalised; check the [AI Office](https://digital-strategy.ec.europa.eu/en/policies/ai-office)
for updates.

## Obligations and how Niyantrak maps

Status: **Helps** = free edition, code in this repository. **Partial** = helps with part; gap stated. **Commercial** =
Pro/Enterprise/Government editions, not in this repository. **Roadmap** = planned ([ROADMAP.md](../ROADMAP.md)).
**Yours** = organisational duty.

### Duties for high-risk AI systems (providers, Chapter III Section 2)

| Article | What it asks (short) | Niyantrak | Status |
|---|---|---|---|
| Art. 9 Risk management system | A continuous process to identify, assess and reduce risks over the system's life | 5W activity and the decision log give data for the process: what was blocked, which rule, how often (`niyantrak telemetry ask`). The process itself is yours. | Partial |
| Art. 10 Data and data governance | Training, validation and test data must be governed: relevance, bias, gaps, personal data | `niyantrak scan` can check data sets for identifiers before use. Niyantrak does not train models or assess bias. | Partial |
| Art. 12 Record-keeping | The system must automatically log events over its lifetime, to spot risks and support monitoring | 5W events (`niyantrak/telemetry/`): who, whom, what, where, why, outcome, rule ids, counts of personal data — never content. Store is append-only with a hash-chained manifest; `niyantrak telemetry verify` detects edits. Gate logs every allow/deny (`niyantrak/gate/events.py`). | Partial — covers the governance layer around the AI system, not the model's own internals; gate log is not hash-chained (see [OWASP.md](../OWASP.md) T8) |
| Art. 13 Transparency to deployers | Instructions for use, capabilities, limits | Not addressed (provider documentation). | Yours |
| Art. 14 Human oversight | Design so people can understand, monitor, override and stop the system | Agent gate hard stops (`niyantrak/gate/engine.py`) with modes `enforce` / `audit` / `off`; the gate blocks an agent from changing its own mode (`gate.tamper`). No approval step in the free edition. | Partial. Approvals ("needs a human"): Commercial (in build) |
| Art. 15 Accuracy, robustness, cybersecurity | Resilience to errors and attacks | Gate parses what a shell would actually run (`niyantrak/gate/shell.py`); hardened nodes (`bootstrap/`); signed node cards and pinned TLS for joins (`niyantrak/card.py`, `join.py`, `tls.py`). No prompt-injection detection. | Partial |
| Art. 19 Keeping logs (providers) | Keep automatically generated logs at least six months | Logs are kept on your machines until you delete them; no retention setting. | Partial — set retention yourself |

### Duties for deployers of high-risk AI (Art. 26, 27)

| Article | What it asks (short) | Niyantrak | Status |
|---|---|---|---|
| Art. 26(1) Use as instructed | Use the system according to the provider's instructions | Agent gate and (commercial) rule book enforce your own use rules on agents. | Partial |
| Art. 26(2) Assign human oversight | Competent, trained people with authority | Decision log records who decided, taken from the OS login (`niyantrak/identity.py`). Roles and separation of duties: Commercial (in build). | Partial |
| Art. 26(4) Input data | Input data under the deployer's control must be relevant | `niyantrak scan` shows which identifiers a prompt carries. | Partial |
| Art. 26(5) Monitor and report | Monitor operation; inform provider and authorities of serious incidents | 5W activity screen and `telemetry ask` support monitoring. Reporting is yours. | Partial |
| Art. 26(6) Keep logs | Keep logs under your control at least six months | Logs live on your machines; you choose how long. No automatic retention. | Partial |
| Art. 26(9) Data protection impact assessment | Use provider information for the GDPR Art. 35 DPIA | Data-flow facts for the DPIA: which identifier types went where (counts per type, `where` field). | Partial |
| Art. 27 Fundamental rights impact assessment | For some deployers (public bodies, credit, insurance) | Not addressed. | Yours |

### Duties that apply beyond high-risk

| Article | What it asks (short) | Niyantrak | Status |
|---|---|---|---|
| Art. 4 AI literacy | Support AI literacy of staff who use AI | Plain-language deny messages name the rule that stopped an agent; not a training programme. | Yours |
| Art. 5 Prohibited practices | Do not use banned AI practices | Not addressed. | Yours |
| Art. 50 Transparency | Tell people they are talking to an AI; mark AI-generated content | Not addressed. | Yours |
| Art. 53, 55 GPAI providers | Technical documentation, copyright policy, training-data summary; extra duties for systemic-risk models | Not applicable to most Niyantrak users (they are not model providers). | Not applicable |
| Art. 72 Post-market monitoring (providers) | Collect and analyse performance data after release | 5W store and SQL questions (`niyantrak telemetry ask`, [QUERYING_5W.md](../QUERYING_5W.md)) give a ready data source. | Partial |
| Art. 73 Serious incident reporting (providers) | Report serious incidents: no later than 15 days; 2 days for widespread or critical-infrastructure incidents; 10 days for a death | Tamper-evident records help reconstruct what happened. Reporting is yours. | Partial |

## What Niyantrak gives an AI Act file today

1. **Evidence of control over agents** — every gate decision with rule id, agent name, machine role and a sha256 of
   the command (never its text).
2. **Evidence of data minimisation** — what a model would have received, and counts of identifier types per event.
3. **Tamper-evident activity records** — `niyantrak telemetry verify` and `niyantrak decisions verify`.
4. **Who decided** — decisions stamped with the OS identity and a stable directory id.

## What it does not give (yet)

- No risk classification of your AI system; no conformity assessment, CE marking or EU database registration.
- No transparency notices, content marking or deepfake labels (Art. 50).
- No bias, accuracy or robustness testing of models.
- No human-approval workflow in the free edition.
- No retention or deletion schedule; you set it.

## Related

[GDPR.md](GDPR.md) (the AI Act does not replace GDPR), [ISO_42001.md](ISO_42001.md), [NIST_AI_RMF.md](NIST_AI_RMF.md),
[OWASP.md](../OWASP.md).
