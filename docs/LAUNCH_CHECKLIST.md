# Launch checklist — free edition v0.1.0

Published as **github.com/vigyanbytes/niyantrak** on 23 Oct 2026. The public repository starts from one fresh commit
(no private working history). Legend: ✅ done · ⚠️ done with a caveat · ⏳ pending · 🔒 needs the founder.

## 1. Nothing private in what we publish
| Item | Status | Evidence / next step |
|---|---|---|
| Working-tree leak scan (keys, tokens, private addresses, private terms) | ✅ | `python3 tools/leak-scan.py` → clean, with the private-terms file |
| Whole-history scan: every blob of every commit on every ref, plus commit metadata | ✅ | `python3 tools/leak-scan.py --history` → clean on the published history |
| Commit metadata (author/committer, messages) | ✅ | fresh single-commit history authored `VigyanBytes <info@vigyanbytes.com>` |
| gitleaks over full history | ✅ | one known finding = a test fixture string in `tests/unit/test_decisions.py` (the decision log must refuse secret-shaped text), recorded in `.gitleaksignore`; its fingerprint holds a commit id, so re-check it on the published history |
| `--history` in CI | ✅ | CI checks out full history (`fetch-depth: 0`) and runs `tools/leak-scan.py --history` |
| Private-terms list kept outside the repo; CI reads it from a repository secret | 🔒 | create the `NIYANTRAK_PRIVATE_TERMS` repository secret |

## 2. Docs a stranger can follow
| Item | Status | Evidence / next step |
|---|---|---|
| README: what/why, alpha status, quickstart (Ubuntu + Windows), walkthrough GIF + video, screenshots, editions, proof | ✅ | `README.md`, `docs/media/` |
| Quickstart, architecture, FAQ, 6W format | ✅ | `docs/QUICKSTART.md`, `docs/ARCHITECTURE.md`, `docs/FAQ.md`, `docs/6W.md` |
| Querying 6W activity and decisions (thirteen questions → SQL → real output; CSV/JSON/Markdown/Parquet) | ✅ | `docs/QUERYING_6W.md`, `niyantrak telemetry ask|sql` |
| OWASP mapping (LLM Top 10 2025, Agentic AI threats T1–T15) with honest status and reading list | ✅ | `docs/OWASP.md` |
| Security policy (private disclosure, supported versions, scope) | ✅ | `SECURITY.md` — GitHub private vulnerability reporting + info@vigyanbytes.com |
| Contributing guide | ✅ | `CONTRIBUTING.md` — DCO sign-off, no CLA (founder decision 2026-10-23); README "Editions & licensing" |
| Code of conduct (Contributor Covenant 2.1) | ✅ | `CODE_OF_CONDUCT.md` — contact info@vigyanbytes.com |
| Issue + PR templates | ✅ | `.github/ISSUE_TEMPLATE/`, `.github/PULL_REQUEST_TEMPLATE.md` |
| Changelog with v0.1.0 notes | ✅ | `CHANGELOG.md` (released 2026-10-23) |
| Repository URL in docs and metadata | ✅ | `github.com/vigyanbytes/niyantrak` |
| Trademark clearance for the name "Niyantrak" | 🔒 | README states it is a working name |

## 3. Packaging
| Item | Status | Evidence / next step |
|---|---|---|
| Metadata: SPDX licence, classifiers (Alpha, 3.10–3.13, Linux/Windows), keywords, URLs, extras | ✅ | `pyproject.toml`; `tests/unit/test_packaging.py` |
| `python -m build` → sdist + wheel, attached to the v0.1.0 GitHub release | ✅ | LICENSE + NOTICE in the wheel |
| Wheel installs into a fresh venv; `niyantrak scan` and `niyantrak panel --help` work | ✅ | `NIYANTRAK_PACKAGING_TEST=1 pytest tests/unit/test_packaging.py` |
| Python 3.10 actually exercised | ⏳ | tests run on 3.13 (dev) and 3.12 (CI); add a 3.10 job |
| Publish to PyPI | 🔒 | not required for launch; README installs from the repository |

## 4. Fresh-machine check
| Item | Status | Evidence / next step |
|---|---|---|
| Ubuntu 24.04 clean container: install wheel, `scan`, start `panel`, `GET /` and `POST /api/scan` | ✅ | `bash tools/fresh-machine-check.sh dist/niyantrak-0.1.0-py3-none-any.whl` |
| Windows: panel + scan without WSL | ⚠️ | a frozen build of this code on a Windows laptop (2026-10-23): `scan`, `telemetry ask`, `decisions write` (identity from the Windows logon, SID) and the panel API all work; found and fixed two Windows bugs. The README pip quickstart on Windows is still to be run |
| Ubuntu 22.04 (Python 3.10) | ⏳ | same script with `ubuntu:22.04` |

## 5. Product honesty
| Item | Status | Evidence / next step |
|---|---|---|
| "Alpha" status stated in README, FAQ, changelog, classifiers | ✅ | |
| Screenshots and video marked as sample data | ✅ | fictional team from `tools/demo-data.py`; every screen carries a *Sample data* badge |
| OWASP status stated as our own assessment, no item claimed fully covered | ✅ | `docs/OWASP.md` |
| External security review of panel + join + gate | ⏳ | internal review before wider promotion; external audit after |

## 6. Go-live
| Item | Status |
|---|---|
| Unit suite, coverage, leak scan (tree + history) green; `tools/prove.py` evidence committed | ✅ |
| Public repository created with description and topics | ✅ |
| Tag `v0.1.0` | ✅ |
| GitHub release with sdist + wheel | 🔒 the founder publishes it (release notes and SHA-256 sums prepared) |
| Private vulnerability reporting; branch protection on `main` (no force-push, no deletion, admins included) | ✅ |
| CI green on GitHub (unit suite with pwsh + shellcheck, coverage, leak scan tree + history) | ✅ |
| Required CI status check on `main` | ⏳ |
