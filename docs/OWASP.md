# Niyantrak and the OWASP AI security lists

OWASP publishes community lists of the most important security risks for applications built on large language
models and for AI agents that act on their own. We map Niyantrak to two of them so you can see, item by item, what
the open evaluation edition (Apache-2.0) in this repository helps with today and what it does not. The status below is our own honest
assessment as of v0.1.0 (2026-10-23); it is not a certification, an audit or an endorsement by OWASP.

Niyantrak is alpha software. Use it alongside your existing controls, not instead of them (see the [FAQ](FAQ.md)).

## Legend

| Status | Meaning |
|---|---|
| **Covered** | The evaluation edition does this today. The row points to the command, file or test that shows it. |
| **Partial** | It helps with part of the risk. The row says which part is missing. |
| **Not yet** | Not in the evaluation edition today. The row says whether it is on the roadmap, in the commercial edition (not in this repository), or out of scope. |

"Evaluation edition" means everything in this repository. Where a gap is filled by the commercial edition (Pro / Enterprise /
Government; in build or in lab validation, not in this repository), we say so and do not describe it further.

## Table 1: OWASP Top 10 for LLM Applications 2025

| Item | Status | What Niyantrak does today | Gap / roadmap |
|---|---|---|---|
| LLM01 Prompt Injection | Not yet (detection); Partial (blast radius) | No prompt-injection detector. For AI coding agents, the agent gate (`niyantrak gate install --cli all`, `niyantrak/gate/engine.py`) still denies destructive commands, credential-file access and production changes whatever instruction caused them. Decisions in `niyantrak decisions ask` only go to a local endpoint (`niyantrak/decisions/ask.py`). | No input or output classifier for injected instructions. Customer-bot traffic is not inspected by the evaluation edition. |
| LLM02 Sensitive Information Disclosure | Partial | Detection: `niyantrak scan` finds Aadhaar, PAN, GSTIN, IFSC, UPI, IBAN, NINO, SSN, card, email, phone and health ids, validated by checksum (`niyantrak/recognizers.py`) and prints placeholders, never values. 6W events hold counts per type only and reject identifier values (`niyantrak/telemetry/schema.py`). The decision log refuses a batch holding a secret or identifier (`niyantrak/decisions/schema.py`). The gate logs a command's sha256, not its text (`niyantrak/gate/events.py`). | The evaluation edition detects and shows what a model would receive; it does not sit in the path of live model calls. The reversible masking gateway (mask, route, reclaim) is in the commercial edition (not in this repository). Names and free-text personal data are not detected by the regex packs. |
| LLM03 Supply Chain | Partial | The core has no runtime dependencies (`dependencies = []` in `pyproject.toml`); optional extras are named and versioned. `python3 tools/leak-scan.py --history` checks every commit for keys and private infrastructure details. Panel plugins load only through a declared entry point group (`niyantrak/plugins.py`). | No model provenance or model-file checks, no SBOM, no signed releases yet (signed Windows installer is on the roadmap). Extras use minimum versions, not a lock file. |
| LLM04 Data and Model Poisoning | Not yet | Nothing here trains or fine-tunes a model. | Out of scope for the evaluation edition. |
| LLM05 Improper Output Handling | Partial | When an AI coding agent's output becomes a shell command, the gate parses what would actually execute (`niyantrak/gate/shell.py`) and denies hard stops before it runs. Card text from other machines is treated as untrusted and escaped in generated docs (`niyantrak/docs/`). | No general sanitising of model output for web pages, SQL or other downstream systems. Commands outside the hard-stop families are allowed. |
| LLM06 Excessive Agency | Partial | Agent gate hard stops for Claude Code, Codex, Gemini CLI, Antigravity and OpenCode (`niyantrak/gate/adapters.py`, `installers.py`): `destructive`, `secret`, `production` and `governance` rule families, each deny named by a rule id (`RULES` in `niyantrak/gate/engine.py`). Per-machine modes `enforce`, `audit`, `off`; the gate denies an agent changing its own mode file (`gate.tamper`). | Only hard stops: everything else is allowed. No fine-grained permissions, per-tool allow-lists or human approval steps in the evaluation edition; a rule book compiled into agent policies with approvals is on the [roadmap](ROADMAP.md) (stage 4). |
| LLM07 System Prompt Leakage | Not yet | Nothing specific. The decision log and 6W events refuse secret-shaped text, which helps keep credentials out of records an agent can read. | No check of system prompts. Out of scope for the evaluation edition. |
| LLM08 Vector and Embedding Weaknesses | Not yet | The evaluation edition has no vector store or retrieval pipeline. | Out of scope today. |
| LLM09 Misinformation | Not yet | `niyantrak decisions ask` gives the local model only the exact matching rows from the decision log, which narrows what it can answer from. | No fact checking or grounding checks on model answers. Out of scope for the evaluation edition. |
| LLM10 Unbounded Consumption | Not yet | The 6W sink rejects request bodies over 5 MB (`niyantrak/telemetry/sink.py`). | No rate limits, token budgets or cost limits on model calls. Not on the current roadmap for the evaluation edition. |

