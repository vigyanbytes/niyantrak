# Other regions: UK, United States, Singapore, Brazil

> **Not legal advice.** Short notes as of 23 October 2026. Each region's rules have more detail than shown here.

The same three needs — keep only the data you need, control what AI systems may do, keep records you can show — run
through every regime below. Niyantrak's features map the same way as in [GDPR.md](GDPR.md) and
[EU_AI_ACT.md](EU_AI_ACT.md); this page notes what is different.

## United Kingdom

- **Law:** UK GDPR and the Data Protection Act 2018, as amended by the **Data (Use and Access) Act 2025**. Its data
  protection changes are all in force as of 19 June 2026; it widens when solely automated decisions are allowed, with
  safeguards (information, representations, human intervention, contest). Maximum fine £17.5 million or 4% of
  worldwide turnover.
- **AI guidance:** the ICO's *Guidance on AI and data protection* treats AI as generally high-risk: assess risk, and
  apply security and data minimisation measures.
- **Niyantrak:** UK National Insurance number and NHS number (mod-11 checksum) detection; minimisation and records as
  for GDPR. UK GDPR jurisdiction profile: Commercial.
- **Sources:** ICO AI guidance <https://ico.org.uk/for-organisations/uk-gdpr-guidance-and-resources/artificial-intelligence/guidance-on-ai-and-data-protection/about-this-guidance/>;
  ICO on security and minimisation in AI <https://ico.org.uk/for-organisations/uk-gdpr-guidance-and-resources/artificial-intelligence/guidance-on-ai-and-data-protection/how-should-we-assess-security-and-data-minimisation-in-ai/>;
  DUAA 2025 <https://www.legislation.gov.uk/ukpga/2025/18>; GOV.UK summary <https://www.gov.uk/guidance/data-use-and-access-act-2025-data-protection-and-privacy-changes>.

## United States

No single federal privacy or AI law; state laws and sector rules apply.

- **State privacy laws.** California's CCPA as amended by the CPRA is the broadest. New CPPA regulations took effect
  1 January 2026: risk assessments for certain processing (including some uses of automated decision-making
  technology) from 2026, with attestations due by 1 April 2028; ADMT duties for significant decisions from 1 January
  2027. Many other states have comprehensive privacy laws with similar minimisation and security duties.
  Source: <https://cppa.ca.gov/regulations/ccpa_updates.html>.
- **State AI laws.** Colorado's AI Act (SB 24-205) was set to take effect 30 June 2026; a federal court blocked
  enforcement in April 2026 and a replacement bill was introduced in May 2026. **Status as of today unverified —
  check before citing.**
- **Health (HIPAA).** The Security Rule requires audit controls that record and examine activity in systems holding
  electronic protected health information (45 CFR 164.312(b)). Source:
  <https://www.ecfr.gov/current/title-45/subtitle-A/subchapter-C/part-164/subpart-C/section-164.312>.
  Note: reversible masking is **not** HIPAA de-identification (45 CFR 164.514).
- **Financial (GLBA Safeguards Rule).** Financial institutions under FTC jurisdiction need a written security
  programme, including monitoring and logging of authorised users' activity (16 CFR Part 314). Source:
  <https://www.ecfr.gov/current/title-16/chapter-I/subchapter-C/part-314>.
- **Niyantrak:** US SSN, NPI (Luhn) and Medicare MBI detection; agent gate and records support audit-control and
  logging duties. HIPAA and US state profiles in the rule book: Commercial.

## Singapore

- **Law:** Personal Data Protection Act 2012 (PDPA), enforced by the PDPC.
- **AI governance (voluntary):** IMDA's **Model AI Governance Framework for Generative AI** (30 May 2024; nine
  dimensions) and the **Model AI Governance Framework for Agentic AI** (22 January 2026), which asks organisations to
  bound agent risks up front, keep humans meaningfully accountable, apply technical controls and enable end-user
  responsibility. It names risks such as unauthorised and erroneous actions and data breaches.
- **Niyantrak:** the agent gate is a technical control that bounds what agents may do and records each decision.
  No Singapore-specific identifiers (such as NRIC) are detected yet.
- **Sources:** Agentic AI framework <https://www.imda.gov.sg/resources/press-releases-factsheets-and-speeches/press-releases/2026/new-model-ai-governance-framework-for-agentic-ai>;
  GenAI framework <https://aiverifyfoundation.sg/resources/mgf-gen-ai/>.

## Brazil

- **Law:** Lei Geral de Proteção de Dados Pessoais (LGPD), Law No. 13.709/2018, enforced by the ANPD. Principles
  include necessity (minimisation) and security; Art. 48 requires notice of security incidents that may cause
  relevant risk or harm.
- **Incident rule:** ANPD Resolution CD/ANPD No. 15/2024 sets notice to the ANPD and data subjects within **3 working
  days** of knowing of the incident (doubled for small agents).
- **Niyantrak:** minimisation and records as for GDPR. No Brazilian identifiers (such as CPF) are detected yet.
- **Sources:** LGPD <https://www.planalto.gov.br/ccivil_03/_ato2015-2018/2018/lei/l13709.htm>; ANPD
  <https://www.gov.br/anpd/>. The resolution number and deadline come from law-firm summaries and are **unverified
  against the ANPD text**.

## Gaps we know about

Identifier packs today: India, EU (IBAN), UK, US, global (email, card, phone) and health. Singapore NRIC, Brazil
CPF and many national ids are not yet covered. Contributions welcome.
