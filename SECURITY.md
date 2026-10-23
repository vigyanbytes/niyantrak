# Security policy

## Reporting a vulnerability
**Please report privately. Do not open a public issue, discussion or pull request for a vulnerability.**

- GitHub private vulnerability reporting on this repository: *Security → Report a vulnerability*
  (<https://github.com/vigyanbytes/niyantrak/security/advisories/new>), or
- email **info@vigyanbytes.com** with "SECURITY" in the subject

Please include: the affected version or commit, what an attacker can do, steps to reproduce, and whether it is
already public. Do not include real personal data in a report; use the test values from the README.

What to expect (targets for an alpha project with a small team):
| Step | Target |
|---|---|
| Acknowledge your report | 3 working days |
| First assessment (accepted / not a vulnerability / need more info) | 10 working days |
| Fix or mitigation for confirmed high/critical issues | 30 days, coordinated with you |
| Public advisory | after a fix is released, crediting you unless you prefer otherwise |

We will not take legal action against good-faith research that follows this policy, avoids privacy violations and
service disruption, and gives us reasonable time to fix before disclosure.

## Supported versions
| Version | Supported |
|---|---|
| 0.1.x (alpha) | ✅ security fixes on the latest 0.1 release only |
| anything older / unreleased branches | ❌ |

Until 1.0, only the most recent release receives fixes; please upgrade before reporting.

## Scope
In scope — the code in this repository:
- identifier detection (`niyantrak scan`) leaking values it should hide, or crashing on crafted input
- the panel (`niyantrak panel`): authentication/loopback bypass for join and approval, path traversal in
  `/proof/` or `/docs/`, XSS, request smuggling, anything reachable from the network listeners
- the join flow and TLS pinning: token reuse, card/host-key forgery, impersonation not detected
- the agent gate: a hard-stop command or credential read that is allowed (a bypass)
- 5W events or the decision log storing message text or identifier values; tamper-evidence bypass
- node bootstrap leaving a machine less secure than it found it
- secrets or private infrastructure details committed to this repository

Out of scope: the commercial editions (report those through your support channel); vulnerabilities in Python,
OpenSSL, OpenSSH or other upstream software (report upstream, tell us if Niyantrak makes it worse); denial of service
needing local root; findings from automated scanners without a demonstrated impact; social engineering.