## Table 2: OWASP Agentic AI – Threats and Mitigations (T1 to T15)

| Item | Status | What Niyantrak does today | Gap / roadmap |
|---|---|---|---|
| T1 Memory Poisoning | Not yet | The decision log is append-only: status is derived from events, never edited in place (`niyantrak/decisions/`), so a poisoned entry can be traced and retracted rather than silently overwritten. | No checks on agent memory or context content. |
| T2 Tool Misuse | Partial | The gate judges each tool call an agent makes: shell commands by what would actually execute, file tools by the paths they name (`ToolCall` in `niyantrak/gate/engine.py`). Tests: `tests/unit/test_gate_engine.py`, `test_gate_shell.py`. | Hard stops only; no allow-lists per tool or per task, no argument policies beyond the listed rules. Coding-agent CLIs only, not general agent frameworks or MCP servers. |
| T3 Privilege Compromise | Partial | `secret.path` denies agents reading credential files (`.ssh` keys, `.env`, cloud and CLI credentials, `/etc/shadow`); `prod.*` rules deny service, firewall, deploy and power changes. Panel approvals are accepted only from loopback. Node bootstrap hardens a stock Ubuntu machine (`bootstrap/`). | The gate does not reduce the privileges an agent runs with; it blocks listed actions. No roles in the evaluation edition (commercial edition, not in this repository). |
| T4 Resource Overload | Not yet | Sink body limit only (5 MB). | No resource quotas for agents or models. |
| T5 Cascading Hallucination Attacks | Not yet | Nothing specific. | Out of scope for the evaluation edition. |
| T6 Intent Breaking and Goal Manipulation | Partial (blast radius only) | No detection of goal changes. If an agent's goal is hijacked, the gate still denies the hard-stop actions. | No planning or intent validation. |
| T7 Misaligned and Deceptive Behaviors | Partial (blast radius only) | Same as T6: hard stops apply whatever the agent intends, and every gate decision, allow included, is logged. | No behaviour monitoring or anomaly detection. |
| T8 Repudiation and Untraceability | Partial | 6W store: Parquet segments with a hash-chained manifest; `niyantrak telemetry verify` reports a broken chain, missing or altered segments (`niyantrak/telemetry/store.py`). Decision log: append-only segments with a sha256 per segment in `manifest.jsonl`; `niyantrak decisions verify`. Gate: one JSON line per decision with rule id, mode and `command_sha256`. Decisions record the person from the OS login via NSS (`niyantrak/identity.py`), not typed in. The record answers questions in read-only SQL: `niyantrak telemetry ask "who ran destructive commands this week"` ([QUERYING_6W.md](QUERYING_6W.md)). | The decision manifest is per-segment sha256, not hash-chained; the gate log is plain JSONL with no chain, and records the user from `getpass` rather than the NSS identity. No external timestamping or signed evidence packs (commercial edition, not in this repository). |
| T9 Identity Spoofing and Impersonation | Partial | People: identity derived from the OS login (loginuid, then NSS: local, SSSD, authd, Kanidm), with a stable directory id (`niyantrak/identity.py`). Machines: node cards signed with the SSH host key (`niyantrak/card.py`), single-use 256-bit join tokens stored only as sha256, TLS pinned by certificate fingerprint, and a changed host key refused as possible impersonation (`niyantrak/join.py`, `tls.py`). | No identity for AI agents themselves beyond the CLI name. The 6W sink and panel API have no authentication of their own; keep them on loopback or a private address. |
| T10 Overwhelming Human in the Loop | Not yet | Hard stops deny without asking a human, so they do not add approval prompts. | No approval workflow in the evaluation edition, so nothing to tune yet. |
| T11 Unexpected RCE and Code Attacks | Partial | The gate parses nested shells and command substitutions to find what would actually run, and denies commands nested too deeply to inspect (`gate.too_deep`). Text an editor writes into a file is treated as data, not a command. | No sandbox. The parser's documented limits (`niyantrak/gate/shell.py`): the contents of a script file or an interpreter call (`./deploy.sh`, `python -c`) and `curl ... \| sh` are opaque, and shell variables are not expanded. It guards against accidents and the obvious, not a determined attacker. |
| T12 Agent Communication Poisoning | Not yet | Machine-to-control-node traffic in the join flow is signed and pinned (see T9). | No agent-to-agent message protection. Out of scope today. |
| T13 Rogue Agents in Multi-Agent Systems | Partial | Each coding agent on a gated machine passes through the same hard stops, and each decision names the agent that asked. | No multi-agent monitoring or containment. |
| T14 Human Attacks on Multi-Agent Systems | Not yet | Nothing specific. | Out of scope today. |
| T15 Human Manipulation | Not yet | Nothing specific for customer-facing conversations in the evaluation edition. | Out of scope today. |

