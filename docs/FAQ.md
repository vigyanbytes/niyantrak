# FAQ

**What is Niyantrak, in one sentence?**
A governance layer that keeps personal data away from AI models, stops dangerous AI-agent actions, and records every
decision as evidence — on machines you own.

**Is it production-ready?**
No. v0.1.1 is **alpha**. The free tools are tested on every commit (see `proof/`), but interfaces may change before
1.0 and there has been no external security audit yet. Use it alongside your existing controls, not instead of them.

**Does it send my data anywhere?**
No. There is no telemetry to us. The only outbound calls are ones you ask for: a joining machine calls its control
node, and `niyantrak decisions ask` calls a model endpoint you configure, which must be local (it refuses
non-local hosts). The panel listens on 127.0.0.1 by default; the optional join listener serves only the join request.

**Why does `niyantrak scan` ignore a number that looks like an Aadhaar or a card?**
Because it fails the checksum (Verhoeff for Aadhaar, Luhn for cards, mod-97 for IBAN, the check character for GSTIN).
That is deliberate: order numbers and invoice ids should not be masked.

**Which identifiers are detected?**
Packs `india` (Aadhaar, PAN, GSTIN, IFSC, UPI id, Indian phone), `eu` (IBAN), `uk` (National Insurance number),
`us` (SSN), `global` (email, card, phone) and the sector pack `health`: health identifiers from every region, each
tagged with the region whose scheme issues it — US NPI (Luhn) and Medicare MBI, UK NHS number (mod 11), German
health insurance number KVNR (check digit; the number on the German EHIC), India ABHA number and ABHA address.
The EU EHIC card itself has no common number format (each country fills the fields with its own ids), so it is
covered through the national ids it carries, not as one pattern.
Run `niyantrak scan --help` and see `niyantrak/recognizers.py` for the full list.

**Does it work on Windows?**
The panel and the scan are built to, without WSL (standard-library Python; state in `%LOCALAPPDATA%\Niyantrak`).
For v0.1.x this is covered by unit tests, not yet by a run on a real Windows machine — see the launch checklist. Node bootstrap, the agent gate installer and joining
a machine *as* a node are Linux features today. A signed Windows installer is on the roadmap.

**Does it work on macOS?**
Not tested. The scan and panel are standard-library Python and are expected to work; reports welcome.

**Do I need a GPU or a local model?**
Not for anything in this repository. Local-only routing of personal data to your own GPU is part of the commercial
gateway.

**What does the free edition not include?**
The gateway that masks, routes and reclaims values on live model calls; jurisdiction profiles; the rule-book compiler;
roles, approvals and evidence packs. See the editions table in the [README](../README.md).

**Does using it make me DPDP / GDPR compliant?**
No tool does that on its own. Niyantrak helps you meet specific obligations (data minimisation, purpose, records);
compliance is about your organisation's processes too.

**The Activity / Fleet screen shows machines and events I don't have.**
Screens marked *Sample data* show built-in examples until your own data exists. Install `.[telemetry]` and send 6W
events to fill Activity; join machines to fill Fleet.

**Where is state stored? How do I reset it?**
`NIYANTRAK_STATE_ROOT` if set; else `/var/lib/niyantrak` (root or writable), else `~/.local/share/niyantrak`; on
Windows `%LOCALAPPDATA%\Niyantrak`. Stop the panel and delete that folder to reset.

**Can I put the panel behind a reverse proxy?**
Not on the same machine in the free edition: approvals are accepted only from loopback, and a local proxy would make
every caller look local. Bind it to a LAN/tailnet address you control instead.

**The agent gate blocked something I wanted to run.**
The deny message names the rule. Switch the machine to `audit` mode to log without blocking while you investigate
(`niyantrak gate status` shows the mode file). Report false positives as issues — with the rule id, not the command
if it contains anything private.

**How do I report a vulnerability?**
Privately — see [SECURITY.md](../SECURITY.md). Please do not open a public issue.

**How is "Niyantrak" pronounced, and will the name change?**
*ni-YAN-trak* (नियंत्रक, "controller"). It is a working name pending trademark clearance.
