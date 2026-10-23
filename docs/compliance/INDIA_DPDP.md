# India: DPDP Act, DPDP Rules and CERT-In Directions

> **Not legal advice.** Our own reading as of 23 October 2026. "DPDP-ready" means a tool helps you meet your
> obligations; it does not make an organisation compliant. Check your case with your lawyer or CA.

India is one region among several that Niyantrak supports; the same features map to GDPR, the EU AI Act and others
(see [README.md](README.md)). This page covers the Indian rules because Niyantrak's detection includes Indian
identifiers (Aadhaar, PAN, GSTIN, UPI id, IFSC, Indian phone, ABHA) and because India's rules name masking and logs
explicitly.

## The rules in one paragraph each

**Digital Personal Data Protection Act, 2023 (DPDP Act).** Applies to digital personal data processed in India, and to
processing outside India connected with offering goods or services to people in India. A business that decides why and
how personal data is used is a **Data Fiduciary**. Duties include notice, consent or another lawful use, reasonable
security safeguards, breach intimation, erasure when the purpose is served, and grievance handling. Some fiduciaries
may be notified as **Significant Data Fiduciaries (SDFs)** with extra duties. There is no exemption based on size.

**DPDP Rules, 2025.** Notified on 13 November 2025 and published in the Gazette on 14 November 2025. They phase in:
board rules at once, consent managers after one year, and most duties after eighteen months.

**CERT-In Directions, 28 April 2022.** Issued under section 70B(6) of the IT Act, 2000. They apply to service
providers, intermediaries, data centres, body corporates and government organisations, and cover cyber incidents,
not only personal data.

**Sources (official)**
- DPDP Act, 2023: <https://www.meity.gov.in/static/uploads/2024/06/2bf1f0e9f04e6fb4f8fef35e82c42aa5.pdf>
- DPDP Rules, 2025 (G.S.R. 846(E)): <https://www.meity.gov.in/static/uploads/2025/11/53450e6e5dc0bfa85ebd78686cadad39.pdf>
- MeitY data protection framework page: <https://www.meity.gov.in/data-protection-framework>
- PIB note on the Rules (17 Nov 2025): <https://static.pib.gov.in/WriteReadData/specificdocs/documents/2025/nov/doc20251117695301.pdf>
- CERT-In Directions (28 Apr 2022): <https://www.cert-in.org.in/PDF/CERT-In_Directions_70B_28.04.2022.pdf>

The Act, the Rules and the CERT-In Directions were downloaded from these addresses and the provisions below were read
from them on 23 October 2026.

## Dates

| Date | What | Source |
|---|---|---|
| 27 Jun 2022 | CERT-In Directions effective (60 days after issue) | Directions, final para |
| 14 Nov 2025 | Rules 1, 2 and 17–21 (Data Protection Board) in force | Rule 1(2) |
| **13 Nov 2026** | Rule 4 (Consent Managers) in force — one year after publication | Rule 1(3) |
| **13 May 2027** | Rules 3, 5–16, 22, 23 in force — eighteen months after publication: notice, security safeguards, breach intimation, erasure, children's data, SDF duties, rights, transfers | Rule 1(4) |
| 7 Oct 2026 | DPDP (Removal of Difficulties) Order, 2026 published: clarifies section 9(1) (children and persons with disabilities) and "data audit" for SDFs in section 10(2) | Gazette; reported by SCC Online and others. **Official URL not verified.** |

MeitY consulted industry in January 2026 on cutting the 18-month period to 12 months. As of 23 October 2026 we found
no notified amendment, and secondary sources report a Lok Sabha written answer of 12 August 2026 confirming the
May 2027 date (**not verified against the Lok Sabha record**). Re-check before relying on the date.

The exact day count from "publication" (13 or 14 November) is a legal question; most commentators use 13 May 2027.

## DPDP mapping

Status: **Helps** (free edition, code here) · **Partial** · **Commercial** (not in this repository) · **Yours**.