## What the counts look like

Of the 25 items above, none is fully **Covered** by the evaluation edition. That is deliberate honesty, not modesty: the
evaluation tools give strong evidence and hard limits for a few risks (LLM02, LLM06, T2, T3, T8, T9, T11), and say nothing
useful about others. If you need one of the gaps closed, open an issue or check the [roadmap](ROADMAP.md).

## How to check it yourself

```bash
# LLM02: what a model would receive; values replaced by placeholders, checksums decide what counts
niyantrak scan "My Aadhaar is 2345 6789 0124, PAN ABCPE1234F, card 4111 1111 1111 1111"

# LLM06 / T2 / T3 / T11: install the hard-stop hook into every supported agent CLI, then check where it went
niyantrak gate install --cli all
niyantrak gate status

# T8: verify the tamper-evident stores (needs the [telemetry] / [decisions] extras)
niyantrak telemetry verify
niyantrak decisions verify

# LLM03: scan every blob of every commit for keys and private infrastructure details
python3 tools/leak-scan.py --history
```

The unit tests behind each claim are in `tests/unit/` (for example `test_gate_engine.py`, `test_telemetry_privacy.py`,
`test_decisions.py`, `test_join.py`, `test_identity.py`), and the latest run is recorded in `proof/latest/`.

## Reading list

- [OWASP Top 10 for LLM Applications 2025](https://genai.owasp.org/llm-top-10/): the item list used in Table 1, with a page per risk.
- [OWASP Top 10 for LLM Applications 2025, full document](https://genai.owasp.org/resource/owasp-top-10-for-llm-applications-2025/): the downloadable PDF with descriptions, examples and mitigations.
- [OWASP Agentic AI – Threats and Mitigations](https://genai.owasp.org/resource/agentic-ai-threats-and-mitigations/): the T1 to T15 threat model used in Table 2, with mitigation playbooks.
- [OWASP Top 10 for Agentic Applications for 2026](https://genai.owasp.org/resource/owasp-top-10-for-agentic-applications-for-2026/): the newer ASI01 to ASI10 list (December 2025), which regroups the T1 to T15 threats; a future version of this page will map to it.
- [OWASP AI Exchange](https://owaspai.org/): a large, free and open guide to securing AI systems end to end; useful for controls beyond this page.
- [NIST AI Risk Management Framework (AI 100-1)](https://nvlpubs.nist.gov/nistpubs/ai/NIST.AI.100-1.pdf): the voluntary framework many organisations use to structure AI risk work.
- [NIST Generative AI Profile (AI 600-1)](https://doi.org/10.6028/NIST.AI.600-1): applies the AI RMF to generative AI risks and actions.
- [MITRE ATLAS](https://atlas.mitre.org/): a knowledge base of real attack techniques against AI systems, useful for threat modelling and red-team planning.

OWASP and the list names are those of the OWASP Foundation. This page is maintained by the Niyantrak project and
is not reviewed or endorsed by OWASP, NIST or MITRE. Corrections are welcome as issues or pull requests.
