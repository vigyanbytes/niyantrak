# Niyantrak and the GDPR

> **Not legal advice.** Our own reading as of 23 October 2026. Niyantrak does not make you GDPR-compliant. It provides
> technical measures and records that can support some of your duties as a controller or processor.

## The law in one paragraph

The EU General Data Protection Regulation (Regulation (EU) 2016/679) governs any processing of personal data about
people in the EU, including by organisations outside the EU that offer them goods or services or monitor their
behaviour (Art. 3). Sending a customer's message to an AI model is processing. If the model provider is outside the
EU, it is usually also an international transfer. The UK has its own version (UK GDPR); see
[OTHER_REGIONS.md](OTHER_REGIONS.md).

**Sources**
- GDPR, official text: <https://eur-lex.europa.eu/eli/reg/2016/679/oj/eng>
- EDPB Opinion 28/2024 on AI models (18 Dec 2024): <https://www.edpb.europa.eu/our-work-tools/our-documents/opinion-board-art-64/opinion-282024-certain-data-protection-aspects_en>
- EDPB Guidelines 01/2025 on pseudonymisation: <https://www.edpb.europa.eu/system/files/2025-01/edpb_guidelines_202501_pseudonymisation_en.pdf>
- EDPB, AI Privacy Risks and Mitigations — Large Language Models (April 2025): <https://www.edpb.europa.eu/system/files/2025-04/ai-privacy-risks-and-mitigations-in-llms.pdf>

EUR-Lex blocks automated fetches, so article numbers were checked against secondary copies of the text rather than
the EUR-Lex page itself. The EDPB links were checked on 23 October 2026.

## Mapping

Status: **Helps** (free edition, code here) · **Partial** · **Commercial** (not in this repository) · **Roadmap** ·
**Yours**.

| GDPR duty | What it asks (short) | Niyantrak | Status |
|---|---|---|---|
| Art. 5(1)(b) Purpose limitation | Use data only for the purposes you collected it for | 5W events carry a `why` (the rule or reason) for every action, so each data flow has a recorded purpose. | Partial |
| Art. 5(1)(c) Data minimisation | Process only what is necessary | `niyantrak scan` shows exactly which identifiers a prompt would send and replaces them with placeholders (`<AADHAAR_1>`, `<CARD_1>`). Masking on live model traffic is in the gateway. | Detection: Helps. Live masking: Commercial (in pilots) |
| Art. 5(1)(e) Storage limitation | Keep data no longer than needed | Free tools never store message text or identifier values ([5W.md](../5W.md)). No retention schedule for the logs themselves. Reclaim map with expiry and erasure: Commercial. | Partial |
| Art. 5(2) Accountability | Be able to show compliance | Tamper-evident 5W store and decision log; proof folder with test evidence (`proof/`). | Partial |
| Art. 25 Data protection by design and by default | Build minimisation and safeguards in from the start | Privacy by design in the tools themselves: events reject free text and identifier values (`niyantrak/telemetry/schema.py`); pseudonymous session ids (HMAC with a per-store salt); gate logs a command's sha256, not its text; decision log refuses secret-shaped text (`niyantrak/decisions/schema.py`). | Helps (for the records Niyantrak keeps); Partial overall |
| Art. 28 Processors | Contracts and guarantees with processors (for example a model API provider) | `where` and `route` fields record which provider or model each request went to — evidence for your processor list. Contracts are yours. | Partial |
| Art. 30 Records of processing | A written record of processing activities | 5W activity gives an observed picture of flows (who, whose data category, what, where, why). It is input to, not a substitute for, your Art. 30 record. | Partial |
| Art. 32 Security of processing | Appropriate measures, including pseudonymisation and encryption | Agent gate (deny destructive, credential-file and production actions); node hardening (`bootstrap/`); signed machine identity and pinned TLS (`niyantrak/join.py`, `tls.py`). Pseudonymisation of prompts before a model: Commercial. | Partial |
| Art. 33, 34 Breach notification | Tell the authority within 72 hours where feasible; tell people when high risk | Tamper-evident records help answer "what data, which systems, when". Notification is yours. | Partial |
| Art. 35 DPIA | Assess high-risk processing before you start | Facts for the DPIA: identifier types and counts per flow, destinations, block rates (`niyantrak telemetry ask`). | Partial |
| Art. 15–22 Data subject rights | Access, rectification, erasure, objection, rights around automated decisions | The free edition stores no message content or identifier values, so it adds nothing to find or erase. Erasure of the encrypted reclaim map: Commercial. Handling requests is yours. | Partial |
| Art. 22 Automated decisions | Rights where decisions with legal or similar effects are made solely by automated means | Agent gate hard stops limit what agents may do on their own; approvals are commercial. Not a decision-review system. | Partial |
| Art. 44–49 International transfers | Transfers outside the EEA need adequacy, safeguards (such as standard contractual clauses) or a derogation | See below. | Partial |

## Sending prompts to a model provider outside the EU

A chat message sent to a model API in another country is a transfer of whatever personal data it contains. You need a
legal basis for the processing, a processor contract, and a transfer tool:

- **Adequacy** (Art. 45): for the United States, the EU–US Data Privacy Framework adequacy decision of 10 July 2023
  covers transfers to certified US companies. The EU General Court dismissed a challenge to it on 3 September 2025
  (*Latombe v Commission*); an appeal is possible. List of adequacy decisions:
  <https://commission.europa.eu/law/law-topic/data-protection/international-dimension-data-protection/adequacy-decisions_en>
- **Standard contractual clauses** (Art. 46) plus a transfer impact assessment, where there is no adequacy.

**How Niyantrak helps:** the less personal data in the prompt, the smaller the transfer. The commercial gateway masks
identifiers before the model call and can keep sensitive categories (cards, health, confidential) on a local model so
they never leave your premises. The free edition shows what would have been sent and records where each request went.

**What it does not change:** masked data that you can re-identify (because you keep the map) is **pseudonymised**, and
pseudonymised data is still personal data (Recital 26; EDPB Guidelines 01/2025). Masking reduces risk and supports
Art. 25 and 32; it does not by itself take a transfer out of the GDPR.

## Helping with requests from people (DSARs)

- The free edition keeps **no message text and no identifier values** — only labels, counts and hashes. There is
  usually nothing in Niyantrak's own stores to return or erase.
- Pseudonymous session ids (`p-…`) are an HMAC of the original id with a salt that never leaves the machine, so a
  record can be found if you hold the original id, but the id cannot be read back from the record.
- The commercial gateway's reclaim map has an expiry and supports erasure on request.

## Limits

- Regex and checksum detection only in the free edition: names, addresses and health details in free text are not
  found. Commercial adds optional name and place detection.
- No consent management, privacy notices or records-of-processing templates.
- Niyantrak does not decide your lawful basis.

## Related

[EU_AI_ACT.md](EU_AI_ACT.md), [ISO_27001.md](ISO_27001.md), [OTHER_REGIONS.md](OTHER_REGIONS.md) (UK GDPR).