| Provision | What it asks (short) | Niyantrak | Status |
|---|---|---|---|
| s. 4–7 Lawful processing, notice, consent | Process only for a lawful purpose with notice and consent or a legitimate use | `why` on every 5W event records the purpose of each flow. Notice and consent are yours. | Partial |
| s. 8(4) Technical and organisational measures | Measures to ensure effective observance | Agent gate, node hardening, records. | Partial |
| **s. 8(5) + Rule 6(1)(a)** | Reasonable security safeguards, "at the minimum" including **"encryption, obfuscation, masking or the use of virtual tokens mapped to that personal data"** | Free: `niyantrak scan` finds identifiers and shows placeholders. Commercial: the redact-and-reclaim gateway replaces identifiers with placeholders mapped to the real values (virtual tokens) before a model call. | Detection: Helps. Masking in the live path: Commercial (in pilots) |
| Rule 6(1)(b) | Control access to computer resources | Agent gate denies credential-file reads and production changes by AI agents; panel on loopback; signed join. | Partial |
| **Rule 6(1)(c)** | **"Visibility on the accessing of such personal data, through appropriate logs, monitoring and review"** | 5W events (who, whom, what, where, why, counts of identifier types) and the Activity view; tamper-evident store. | Partial — covers flows that send events to Niyantrak |
| Rule 6(1)(e) | Keep such logs and personal data for **one year** for detection and investigation, unless another law requires otherwise | Logs stay on your machines; no retention setting. | Partial — set one-year retention yourself |
| Rule 6(1)(f) | Security clauses in contracts with Data Processors | `where` / `route` record which processor (model provider) got each request. Contracts are yours. | Partial |
| **s. 8(6) + Rule 7** | Intimate each affected person and the Board without delay; detailed report to the Board **within 72 hours** | Records to reconstruct what data went where. Intimation is yours. | Partial |
| s. 8(7), 8(8) + Rule 8 | Erase data when the purpose is served; notify 48 hours before erasure for listed classes; keep processing logs at least one year (Rule 8(3)) | Free edition never stores values. Reclaim map expiry and erasure: Commercial. | Partial / Commercial |
| s. 8(9), 8(10) | Publish a contact; grievance redressal | Not addressed. | Yours |
| s. 9 Children's data | Verifiable parental consent; no tracking or targeted ads | Not addressed. | Yours |
| s. 10 + Rule 13 SDFs | DPO, independent data auditor, annual DPIA and audit; due diligence on algorithmic software; localisation for notified data | Data-flow facts for the DPIA and audit; local-only routing (commercial) can keep notified data in India. | Partial / Commercial |
| s. 11–14 + Rule 14 Rights | Access, correction, erasure, grievance, nomination | No values stored by free tools; nothing to return or erase there. | Partial |
| s. 16 + Rule 15 Transfers outside India | Allowed unless restricted by notification; Government may set requirements | Commercial local-only routing keeps chosen data on your machines in India. | Commercial |

**Penalties (Schedule to the Act):** up to ₹250 crore for failing to take reasonable security safeguards (s. 8(5));
up to ₹200 crore for failing to give breach notice (s. 8(6)); up to ₹200 crore for children's-data duties; up to
₹150 crore for SDF duties; up to ₹50 crore for other breaches.

## CERT-In Directions mapping

| Direction | What it asks | Niyantrak | Status |
|---|---|---|---|
| (i) Clock sync | Sync ICT clocks to NIC/NPL NTP or traceable sources | Events stored in UTC. NTP setup is yours. | Yours |
| (ii) Incident reporting | Report listed cyber incidents to CERT-In **within 6 hours** of noticing them | Gate and 5W records help answer "what happened, on which machine, by which agent". Reporting is yours. | Partial |
| (iv) Logs | Enable logs of all ICT systems; keep them securely for a **rolling 180 days**, **within Indian jurisdiction**; give them to CERT-In on request | Gate logs, 5W store and bootstrap auditd rules are kept on your own machines, so you control where they are. No retention setting. | Partial — keep 180 days (CERT-In) and one year (DPDP Rule 6(1)(e)), whichever is longer for your case |

## Indian identifiers Niyantrak detects

| Identifier | Check | Code |
|---|---|---|
| Aadhaar | Verhoeff checksum | `niyantrak/recognizers.py` (`india` pack) |
| PAN | Format and entity-type character | `india` |
| GSTIN | Check character | `india` |
| IFSC | Format | `india` |
| UPI id | Format | `india` |
| Indian mobile | Format | `india` |
| ABHA number and ABHA address | Format | `health` pack |

## Limits

- Masked data you can re-identify is still personal data under the DPDP Act.
- The free edition does not sit in the path of live model calls.
- No consent manager, notices, grievance or children's-data features.
- Names and addresses in free text are not detected by the free edition.

## Related

[README.md](README.md), [GDPR.md](GDPR.md), [OTHER_REGIONS.md](OTHER_REGIONS.md).
